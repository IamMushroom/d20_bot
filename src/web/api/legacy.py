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
from web.api.common import ApiEndpoint
from web.http import Request, ResponseTuple


class LegacyApi(ApiEndpoint):
    """Deprecated action-based `/api/*` compatibility endpoints."""

    def __init__(
        self,
        access: AdminAccessService,
        campaigns: CampaignService,
        sessions: SessionService,
        outbox: OutboxService,
        identities: IdentityProvider | None,
        rate_limiter: RateLimiter | None,
        token: str,
        web_base_url: str,
    ) -> None:
        super().__init__(token, rate_limiter)
        self._access, self._campaigns, self._sessions, self._outbox = (
            access,
            campaigns,
            sessions,
            outbox,
        )
        self._identities, self._web_base_url = identities, web_base_url

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
        try:
            chat_id, user_id = int(request.form['chat_id'][0]), int(request.form['user_id'][0])
            chat_title = request.form.get('chat_title', [None])[0] or None
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
        form, action = request.form, request.form.get('action', [''])[0]
        try:
            if action == 'get':
                chat_id = int(form['chat_id'][0])
                session = await self._sessions.get_planned(chat_id)
                message = (
                    game_message(session, await self._sessions.get_announcement_timezone(chat_id))
                    if session
                    else '📅 Следующая игра пока не назначена.'
                )
                return self._json(HTTPStatus.OK, {'message': message})
            if action == 'schedule':
                chat_id = int(form['chat_id'][0])
                scheduled_at = datetime.fromisoformat(form['scheduled_at'][0])
                foundry_url = form.get('foundry_url', [''])[0]
                foundry_url = (
                    foundry_url
                    or await self._sessions.get_default_url(chat_id)
                    or getenv('D20_BOT_FOUNDRY_URL', '')
                )
                if scheduled_at.tzinfo is None or not valid_url(foundry_url):
                    raise ValueError
                result = await self._sessions.schedule(
                    chat_id,
                    form.get('chat_title', [''])[0] or None,
                    scheduled_at.astimezone(UTC),
                    foundry_url,
                )
                return self._json(
                    HTTPStatus.OK,
                    {
                        'session_id': result.session.id,
                        'message': game_message(
                            result.session, await self._sessions.get_announcement_timezone(chat_id)
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
            chat_id, action = int(form['chat_id'][0]), form.get('action', [''])[0]
            if action == 'get':
                url = await self._sessions.get_default_url(chat_id) or getenv(
                    'D20_BOT_FOUNDRY_URL', ''
                )
                return self._json(HTTPStatus.OK, {'url': url if valid_url(url) else None})
            if action == 'set':
                url = form['foundry_url'][0]
                if not valid_url(url):
                    raise ValueError
                await self._sessions.set_default_url(chat_id, url, datetime.now(UTC))
                return self._json(HTTPStatus.OK, {'ok': True})
        except KeyError, ValueError, IndexError:
            return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_request'})
        return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_action'})

    async def session(self, request: Request) -> ResponseTuple:
        if not self._authorized(request.headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
        try:
            chat_id, user_id, action = (
                int(request.form['chat_id'][0]),
                int(request.form['user_id'][0]),
                request.form.get('action', [''])[0],
            )
        except KeyError, ValueError, IndexError:
            return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_request'})
        if action == 'start':
            title = request.form.get('title', [''])[0].strip() or None
            if title is not None and len(title) > 100:
                return self._json(HTTPStatus.BAD_REQUEST, {'error': 'title_too_long'})
            result = await self._sessions.start(chat_id, user_id, title)
            if result.status is SessionStartStatus.FORBIDDEN:
                return self._json(HTTPStatus.OK, {'status': 'forbidden'})
            if result.status is SessionStartStatus.ALREADY_ACTIVE:
                return self._json(HTTPStatus.OK, {'status': 'already_active'})
            assert result.session is not None
            return self._json(
                HTTPStatus.OK,
                {
                    'status': 'started',
                    'number': result.session.number,
                    'title': result.session.title,
                    'announcement_message_id': result.announcement_message_id,
                },
            )
        if action == 'stop':
            result = await self._sessions.stop(chat_id, user_id)
            if result.status is SessionStopStatus.FORBIDDEN:
                return self._json(HTTPStatus.OK, {'status': 'forbidden'})
            if result.status is SessionStopStatus.NO_ACTIVE_SESSION:
                return self._json(HTTPStatus.OK, {'status': 'no_active_session'})
            assert result.session is not None
            return self._json(HTTPStatus.OK, {'status': 'stopped', 'number': result.session.number})
        return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_action'})

    async def role(self, request: Request) -> ResponseTuple:
        if not self._authorized(request.headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
        try:
            chat_id, user_id = int(request.form['chat_id'][0]), int(request.form['user_id'][0])
            action = request.form.get('action', [''])[0]
        except KeyError, ValueError, IndexError:
            return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_request'})
        title = request.form.get('chat_title', [''])[0] or None
        if action == 'assign_master':
            await self._campaigns.assign_master(chat_id, user_id, title)
            return self._json(HTTPStatus.OK, {'ok': True})
        if action == 'register_player':
            name = request.form.get('name', [''])[0].strip()
            if not name or len(name) > 16:
                return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_name'})
            result = await self._campaigns.register_player(chat_id, user_id, name, title)
            if result.status is PlayerRegistrationStatus.MASTER_CONFLICT:
                return self._json(HTTPStatus.OK, {'status': 'master_conflict'})
            assert result.character is not None
            return self._json(
                HTTPStatus.OK, {'status': 'registered', 'name': result.character.name}
            )
        return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_action'})

    async def web_url(self, request: Request) -> ResponseTuple:
        if not self._authorized(request.headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
        try:
            chat_id, action = int(request.form['chat_id'][0]), request.form.get('action', [''])[0]
            if action == 'get':
                return self._json(
                    HTTPStatus.OK,
                    {
                        'url': await self._sessions.get_web_base_url(chat_id)
                        or self._web_base_url
                        or None
                    },
                )
            if action == 'set':
                url = request.form['web_url'][0].rstrip('/')
                if not valid_url(url):
                    raise ValueError
                await self._sessions.set_web_base_url(chat_id, url, datetime.now(UTC))
                return self._json(HTTPStatus.OK, {'ok': True})
        except KeyError, ValueError, IndexError:
            return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_request'})
        return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_action'})

    async def events(self, request: Request) -> ResponseTuple:
        if not self._authorized(request.headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
        action = request.form.get('action', [''])[0]
        if action == 'get':
            events = await self._outbox.pending()
            return self._json(
                HTTPStatus.OK,
                {
                    'events': [
                        {'id': e.id, 'type': e.event_type, 'payload': e.payload} for e in events
                    ]
                },
            )
        if action == 'ack':
            try:
                event_id = int(request.form['event_id'][0])
            except KeyError, ValueError, IndexError:
                return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_request'})
            await self._outbox.acknowledge(event_id)
            return self._json(HTTPStatus.OK, {'ok': True})
        return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_action'})
