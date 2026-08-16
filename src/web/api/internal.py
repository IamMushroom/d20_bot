import json
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from os import getenv

from auth import IdentityProvider, RateLimiter, UnknownTelegramUser
from game import game_message, valid_url
from services import (
    CampaignService,
    OutboxService,
    PlayerRegistrationStatus,
    SessionService,
    SessionStartStatus,
    SessionStopStatus,
)
from web.access import AdminAccessService, AdminIdentity
from web.http import Request, ResponseTuple


class InternalApi:
    def __init__(
        self,
        access: AdminAccessService,
        campaigns: CampaignService,
        sessions: SessionService,
        outbox: OutboxService,
        identities: IdentityProvider | None,
        rate_limiter: RateLimiter | None,
        internal_token: str,
        web_base_url: str,
    ) -> None:
        self._access = access
        self._campaigns = campaigns
        self._sessions = sessions
        self._outbox = outbox
        self._identities = identities
        self._rate_limiter = rate_limiter
        self._internal_token = internal_token
        self._web_base_url = web_base_url

    async def registration(self, request: Request) -> ResponseTuple:
        if not self._authorized(request.headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
        if self._identities is None:
            return self._json(HTTPStatus.SERVICE_UNAVAILABLE, {'error': 'auth_disabled'})
        try:
            user_id = int(request.form['user_id'][0])
        except KeyError, ValueError, IndexError:
            return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_request'})
        limited = await self._rate_limit(f'registration-code:{user_id}', 5, timedelta(minutes=15))
        if limited is not None:
            return limited
        try:
            code = await self._identities.issue_registration_code(user_id)
        except UnknownTelegramUser:
            return self._json(HTTPStatus.NOT_FOUND, {'error': 'unknown_user'})
        return self._json(HTTPStatus.OK, {'code': code})

    async def admin_link(self, request: Request) -> ResponseTuple:
        if not self._authorized(request.headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
        form = request.form
        try:
            chat_id = int(form['chat_id'][0])
            user_id = int(form['user_id'][0])
            chat_title = form.get('chat_title', [None])[0] or None
        except KeyError, ValueError, IndexError:
            return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_request'})
        if not await self._campaigns.is_master(chat_id, user_id):
            return self._json(HTTPStatus.FORBIDDEN, {'error': 'forbidden'})
        limited = await self._rate_limit(f'admin-link:{user_id}', 5, timedelta(minutes=10))
        if limited is not None:
            return limited
        base_url = await self._sessions.get_web_base_url(chat_id) or self._web_base_url
        if not base_url:
            return self._json(HTTPStatus.CONFLICT, {'error': 'web_url_not_configured'})
        token = await self._access.create_login(AdminIdentity(chat_id, user_id, chat_title))
        return self._json(HTTPStatus.OK, {'url': f'{base_url.rstrip("/")}/login?token={token}'})

    async def game(self, request: Request) -> ResponseTuple:
        if not self._authorized(request.headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
        form = request.form
        action = form.get('action', [''])[0]
        try:
            if action == 'get':
                chat_id = int(form['chat_id'][0])
                session = await self._sessions.get_planned(chat_id)
                timezone_name = await self._sessions.get_announcement_timezone(chat_id)
                message = (
                    game_message(session, timezone_name)
                    if session
                    else '📅 Следующая игра пока не назначена.'
                )
                return self._json(HTTPStatus.OK, {'message': message})
            if action == 'schedule':
                chat_id = int(form['chat_id'][0])
                scheduled_at = datetime.fromisoformat(form['scheduled_at'][0])
                chat_title = form.get('chat_title', [''])[0] or None
                foundry_url = form.get('foundry_url', [''])[0]
                if not foundry_url:
                    foundry_url = await self._sessions.get_default_url(chat_id) or getenv(
                        'D20_BOT_FOUNDRY_URL', ''
                    )
                if scheduled_at.tzinfo is None or not valid_url(foundry_url):
                    raise ValueError
                result = await self._sessions.schedule(
                    chat_id, chat_title, scheduled_at.astimezone(UTC), foundry_url
                )
                return self._json(
                    HTTPStatus.OK,
                    {
                        'session_id': result.session.id,
                        'message': game_message(
                            result.session,
                            await self._sessions.get_announcement_timezone(chat_id),
                        ),
                        'previous_message_id': result.previous_message_id,
                    },
                )
            if action == 'set_announcement':
                await self._sessions.set_announcement(
                    int(form['session_id'][0]), int(form['message_id'][0])
                )
                return self._json(HTTPStatus.OK, {'ok': True})
        except KeyError, ValueError, IndexError:
            return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_request'})
        return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_action'})

    async def game_url(self, request: Request) -> ResponseTuple:
        if not self._authorized(request.headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
        form = request.form
        try:
            chat_id = int(form['chat_id'][0])
            action = form.get('action', [''])[0]
            if action == 'get':
                url = await self._sessions.get_default_url(chat_id) or getenv(
                    'D20_BOT_FOUNDRY_URL', ''
                )
                return self._json(HTTPStatus.OK, {'url': url if valid_url(url) else None})
            if action == 'set':
                foundry_url = form['foundry_url'][0]
                if not valid_url(foundry_url):
                    raise ValueError
                await self._sessions.set_default_url(chat_id, foundry_url, datetime.now(UTC))
                return self._json(HTTPStatus.OK, {'ok': True})
        except KeyError, ValueError, IndexError:
            return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_request'})
        return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_action'})

    async def session(self, request: Request) -> ResponseTuple:
        if not self._authorized(request.headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
        form = request.form
        try:
            chat_id = int(form['chat_id'][0])
            user_id = int(form['user_id'][0])
            action = form.get('action', [''])[0]
        except KeyError, ValueError, IndexError:
            return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_request'})
        if action == 'start':
            title = form.get('title', [''])[0].strip() or None
            if title is not None and len(title) > 100:
                return self._json(HTTPStatus.BAD_REQUEST, {'error': 'title_too_long'})
            result = await self._sessions.start(chat_id, user_id, title)
            if result.status is SessionStartStatus.FORBIDDEN:
                return self._json(HTTPStatus.OK, {'status': 'forbidden'})
            if result.status is SessionStartStatus.ALREADY_ACTIVE:
                return self._json(HTTPStatus.OK, {'status': 'already_active'})
            session = result.session
            assert session is not None
            return self._json(
                HTTPStatus.OK,
                {
                    'status': 'started',
                    'number': session.number,
                    'title': session.title,
                    'announcement_message_id': result.announcement_message_id,
                },
            )
        if action == 'stop':
            result = await self._sessions.stop(chat_id, user_id)
            if result.status is SessionStopStatus.FORBIDDEN:
                return self._json(HTTPStatus.OK, {'status': 'forbidden'})
            if result.status is SessionStopStatus.NO_ACTIVE_SESSION:
                return self._json(HTTPStatus.OK, {'status': 'no_active_session'})
            session = result.session
            assert session is not None
            return self._json(HTTPStatus.OK, {'status': 'stopped', 'number': session.number})
        return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_action'})

    async def role(self, request: Request) -> ResponseTuple:
        if not self._authorized(request.headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
        form = request.form
        try:
            chat_id = int(form['chat_id'][0])
            user_id = int(form['user_id'][0])
            action = form.get('action', [''])[0]
            chat_title = form.get('chat_title', [''])[0] or None
        except KeyError, ValueError, IndexError:
            return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_request'})
        if action == 'assign_master':
            await self._campaigns.assign_master(chat_id, user_id, chat_title)
            return self._json(HTTPStatus.OK, {'ok': True})
        if action == 'register_player':
            name = form.get('name', [''])[0].strip()
            if not name or len(name) > 16:
                return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_name'})
            result = await self._campaigns.register_player(chat_id, user_id, name, chat_title)
            if result.status is PlayerRegistrationStatus.MASTER_CONFLICT:
                return self._json(HTTPStatus.OK, {'status': 'master_conflict'})
            character = result.character
            assert character is not None
            return self._json(HTTPStatus.OK, {'status': 'registered', 'name': character.name})
        return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_action'})

    async def web_url(self, request: Request) -> ResponseTuple:
        if not self._authorized(request.headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
        form = request.form
        try:
            chat_id = int(form['chat_id'][0])
            action = form.get('action', [''])[0]
            if action == 'get':
                url = await self._sessions.get_web_base_url(chat_id) or self._web_base_url
                return self._json(HTTPStatus.OK, {'url': url or None})
            if action == 'set':
                web_url = form['web_url'][0].rstrip('/')
                if not valid_url(web_url):
                    raise ValueError
                await self._sessions.set_web_base_url(chat_id, web_url, datetime.now(UTC))
                return self._json(HTTPStatus.OK, {'ok': True})
        except KeyError, ValueError, IndexError:
            return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_request'})
        return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_action'})

    async def events(self, request: Request) -> ResponseTuple:
        if not self._authorized(request.headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
        form = request.form
        action = form.get('action', [''])[0]
        if action == 'get':
            events = await self._outbox.pending()
            return self._json(
                HTTPStatus.OK,
                {
                    'events': [
                        {'id': event.id, 'type': event.event_type, 'payload': event.payload}
                        for event in events
                    ]
                },
            )
        if action == 'ack':
            try:
                event_id = int(form['event_id'][0])
            except KeyError, ValueError, IndexError:
                return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_request'})
            await self._outbox.acknowledge(event_id)
            return self._json(HTTPStatus.OK, {'ok': True})
        return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_action'})

    async def list_events(self, request: Request) -> ResponseTuple:
        if not self._authorized(request.headers):
            return self._error(
                HTTPStatus.UNAUTHORIZED,
                'unauthorized',
                'A valid Core bearer token is required.',
            )
        events = await self._outbox.pending()
        return self._json(
            HTTPStatus.OK,
            {
                'events': [
                    {'id': event.id, 'type': event.event_type, 'payload': event.payload}
                    for event in events
                ]
            },
        )

    async def acknowledge_event(self, request: Request) -> ResponseTuple:
        if not self._authorized(request.headers):
            return self._error(
                HTTPStatus.UNAUTHORIZED,
                'unauthorized',
                'A valid Core bearer token is required.',
            )
        try:
            event_id = int(request.path_parameters['event_id'])
            if event_id <= 0:
                raise ValueError
        except KeyError, ValueError:
            return self._error(
                HTTPStatus.BAD_REQUEST,
                'invalid_event_id',
                'Event ID must be a positive integer.',
            )
        await self._outbox.acknowledge(event_id)
        return self._json(HTTPStatus.OK, {'ok': True})

    def _authorized(self, headers: Mapping[str, str]) -> bool:
        authorization = headers.get('authorization', '')
        supplied = (
            authorization.removeprefix('Bearer ') if authorization.startswith('Bearer ') else ''
        )
        return bool(self._internal_token) and secrets.compare_digest(supplied, self._internal_token)

    async def _rate_limit(self, key: str, limit: int, window: timedelta) -> ResponseTuple | None:
        if self._rate_limiter is None:
            return None
        result = await self._rate_limiter.hit(key, limit=limit, window=window)
        if result.allowed:
            return None
        status, headers, body = self._json(
            HTTPStatus.TOO_MANY_REQUESTS,
            {'error': 'rate_limited', 'retry_after': result.retry_after},
        )
        return status, {**headers, 'Retry-After': str(result.retry_after)}, body

    @staticmethod
    def _json(status: HTTPStatus, payload: Mapping[str, object]) -> ResponseTuple:
        return (
            status,
            {'Content-Type': 'application/json; charset=utf-8'},
            json.dumps(payload, ensure_ascii=False).encode(),
        )

    @classmethod
    def _error(cls, status: HTTPStatus, code: str, message: str) -> ResponseTuple:
        return cls._json(status, {'error': {'code': code, 'message': message}})
