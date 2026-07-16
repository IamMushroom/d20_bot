import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from web.session_store import AdminIdentity, StoredWebSession, WebSessionStore


@dataclass(frozen=True, slots=True)
class ActiveWebSession:
    revocation_id: str
    created_at: datetime
    expires_at: datetime
    current: bool


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AdminAccessService:
    def __init__(self, store: WebSessionStore) -> None:
        self._store = store

    async def create_login(self, identity: AdminIdentity) -> str:
        now = datetime.now(UTC)
        await self._store.purge(now)
        token = secrets.token_urlsafe(32)
        await self._store.save_login(_hash(token), identity, now + timedelta(minutes=15))
        return token

    async def consume_login(self, token: str) -> str | None:
        now = datetime.now(UTC)
        identity = await self._store.consume_login(_hash(token), now)
        if identity is None:
            return None
        return await self.create_session(identity)

    async def create_session(self, identity: AdminIdentity) -> str:
        now = datetime.now(UTC)
        await self._store.purge(now)
        session_id = secrets.token_urlsafe(32)
        await self._store.save_session(
            _hash(session_id),
            StoredWebSession(
                identity=identity,
                created_at=now,
                expires_at=now + timedelta(hours=8),
                csrf_token=secrets.token_urlsafe(32),
                revocation_id=secrets.token_urlsafe(18),
            ),
        )
        return session_id

    async def authenticate(self, session_id: str | None) -> AdminIdentity | None:
        session = await self._session(session_id)
        return session.identity if session else None

    async def csrf_token(self, session_id: str | None) -> str | None:
        session = await self._session(session_id)
        return session.csrf_token if session else None

    async def revoke(self, session_id: str | None) -> None:
        if session_id:
            await self._store.delete_session(_hash(session_id))

    async def list_sessions(
        self, identity: AdminIdentity, current_session_id: str
    ) -> tuple[ActiveWebSession, ...]:
        sessions = await self._store.list_sessions(identity.user_id, datetime.now(UTC))
        current = await self._session(current_session_id)
        return tuple(
            ActiveWebSession(
                revocation_id=session.revocation_id,
                created_at=session.created_at,
                expires_at=session.expires_at,
                current=(
                    current is not None
                    and secrets.compare_digest(session.revocation_id, current.revocation_id)
                ),
            )
            for session in sessions
        )

    async def revoke_by_id(self, identity: AdminIdentity, revocation_id: str) -> bool:
        return await self._store.delete_by_revocation_id(identity.user_id, revocation_id)

    async def _session(self, session_id: str | None) -> StoredWebSession | None:
        if not session_id:
            return None
        return await self._store.get_session(_hash(session_id), datetime.now(UTC))


__all__ = ['ActiveWebSession', 'AdminAccessService', 'AdminIdentity']
