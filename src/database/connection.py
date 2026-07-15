import asyncio
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

type Parameters = Sequence[object]
type Row = Mapping[str, object]


class Database(Protocol):
    async def execute(self, query: str, parameters: Parameters = ()) -> int: ...

    async def fetch_one(self, query: str, parameters: Parameters = ()) -> Row | None: ...

    async def fetch_all(self, query: str, parameters: Parameters = ()) -> list[Row]: ...

    async def executescript(self, script: str) -> None: ...

    async def close(self) -> None: ...


class SQLiteDatabase:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self._lock = asyncio.Lock()

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
        async with self._lock:
            cursor = await asyncio.to_thread(self._connection.execute, query, parameters)
            return cursor.rowcount

    async def fetch_one(self, query: str, parameters: Parameters = ()) -> Row | None:
        async with self._lock:
            cursor = await asyncio.to_thread(self._connection.execute, query, parameters)
            row = await asyncio.to_thread(cursor.fetchone)
            return dict(row) if row is not None else None

    async def fetch_all(self, query: str, parameters: Parameters = ()) -> list[Row]:
        async with self._lock:
            cursor = await asyncio.to_thread(self._connection.execute, query, parameters)
            rows = await asyncio.to_thread(cursor.fetchall)
            return [dict(row) for row in rows]

    async def executescript(self, script: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._connection.executescript, script)

    async def close(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._connection.close)


async def create_database(url: str) -> Database:
    prefix = 'sqlite:///'
    if not url.startswith(prefix):
        scheme = url.partition(':')[0] or 'unknown'
        raise ValueError(f'Unsupported database scheme: {scheme}')
    path = url.removeprefix(prefix)
    if not path:
        raise ValueError('SQLite database path is empty')
    return await SQLiteDatabase.connect(path)
