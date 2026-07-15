import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True, slots=True)
class AdminIdentity:
    chat_id: int
    user_id: int
    chat_title: str | None


class AdminAccessService:
    def __init__(self) -> None:
        self._logins: dict[str, tuple[AdminIdentity, datetime]] = {}
        self._sessions: dict[str, tuple[AdminIdentity, datetime]] = {}

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
        self._sessions[session_id] = (login[0], datetime.now(UTC) + timedelta(hours=8))
        return session_id

    def authenticate(self, session_id: str | None) -> AdminIdentity | None:
        self._purge()
        session = self._sessions.get(session_id or '')
        return session[0] if session is not None else None

    def _purge(self) -> None:
        now = datetime.now(UTC)
        self._logins = {token: value for token, value in self._logins.items() if value[1] > now}
        self._sessions = {
            session_id: value for session_id, value in self._sessions.items() if value[1] > now
        }
