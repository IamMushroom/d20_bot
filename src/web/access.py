import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True, slots=True)
class AdminIdentity:
    chat_id: int
    user_id: int
    chat_title: str | None


@dataclass(frozen=True, slots=True)
class WebSession:
    identity: AdminIdentity
    created_at: datetime
    expires_at: datetime
    csrf_token: str
    revocation_id: str


@dataclass(frozen=True, slots=True)
class ActiveWebSession:
    revocation_id: str
    created_at: datetime
    expires_at: datetime
    current: bool


class AdminAccessService:
    def __init__(self) -> None:
        self._logins: dict[str, tuple[AdminIdentity, datetime]] = {}
        self._sessions: dict[str, WebSession] = {}

    def create_login(self, identity: AdminIdentity) -> str:
        self._purge()
        token = secrets.token_urlsafe(32)
        self._logins[token] = (identity, datetime.now(UTC) + timedelta(minutes=15))
        return token

    def consume_login(self, token: str) -> str | None:
        self._purge()
        login = self._logins.pop(token, None)
        if login is None:
            return None
        session_id = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        self._sessions[session_id] = WebSession(
            identity=login[0],
            created_at=now,
            expires_at=now + timedelta(hours=8),
            csrf_token=secrets.token_urlsafe(32),
            revocation_id=secrets.token_urlsafe(18),
        )
        return session_id

    def authenticate(self, session_id: str | None) -> AdminIdentity | None:
        self._purge()
        session = self._sessions.get(session_id or '')
        return session.identity if session is not None else None

    def csrf_token(self, session_id: str | None) -> str | None:
        self._purge()
        session = self._sessions.get(session_id or '')
        return session.csrf_token if session is not None else None

    def revoke(self, session_id: str | None) -> None:
        if session_id is not None:
            self._sessions.pop(session_id, None)

    def list_sessions(
        self, identity: AdminIdentity, current_session_id: str
    ) -> tuple[ActiveWebSession, ...]:
        self._purge()
        sessions = (
            ActiveWebSession(
                revocation_id=session.revocation_id,
                created_at=session.created_at,
                expires_at=session.expires_at,
                current=session_id == current_session_id,
            )
            for session_id, session in self._sessions.items()
            if session.identity.chat_id == identity.chat_id
            and session.identity.user_id == identity.user_id
        )
        return tuple(sorted(sessions, key=lambda session: session.created_at, reverse=True))

    def revoke_by_id(self, identity: AdminIdentity, revocation_id: str) -> bool:
        self._purge()
        for session_id, session in self._sessions.items():
            if (
                secrets.compare_digest(session.revocation_id, revocation_id)
                and session.identity.chat_id == identity.chat_id
                and session.identity.user_id == identity.user_id
            ):
                del self._sessions[session_id]
                return True
        return False

    def _purge(self) -> None:
        now = datetime.now(UTC)
        self._logins = {token: value for token, value in self._logins.items() if value[1] > now}
        self._sessions = {
            session_id: value
            for session_id, value in self._sessions.items()
            if value.expires_at > now
        }
