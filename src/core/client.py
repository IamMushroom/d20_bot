import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CORE_CLIENT_KEY = 'core_client'


class CoreClientError(Exception):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ScheduledGame:
    session_id: int
    message: str
    previous_message_id: int | None


@dataclass(frozen=True, slots=True)
class SessionTransition:
    status: str
    number: int | None = None
    title: str | None = None
    announcement_message_id: int | None = None


@dataclass(frozen=True, slots=True)
class PlayerRegistration:
    status: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class CoreEvent:
    id: int
    event_type: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class CoreClient:
    base_url: str
    token: str

    async def create_admin_link(self, chat_id: int, user_id: int, chat_title: str | None) -> str:
        payload = await self._request(
            '/api/admin-link',
            {'chat_id': chat_id, 'user_id': user_id, 'chat_title': chat_title or ''},
        )
        return self._string(payload, 'url')

    async def create_registration_code(self, user_id: int) -> str:
        payload = await self._request('/api/auth/registration', {'user_id': user_id})
        return self._string(payload, 'code')

    async def get_game(self, chat_id: int) -> str:
        payload = await self._request('/api/game', {'action': 'get', 'chat_id': chat_id})
        return self._string(payload, 'message')

    async def schedule_game(
        self,
        chat_id: int,
        chat_title: str | None,
        scheduled_at: datetime,
        foundry_url: str | None,
    ) -> ScheduledGame:
        payload = await self._request(
            '/api/game',
            {
                'action': 'schedule',
                'chat_id': chat_id,
                'chat_title': chat_title or '',
                'scheduled_at': scheduled_at.isoformat(),
                'foundry_url': foundry_url or '',
            },
        )
        session_id = payload.get('session_id')
        previous = payload.get('previous_message_id')
        if not isinstance(session_id, int) or not (previous is None or isinstance(previous, int)):
            raise CoreClientError('Core returned an invalid response')
        return ScheduledGame(session_id, self._string(payload, 'message'), previous)

    async def set_game_announcement(self, session_id: int, message_id: int) -> None:
        await self._request(
            '/api/game',
            {'action': 'set_announcement', 'session_id': session_id, 'message_id': message_id},
        )

    async def get_game_url(self, chat_id: int) -> str | None:
        payload = await self._request('/api/game-url', {'action': 'get', 'chat_id': chat_id})
        value = payload.get('url')
        if value is not None and not isinstance(value, str):
            raise CoreClientError('Core returned an invalid response')
        return value

    async def set_game_url(self, chat_id: int, foundry_url: str) -> None:
        await self._request(
            '/api/game-url', {'action': 'set', 'chat_id': chat_id, 'foundry_url': foundry_url}
        )

    async def get_web_url(self, chat_id: int) -> str | None:
        payload = await self._request('/api/web-url', {'action': 'get', 'chat_id': chat_id})
        value = payload.get('url')
        if value is not None and not isinstance(value, str):
            raise CoreClientError('Core returned an invalid response')
        return value

    async def set_web_url(self, chat_id: int, web_url: str) -> None:
        await self._request(
            '/api/web-url', {'action': 'set', 'chat_id': chat_id, 'web_url': web_url}
        )

    async def start_session(
        self, chat_id: int, user_id: int, title: str | None
    ) -> SessionTransition:
        payload = await self._request(
            '/api/session',
            {'action': 'start', 'chat_id': chat_id, 'user_id': user_id, 'title': title or ''},
        )
        transition = self._session_transition(payload)
        if transition.status not in {'started', 'forbidden', 'already_active'}:
            raise CoreClientError('Core returned an invalid response')
        return transition

    async def stop_session(self, chat_id: int, user_id: int) -> SessionTransition:
        payload = await self._request(
            '/api/session', {'action': 'stop', 'chat_id': chat_id, 'user_id': user_id}
        )
        transition = self._session_transition(payload)
        if transition.status not in {'stopped', 'forbidden', 'no_active_session'}:
            raise CoreClientError('Core returned an invalid response')
        return transition

    async def assign_master(self, chat_id: int, user_id: int, chat_title: str | None) -> None:
        await self._request(
            '/api/role',
            {
                'action': 'assign_master',
                'chat_id': chat_id,
                'user_id': user_id,
                'chat_title': chat_title or '',
            },
        )

    async def register_player(
        self, chat_id: int, user_id: int, name: str, chat_title: str | None
    ) -> PlayerRegistration:
        payload = await self._request(
            '/api/role',
            {
                'action': 'register_player',
                'chat_id': chat_id,
                'user_id': user_id,
                'name': name,
                'chat_title': chat_title or '',
            },
        )
        status = payload.get('status')
        returned_name = payload.get('name')
        if status not in {'registered', 'master_conflict'} or not (
            returned_name is None or isinstance(returned_name, str)
        ):
            raise CoreClientError('Core returned an invalid response')
        return PlayerRegistration(status, returned_name)

    async def get_events(self) -> tuple[CoreEvent, ...]:
        payload = await self._request('/internal/events', {}, method='GET')
        raw_events = payload.get('events')
        if not isinstance(raw_events, list):
            raise CoreClientError('Core returned an invalid response')
        events = []
        for item in raw_events:
            if not isinstance(item, dict):
                raise CoreClientError('Core returned an invalid response')
            event_id = item.get('id')
            event_type = item.get('type')
            event_payload = item.get('payload')
            if (
                not isinstance(event_id, int)
                or not isinstance(event_type, str)
                or not isinstance(event_payload, dict)
            ):
                raise CoreClientError('Core returned an invalid response')
            events.append(CoreEvent(event_id, event_type, event_payload))
        return tuple(events)

    async def acknowledge_event(self, event_id: int) -> None:
        await self._request(f'/internal/events/{event_id}/ack', {})

    async def _request(
        self, path: str, fields: dict[str, object], *, method: str = 'POST'
    ) -> dict[str, object]:
        return await asyncio.to_thread(self._request_sync, path, fields, method=method)

    def _request_sync(
        self, path: str, fields: dict[str, object], *, method: str = 'POST'
    ) -> dict[str, object]:
        encoded = urlencode(fields)
        url = f'{self.base_url.rstrip("/")}{path}'
        if method == 'GET' and encoded:
            url = f'{url}?{encoded}'
        request = Request(
            url,
            data=encoded.encode() if method != 'GET' else None,
            headers={
                'Authorization': f'Bearer {self.token}',
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=5) as response:
                payload = json.load(response)
        except HTTPError as error:
            code = None
            try:
                error_payload = json.load(error)
                detail = error_payload.get('error') if isinstance(error_payload, dict) else None
                if isinstance(detail, dict) and isinstance(detail.get('code'), str):
                    code = detail['code']
            except AttributeError, json.JSONDecodeError, TypeError:
                pass
            raise CoreClientError(f'Core returned HTTP {error.code}', code=code) from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise CoreClientError(f'Core is unavailable: {error}') from error
        if not isinstance(payload, dict):
            raise CoreClientError('Core returned an invalid response')
        return payload

    @staticmethod
    def _string(payload: dict[str, object], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise CoreClientError('Core returned an invalid response')
        return value

    @staticmethod
    def _session_transition(payload: dict[str, object]) -> SessionTransition:
        status = payload.get('status')
        number = payload.get('number')
        title = payload.get('title')
        announcement = payload.get('announcement_message_id')
        if (
            not isinstance(status, str)
            or not (number is None or isinstance(number, int))
            or not (title is None or isinstance(title, str))
            or not (announcement is None or isinstance(announcement, int))
        ):
            raise CoreClientError('Core returned an invalid response')
        return SessionTransition(status, number, title, announcement)
