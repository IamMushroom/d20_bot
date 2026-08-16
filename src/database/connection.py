import asyncio
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Protocol

type Parameters = Sequence[object]
type Row = Mapping[str, object]


class Database(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[None]: ...

    async def execute(self, query: str, parameters: Parameters = ()) -> int: ...

    async def fetch_one(self, query: str, parameters: Parameters = ()) -> Row | None: ...

    async def fetch_all(self, query: str, parameters: Parameters = ()) -> list[Row]: ...

    async def executescript(self, script: str) -> None: ...

    async def close(self) -> None: ...


class SQLiteDatabase:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self._lock = asyncio.Lock()
        self._transaction_owner: asyncio.Task[object] | None = None

    @classmethod
    async def connect(cls, path: str) -> SQLiteDatabase:
        if path != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)

        def open_connection() -> sqlite3.Connection:
            connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys = ON')
            connection.execute('PRAGMA busy_timeout = 5000')
            connection.execute('PRAGMA journal_mode = WAL')
            return connection

        return cls(await asyncio.to_thread(open_connection))

    async def execute(self, query: str, parameters: Parameters = ()) -> int:
        async def operation() -> int:
            cursor = await asyncio.to_thread(self._connection.execute, query, parameters)
            return cursor.rowcount

        return await self._run(operation)

    async def fetch_one(self, query: str, parameters: Parameters = ()) -> Row | None:
        async def operation() -> Row | None:
            cursor = await asyncio.to_thread(self._connection.execute, query, parameters)
            row = await asyncio.to_thread(cursor.fetchone)
            return dict(row) if row is not None else None

        return await self._run(operation)

    async def fetch_all(self, query: str, parameters: Parameters = ()) -> list[Row]:
        async def operation() -> list[Row]:
            cursor = await asyncio.to_thread(self._connection.execute, query, parameters)
            rows = await asyncio.to_thread(cursor.fetchall)
            return [dict(row) for row in rows]

        return await self._run(operation)

    async def executescript(self, script: str) -> None:
        if self._owns_transaction():
            raise RuntimeError('executescript is not supported inside a transaction')
        async with self._lock:
            await asyncio.to_thread(self._connection.executescript, script)

    async def close(self) -> None:
        if self._owns_transaction():
            raise RuntimeError('database cannot be closed inside a transaction')
        async with self._lock:
            await asyncio.to_thread(self._connection.close)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError('transaction requires an asyncio task')
        if self._transaction_owner is task:
            raise RuntimeError('nested transactions are not supported')

        await self._lock.acquire()
        self._transaction_owner = task
        try:
            await asyncio.to_thread(self._connection.execute, 'BEGIN')
            try:
                yield
                await asyncio.to_thread(self._connection.commit)
            except BaseException:
                await asyncio.to_thread(self._connection.rollback)
                raise
        finally:
            self._transaction_owner = None
            self._lock.release()

    def _owns_transaction(self) -> bool:
        return self._transaction_owner is asyncio.current_task()

    async def _run[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        if self._owns_transaction():
            return await operation()
        async with self._lock:
            return await operation()


async def create_database(url: str) -> Database:
    prefix = 'sqlite:///'
    if not url.startswith(prefix):
        scheme = url.partition(':')[0] or 'unknown'
        raise ValueError(f'Unsupported database scheme: {scheme}')
    path = url.removeprefix(prefix)
    if not path:
        raise ValueError('SQLite database path is empty')
    return await SQLiteDatabase.connect(path)
