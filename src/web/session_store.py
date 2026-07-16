from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from database.connection import Database


@dataclass(frozen=True, slots=True)
class AdminIdentity:
    chat_id: int
    user_id: int
    chat_title: str | None


@dataclass(frozen=True, slots=True)
class StoredWebSession:
    identity: AdminIdentity
    created_at: datetime
    expires_at: datetime
    csrf_token: str
    revocation_id: str


class WebSessionStore(Protocol):
    async def save_login(
        self, token_hash: str, identity: AdminIdentity, expires_at: datetime
    ) -> None: ...

    async def consume_login(self, token_hash: str, now: datetime) -> AdminIdentity | None: ...

    async def save_session(self, session_hash: str, session: StoredWebSession) -> None: ...

    async def get_session(self, session_hash: str, now: datetime) -> StoredWebSession | None: ...

    async def delete_session(self, session_hash: str) -> None: ...

    async def list_sessions(
        self, telegram_user_id: int, now: datetime
    ) -> tuple[StoredWebSession, ...]: ...

    async def delete_by_revocation_id(self, telegram_user_id: int, revocation_id: str) -> bool: ...

    async def purge(self, now: datetime) -> None: ...


def _stored_session(row: dict[str, object]) -> StoredWebSession:
    return StoredWebSession(
        identity=AdminIdentity(
            cast(int, row['initial_chat_id']),
            cast(int, row['telegram_user_id']),
            str(row['chat_title']) if row['chat_title'] is not None else None,
        ),
        created_at=datetime.fromisoformat(str(row['created_at'])),
        expires_at=datetime.fromisoformat(str(row['expires_at'])),
        csrf_token=str(row['csrf_token']),
        revocation_id=str(row['revocation_id']),
    )


class SQLiteWebSessionStore:
    def __init__(self, database: Database):
        self._database = database

    async def save_login(
        self, token_hash: str, identity: AdminIdentity, expires_at: datetime
    ) -> None:
        await self._database.execute(
            """INSERT INTO web_login_tokens (
                token_hash, telegram_user_id, initial_chat_id, chat_title, expires_at
            ) VALUES (?, ?, ?, ?, ?)""",
            (
                token_hash,
                identity.user_id,
                identity.chat_id,
                identity.chat_title,
                expires_at.isoformat(),
            ),
        )

    async def consume_login(self, token_hash: str, now: datetime) -> AdminIdentity | None:
        row = await self._database.fetch_one(
            """DELETE FROM web_login_tokens
            WHERE token_hash = ? AND expires_at > ? RETURNING *""",
            (token_hash, now.isoformat()),
        )
        return (
            AdminIdentity(
                cast(int, row['initial_chat_id']),
                cast(int, row['telegram_user_id']),
                str(row['chat_title']) if row['chat_title'] is not None else None,
            )
            if row
            else None
        )

    async def save_session(self, session_hash: str, session: StoredWebSession) -> None:
        await self._database.execute(
            """INSERT INTO web_sessions (
                session_hash, telegram_user_id, initial_chat_id, chat_title,
                csrf_token, revocation_id, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_hash,
                session.identity.user_id,
                session.identity.chat_id,
                session.identity.chat_title,
                session.csrf_token,
                session.revocation_id,
                session.created_at.isoformat(),
                session.expires_at.isoformat(),
            ),
        )

    async def get_session(self, session_hash: str, now: datetime) -> StoredWebSession | None:
        row = await self._database.fetch_one(
            'SELECT * FROM web_sessions WHERE session_hash = ? AND expires_at > ?',
            (session_hash, now.isoformat()),
        )
        return _stored_session(dict(row)) if row else None

    async def delete_session(self, session_hash: str) -> None:
        await self._database.execute(
            'DELETE FROM web_sessions WHERE session_hash = ?', (session_hash,)
        )

    async def list_sessions(
        self, telegram_user_id: int, now: datetime
    ) -> tuple[StoredWebSession, ...]:
        rows = await self._database.fetch_all(
            """SELECT * FROM web_sessions
            WHERE telegram_user_id = ? AND expires_at > ? ORDER BY created_at DESC""",
            (telegram_user_id, now.isoformat()),
        )
        return tuple(_stored_session(dict(row)) for row in rows)

    async def delete_by_revocation_id(self, telegram_user_id: int, revocation_id: str) -> bool:
        changed = await self._database.execute(
            'DELETE FROM web_sessions WHERE telegram_user_id = ? AND revocation_id = ?',
            (telegram_user_id, revocation_id),
        )
        return changed > 0

    async def purge(self, now: datetime) -> None:
        await self._database.execute(
            'DELETE FROM web_login_tokens WHERE expires_at <= ?', (now.isoformat(),)
        )
        await self._database.execute(
            'DELETE FROM web_sessions WHERE expires_at <= ?', (now.isoformat(),)
        )
