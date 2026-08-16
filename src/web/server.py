import asyncio
import json
import logging
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from importlib.resources import files
from ipaddress import ip_address, ip_network
from os import getenv
from urllib.parse import parse_qs, urlsplit

from auth import (
    AuthenticationError,
    IdentityProvider,
    InvalidRegistrationCode,
    LoginAlreadyExists,
    RateLimiter,
    UnknownTelegramUser,
)
from commands.game_utils import ANNOUNCEMENT_TIMEZONES, game_message, valid_url
from services import (
    CampaignService,
    OutboxService,
    PlayerRegistrationStatus,
    SessionService,
    SessionStartStatus,
    SessionStopStatus,
)
from web.access import AdminAccessService, AdminIdentity
from web.views import (
    campaigns_response,
    dashboard_response,
    landing_response,
    login_response,
    page_response,
    sessions_response,
    settings_response,
)

MAX_REQUEST_SIZE = 16 * 1024
APP_JS = files('web').joinpath('static/app.js').read_bytes()


class AdminWebServer:
    def __init__(
        self,
        access: AdminAccessService,
        campaigns: CampaignService,
        sessions: SessionService,
        outbox: OutboxService,
        identities: IdentityProvider | None = None,
        rate_limiter: RateLimiter | None = None,
        internal_token: str = '',
        web_base_url: str = '',
    ) -> None:
        self._access = access
        self._campaigns = campaigns
        self._sessions = sessions
        self._outbox = outbox
        self._identities = identities
        self._rate_limiter = rate_limiter
        self._internal_token = internal_token
        self._web_base_url = web_base_url
        self._server: asyncio.Server | None = None

    async def start(self, host: str, port: int) -> None:
        self._server = await asyncio.start_server(self._handle, host, port)
        logging.info('Admin web server started', extra={'web_host': host, 'web_port': port})

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError('Admin web server is not started')
        async with self._server:
            await self._server.serve_forever()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            method, target, headers, body = await self._read_request(reader)
            peer = writer.get_extra_info('peername')
            remote_host = str(peer[0]) if isinstance(peer, tuple) and peer else None
            status, response_headers, content = await self._route(
                method, target, headers, body, remote_host
            )
        except ValueError, UnicodeError:
            status, response_headers, content = HTTPStatus.BAD_REQUEST, {}, b'Bad request'
        except Exception:
            logging.exception('Admin web request failed')
            status, response_headers, content = HTTPStatus.INTERNAL_SERVER_ERROR, {}, b'Error'
        response_headers = {
            'Content-Type': 'text/html; charset=utf-8',
            'Content-Length': str(len(content)),
            'Connection': 'close',
            'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; script-src 'self' 'unsafe-inline'; form-action 'self'",
            **response_headers,
        }
        head = f'HTTP/1.1 {status.value} {status.phrase}\r\n' + ''.join(
            f'{name}: {value}\r\n' for name, value in response_headers.items()
        )
        writer.write(head.encode() + b'\r\n' + content)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def _read_request(
        self, reader: asyncio.StreamReader
    ) -> tuple[str, str, dict[str, str], bytes]:
        raw_head = await reader.readuntil(b'\r\n\r\n')
        if len(raw_head) > MAX_REQUEST_SIZE:
            raise ValueError('request too large')
        lines = raw_head.decode('ascii').split('\r\n')
        method, target, _version = lines[0].split(' ', 2)
        headers = {
            name.lower(): value.strip()
            for line in lines[1:]
            if line
            for name, value in [line.split(':', 1)]
        }
        length = int(headers.get('content-length', '0'))
        if length < 0 or length > MAX_REQUEST_SIZE:
            raise ValueError('request too large')
        return method, target, headers, await reader.readexactly(length)

    async def _route(
        self,
        method: str,
        target: str,
        headers: Mapping[str, str],
        body: bytes,
        remote_host: str | None = None,
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        url = urlsplit(target)
        if method == 'GET' and url.path == '/health':
            return self._json(HTTPStatus.OK, {'status': 'ok'})
        if method == 'GET' and url.path == '/static/app.js':
            return (
                HTTPStatus.OK,
                {
                    'Content-Type': 'text/javascript; charset=utf-8',
                    'Cache-Control': 'public, max-age=3600',
                },
                APP_JS,
            )
        if method == 'POST' and url.path == '/api/admin-link':
            return await self._admin_link(headers, parse_qs(body.decode()))
        if method == 'POST' and url.path == '/api/auth/registration':
            return await self._registration_api(headers, parse_qs(body.decode()))
        if method == 'POST' and url.path == '/api/game':
            return await self._game_api(headers, parse_qs(body.decode()))
        if method == 'POST' and url.path == '/api/game-url':
            return await self._game_url_api(headers, parse_qs(body.decode()))
        if method == 'POST' and url.path == '/api/session':
            return await self._session_api(headers, parse_qs(body.decode()))
        if method == 'POST' and url.path == '/api/role':
            return await self._role_api(headers, parse_qs(body.decode()))
        if method == 'POST' and url.path == '/api/web-url':
            return await self._web_url_api(headers, parse_qs(body.decode()))
        if method == 'POST' and url.path == '/api/events':
            return await self._events_api(headers, parse_qs(body.decode()))
        if method == 'GET' and url.path == '/login' and url.query:
            token = parse_qs(url.query).get('token', [''])[0]
            session_id = await self._access.consume_login(token)
            if session_id is None:
                return page_response(
                    HTTPStatus.UNAUTHORIZED, 'Ссылка недействительна или уже использована.'
                )
            cookie = self._session_cookie(session_id, headers, remote_host)
            return HTTPStatus.SEE_OTHER, {'Location': '/campaigns', 'Set-Cookie': cookie}, b''
        if method == 'GET' and url.path == '/login':
            return login_response()
        if method == 'GET' and url.path == '/register':
            return login_response(registration=True, code=parse_qs(url.query).get('code', [''])[0])
        if method == 'POST' and url.path == '/login':
            if self._identities is None:
                return page_response(HTTPStatus.SERVICE_UNAVAILABLE, 'Локальный вход отключён.')
            limited = await self._rate_limit(
                f'login:{self._client_ip(headers, remote_host)}',
                limit=10,
                window=timedelta(minutes=10),
            )
            if limited is not None:
                return limited
            form = parse_qs(body.decode())
            user_id = await self._identities.authenticate(
                form.get('login', [''])[0], form.get('password', [''])[0]
            )
            if user_id is None:
                return login_response(error='Неверный логин или пароль.')
            return await self._local_session(user_id, headers, remote_host)
        if method == 'POST' and url.path == '/register':
            if self._identities is None:
                return page_response(HTTPStatus.SERVICE_UNAVAILABLE, 'Регистрация отключена.')
            limited = await self._rate_limit(
                f'register:{self._client_ip(headers, remote_host)}',
                limit=10,
                window=timedelta(minutes=10),
            )
            if limited is not None:
                return limited
            form = parse_qs(body.decode())
            try:
                user_id = await self._identities.register(
                    form.get('code', [''])[0],
                    form.get('login', [''])[0],
                    form.get('password', [''])[0],
                )
            except InvalidRegistrationCode:
                return login_response(error='Код недействителен или просрочен.', registration=True)
            except LoginAlreadyExists:
                return login_response(error='Этот логин уже занят.', registration=True)
            except AuthenticationError:
                return login_response(
                    error='Логин: 3–32 символа A–Z, цифры, точка, дефис или подчёркивание. Пароль — от 10 символов.',
                    registration=True,
                )
            return await self._local_session(user_id, headers, remote_host)

        session_id = self._cookie(headers, 'd20_admin')
        identity = await self._access.authenticate(session_id)
        if identity is None:
            if method == 'GET' and url.path == '/':
                return landing_response()
            return page_response(HTTPStatus.UNAUTHORIZED, 'Запросите новую ссылку командой /admin.')
        form = parse_qs(body.decode()) if method == 'POST' else {}
        if method == 'POST':
            expected = await self._access.csrf_token(session_id)
            supplied = form.get('csrf_token', [''])[0]
            if expected is None or not secrets.compare_digest(expected, supplied):
                return page_response(
                    HTTPStatus.FORBIDDEN, 'Проверка безопасности формы не пройдена.'
                )
        selected_identity = identity
        if method == 'POST' and url.path in {
            '/settings',
            '/schedule',
            '/session/start',
            '/session/stop',
            '/player/invite',
            '/player/rename',
            '/player/remove',
            '/master/transfer',
        }:
            try:
                chat_id = int(form.get('chat_id', [str(identity.chat_id)])[0])
            except ValueError:
                return page_response(HTTPStatus.BAD_REQUEST, 'Некорректная кампания.')
            if not await self._campaigns.is_master(chat_id, identity.user_id):
                return page_response(HTTPStatus.FORBIDDEN, 'Недостаточно прав в этой кампании.')
            selected_identity = AdminIdentity(chat_id, identity.user_id, None)
        if method == 'POST' and url.path == '/logout':
            await self._access.revoke(session_id)
            return (
                HTTPStatus.SEE_OTHER,
                {
                    'Location': '/',
                    'Set-Cookie': 'd20_admin=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0',
                },
                b'',
            )
        if method == 'POST' and url.path == '/sessions/revoke':
            revocation_id = form.get('revocation_id', [''])[0]
            current = any(
                session.current and session.revocation_id == revocation_id
                for session in await self._access.list_sessions(identity, session_id)
            )
            if not revocation_id or not await self._access.revoke_by_id(identity, revocation_id):
                return page_response(HTTPStatus.NOT_FOUND, 'Активная сессия не найдена.')
            headers_out = {'Location': '/sessions'}
            if current:
                headers_out = {
                    'Location': '/',
                    'Set-Cookie': 'd20_admin=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0',
                }
            return HTTPStatus.SEE_OTHER, headers_out, b''
        if method == 'GET' and url.path == '/':
            try:
                chat_id = int(parse_qs(url.query).get('campaign', [str(identity.chat_id)])[0])
            except ValueError:
                return page_response(HTTPStatus.BAD_REQUEST, 'Некорректная кампания.')
            role = await self._campaigns.get_role(chat_id, identity.user_id)
            if role is None:
                return page_response(HTTPStatus.FORBIDDEN, 'Нет доступа к этой кампании.')
            return await self._dashboard(
                AdminIdentity(chat_id, identity.user_id, None), session_id, role
            )
        if method == 'GET' and url.path == '/campaigns':
            return campaigns_response(
                await self._campaigns.list_for_user(identity.user_id),
                identity.chat_id,
                await self._access.csrf_token(session_id) or '',
            )
        if method == 'GET' and url.path == '/settings':
            try:
                chat_id = int(parse_qs(url.query).get('campaign', [str(identity.chat_id)])[0])
            except ValueError:
                return page_response(HTTPStatus.BAD_REQUEST, 'Некорректная кампания.')
            if not await self._campaigns.is_master(chat_id, identity.user_id):
                return page_response(HTTPStatus.FORBIDDEN, 'Настройки доступны только мастеру.')
            return await self._settings(AdminIdentity(chat_id, identity.user_id, None), session_id)
        if method == 'GET' and url.path == '/sessions':
            return sessions_response(
                await self._access.list_sessions(identity, session_id),
                await self._access.csrf_token(session_id) or '',
            )
        if method == 'POST' and url.path == '/settings':
            return await self._save_settings(selected_identity, form)
        if method == 'POST' and url.path == '/schedule':
            return await self._schedule(selected_identity, form)
        if method == 'POST' and url.path == '/session/start':
            return await self._start_session(selected_identity, form)
        if method == 'POST' and url.path == '/session/stop':
            return await self._stop_session(selected_identity)
        if method == 'POST' and url.path == '/player/invite':
            return await self._invite_player(selected_identity, form)
        if method == 'POST' and url.path == '/player/rename':
            return await self._rename_player(selected_identity, form)
        if method == 'POST' and url.path == '/player/remove':
            return await self._remove_player(selected_identity, form)
        if method == 'POST' and url.path == '/master/transfer':
            return await self._transfer_master(selected_identity, form)
        return page_response(HTTPStatus.NOT_FOUND, 'Страница не найдена.')

    async def _local_session(
        self, user_id: int, headers: Mapping[str, str], remote_host: str | None
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        campaigns = await self._campaigns.list_for_user(user_id)
        initial_chat_id = campaigns[0].chat_id if campaigns else 0
        session_id = await self._access.create_session(
            AdminIdentity(initial_chat_id, user_id, None)
        )
        return (
            HTTPStatus.SEE_OTHER,
            {
                'Location': '/campaigns',
                'Set-Cookie': self._session_cookie(session_id, headers, remote_host),
            },
            b'',
        )

    def _session_cookie(
        self, session_id: str, headers: Mapping[str, str], remote_host: str | None
    ) -> str:
        cookie = f'd20_admin={session_id}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'
        secure_mode = getenv('D20_BOT_WEB_SECURE_COOKIE', 'auto').lower()
        forwarded_protocol = (
            headers.get('x-forwarded-proto', 'http').split(',', 1)[0].strip().lower()
            if self._trusted_proxy(remote_host)
            else 'http'
        )
        if secure_mode == 'true' or (secure_mode == 'auto' and forwarded_protocol == 'https'):
            cookie += '; Secure'
        return cookie

    async def _registration_api(
        self, headers: Mapping[str, str], form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        if not self._authorized(headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
        if self._identities is None:
            return self._json(HTTPStatus.SERVICE_UNAVAILABLE, {'error': 'auth_disabled'})
        try:
            user_id = int(form['user_id'][0])
        except KeyError, ValueError, IndexError:
            return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_request'})
        limited = await self._rate_limit(
            f'registration-code:{user_id}', limit=5, window=timedelta(minutes=15), json=True
        )
        if limited is not None:
            return limited
        try:
            code = await self._identities.issue_registration_code(user_id)
        except UnknownTelegramUser:
            return self._json(HTTPStatus.NOT_FOUND, {'error': 'unknown_user'})
        return self._json(HTTPStatus.OK, {'code': code})

    async def _admin_link(
        self, headers: Mapping[str, str], form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        if not self._authorized(headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
        try:
            chat_id = int(form['chat_id'][0])
            user_id = int(form['user_id'][0])
            chat_title = form.get('chat_title', [None])[0] or None
        except KeyError, ValueError, IndexError:
            return self._json(HTTPStatus.BAD_REQUEST, {'error': 'invalid_request'})
        if not await self._campaigns.is_master(chat_id, user_id):
            return self._json(HTTPStatus.FORBIDDEN, {'error': 'forbidden'})
        limited = await self._rate_limit(
            f'admin-link:{user_id}', limit=5, window=timedelta(minutes=10), json=True
        )
        if limited is not None:
            return limited
        base_url = await self._sessions.get_web_base_url(chat_id) or self._web_base_url
        if not base_url:
            return self._json(HTTPStatus.CONFLICT, {'error': 'web_url_not_configured'})
        token = await self._access.create_login(AdminIdentity(chat_id, user_id, chat_title))
        return self._json(
            HTTPStatus.OK,
            {'url': f'{base_url.rstrip("/")}/login?token={token}'},
        )

    async def _game_api(
        self, headers: Mapping[str, str], form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        if not self._authorized(headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
        action = form.get('action', [''])[0]
        try:
            if action == 'get':
                session = await self._sessions.get_planned(int(form['chat_id'][0]))
                timezone_name = await self._sessions.get_announcement_timezone(
                    int(form['chat_id'][0])
                )
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

    async def _game_url_api(
        self, headers: Mapping[str, str], form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        if not self._authorized(headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
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

    async def _session_api(
        self, headers: Mapping[str, str], form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        if not self._authorized(headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
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

    async def _role_api(
        self, headers: Mapping[str, str], form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        if not self._authorized(headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
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

    async def _web_url_api(
        self, headers: Mapping[str, str], form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        if not self._authorized(headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
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

    async def _events_api(
        self, headers: Mapping[str, str], form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        if not self._authorized(headers):
            return self._json(HTTPStatus.UNAUTHORIZED, {'error': 'unauthorized'})
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

    def _authorized(self, headers: Mapping[str, str]) -> bool:
        authorization = headers.get('authorization', '')
        supplied_token = (
            authorization.removeprefix('Bearer ') if authorization.startswith('Bearer ') else ''
        )
        return bool(self._internal_token) and secrets.compare_digest(
            supplied_token, self._internal_token
        )

    def _client_ip(self, headers: Mapping[str, str], remote_host: str | None) -> str:
        candidate = remote_host or 'unknown'
        if self._trusted_proxy(remote_host):
            candidate = headers.get('x-forwarded-for', '').split(',', 1)[0].strip() or candidate
        try:
            return str(ip_address(candidate))
        except ValueError:
            return remote_host or 'unknown'

    async def _rate_limit(
        self,
        key: str,
        *,
        limit: int,
        window: timedelta,
        json: bool = False,
    ) -> tuple[HTTPStatus, dict[str, str], bytes] | None:
        if self._rate_limiter is None:
            return None
        result = await self._rate_limiter.hit(key, limit=limit, window=window)
        if result.allowed:
            return None
        retry_header = {'Retry-After': str(result.retry_after)}
        if json:
            status, headers, body = self._json(
                HTTPStatus.TOO_MANY_REQUESTS,
                {'error': 'rate_limited', 'retry_after': result.retry_after},
            )
            return status, {**headers, **retry_header}, body
        status, headers, body = page_response(
            HTTPStatus.TOO_MANY_REQUESTS,
            'Слишком много попыток. Повторите запрос позже.',
        )
        return status, {**headers, **retry_header}, body

    async def _dashboard(
        self, identity: AdminIdentity, session_id: str, role: str = 'master'
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        session = await self._sessions.get_planned(identity.chat_id)
        active = await self._sessions.get_active(identity.chat_id)
        history = await self._sessions.get_history(identity.chat_id)
        roster = await self._campaigns.get_roster(identity.chat_id)
        default_url = await self._sessions.get_default_url(identity.chat_id) or getenv(
            'D20_BOT_FOUNDRY_URL', ''
        )
        timezone_name = await self._sessions.get_announcement_timezone(identity.chat_id)
        return dashboard_response(
            identity,
            session,
            active,
            roster,
            default_url,
            history,
            timezone_name,
            await self._access.csrf_token(session_id) or '',
            role,
        )

    async def _schedule(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        try:
            local = datetime.fromisoformat(form['scheduled_at'][0])
            if local.tzinfo is None:
                raise ValueError
            scheduled_at = local.astimezone(UTC)
            foundry_url = form['foundry_url'][0]
        except KeyError, ValueError, IndexError:
            return page_response(HTTPStatus.BAD_REQUEST, 'Неверные дата или URL.')
        if not valid_url(foundry_url):
            return page_response(HTTPStatus.BAD_REQUEST, 'Неверный Foundry URL.')
        result = await self._sessions.schedule(
            identity.chat_id, identity.chat_title, scheduled_at, foundry_url
        )
        await self._outbox.publish(
            'game_scheduled',
            {
                'chat_id': identity.chat_id,
                'session_id': result.session.id,
                'message': game_message(
                    result.session,
                    await self._sessions.get_announcement_timezone(identity.chat_id),
                ),
                'previous_message_id': result.previous_message_id,
            },
        )
        return HTTPStatus.SEE_OTHER, {'Location': f'/?campaign={identity.chat_id}'}, b''

    async def _settings(
        self, identity: AdminIdentity, session_id: str
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        roster = await self._campaigns.get_roster(identity.chat_id)
        title = (
            roster.campaign.title if roster and roster.campaign.title else identity.chat_title or ''
        )
        default_url = await self._sessions.get_default_url(identity.chat_id) or getenv(
            'D20_BOT_FOUNDRY_URL', ''
        )
        timezone_name = await self._sessions.get_announcement_timezone(identity.chat_id)
        return settings_response(
            title,
            default_url,
            timezone_name,
            await self._access.csrf_token(session_id) or '',
            identity.chat_id,
        )

    async def _save_settings(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        try:
            title = form['title'][0].strip()
            foundry_url = form['foundry_url'][0].strip()
            timezone_name = form['announcement_timezone'][0]
        except KeyError, IndexError, ValueError:
            return page_response(HTTPStatus.BAD_REQUEST, 'Некорректные настройки кампании.')
        if (
            not title
            or len(title) > 100
            or not valid_url(foundry_url)
            or timezone_name not in ANNOUNCEMENT_TIMEZONES
        ):
            return page_response(HTTPStatus.BAD_REQUEST, 'Проверьте название и Foundry URL.')
        now = datetime.now(UTC)
        await self._campaigns.set_title(identity.chat_id, title)
        await self._sessions.set_default_url(identity.chat_id, foundry_url, now)
        await self._sessions.set_announcement_timezone(identity.chat_id, timezone_name, now)
        return (
            HTTPStatus.SEE_OTHER,
            {'Location': f'/settings?campaign={identity.chat_id}'},
            b'',
        )

    async def _start_session(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        title = form.get('title', [''])[0].strip() or None
        if title is not None and len(title) > 100:
            return page_response(HTTPStatus.BAD_REQUEST, 'Название слишком длинное.')
        result = await self._sessions.start(identity.chat_id, identity.user_id, title)
        if result.status is SessionStartStatus.FORBIDDEN:
            return page_response(HTTPStatus.FORBIDDEN, 'Доступ к кампании отозван.')
        if result.status is SessionStartStatus.ALREADY_ACTIVE:
            return page_response(HTTPStatus.CONFLICT, 'Сессия уже активна.')
        session = result.session
        assert session is not None
        await self._outbox.publish(
            'session_started',
            {
                'chat_id': identity.chat_id,
                'number': session.number,
                'title': session.title,
                'announcement_message_id': result.announcement_message_id,
            },
        )
        return HTTPStatus.SEE_OTHER, {'Location': f'/?campaign={identity.chat_id}'}, b''

    async def _stop_session(
        self, identity: AdminIdentity
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        result = await self._sessions.stop(identity.chat_id, identity.user_id)
        if result.status is SessionStopStatus.FORBIDDEN:
            return page_response(HTTPStatus.FORBIDDEN, 'Доступ к кампании отозван.')
        if result.status is SessionStopStatus.NO_ACTIVE_SESSION:
            return page_response(HTTPStatus.CONFLICT, 'Активной сессии нет.')
        session = result.session
        assert session is not None
        await self._outbox.publish(
            'session_stopped',
            {'chat_id': identity.chat_id, 'number': session.number},
        )
        return HTTPStatus.SEE_OTHER, {'Location': f'/?campaign={identity.chat_id}'}, b''

    async def _rename_player(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        try:
            user_id = int(form['user_id'][0])
            name = form['name'][0].strip()
        except KeyError, ValueError, IndexError:
            return page_response(HTTPStatus.BAD_REQUEST, 'Некорректные данные игрока.')
        if not name or len(name) > 64:
            return page_response(
                HTTPStatus.BAD_REQUEST, 'Имя должно содержать от 1 до 64 символов.'
            )
        if await self._campaigns.rename_player(identity.chat_id, user_id, name) is None:
            return page_response(HTTPStatus.NOT_FOUND, 'Игрок не найден в этой кампании.')
        return HTTPStatus.SEE_OTHER, {'Location': f'/?campaign={identity.chat_id}'}, b''

    async def _invite_player(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        try:
            user_id = int(form['user_id'][0])
            name = form['name'][0].strip()
        except KeyError, ValueError, IndexError:
            return page_response(HTTPStatus.BAD_REQUEST, 'Некорректные данные игрока.')
        if user_id <= 0 or not name or len(name) > 64:
            return page_response(
                HTTPStatus.BAD_REQUEST,
                'Укажите положительный Telegram ID и имя от 1 до 64 символов.',
            )
        if user_id == identity.user_id:
            return page_response(
                HTTPStatus.CONFLICT,
                'Нельзя пригласить самого себя как игрока.',
            )
        if await self._campaigns.get_role(identity.chat_id, user_id) is not None:
            return page_response(HTTPStatus.CONFLICT, 'Пользователь уже состоит в кампании.')
        await self._outbox.publish(
            'player_invited',
            {
                'chat_id': identity.chat_id,
                'requester_user_id': identity.user_id,
                'target_user_id': user_id,
                'character_name': name,
            },
        )
        return HTTPStatus.SEE_OTHER, {'Location': f'/?campaign={identity.chat_id}'}, b''

    async def _remove_player(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        try:
            user_id = int(form['user_id'][0])
        except KeyError, ValueError, IndexError:
            return page_response(HTTPStatus.BAD_REQUEST, 'Некорректные данные игрока.')
        if not await self._campaigns.remove_player(identity.chat_id, user_id):
            return page_response(HTTPStatus.NOT_FOUND, 'Игрок не найден в этой кампании.')
        return HTTPStatus.SEE_OTHER, {'Location': f'/?campaign={identity.chat_id}'}, b''

    async def _transfer_master(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        try:
            user_id = int(form['user_id'][0])
        except KeyError, ValueError, IndexError:
            return page_response(HTTPStatus.BAD_REQUEST, 'Некорректный новый мастер.')
        if not await self._campaigns.transfer_master(identity.chat_id, identity.user_id, user_id):
            return page_response(
                HTTPStatus.CONFLICT,
                'Передать роль можно только зарегистрированному игроку этой кампании.',
            )
        return HTTPStatus.SEE_OTHER, {'Location': f'/?campaign={identity.chat_id}'}, b''

    @staticmethod
    def _trusted_proxy(remote_host: str | None) -> bool:
        if remote_host is None:
            return False
        try:
            address = ip_address(remote_host)
        except ValueError:
            return False
        for value in getenv('D20_BOT_WEB_TRUSTED_PROXIES', '').split(','):
            value = value.strip()
            if not value:
                continue
            try:
                if address in ip_network(value, strict=False):
                    return True
            except ValueError:
                logging.warning(
                    'Invalid trusted proxy network', extra={'trusted_proxy_network': value}
                )
        return False

    @staticmethod
    def _cookie(headers: Mapping[str, str], name: str) -> str | None:
        cookies = headers.get('cookie', '').split(';')
        for cookie in cookies:
            key, separator, value = cookie.strip().partition('=')
            if separator and key == name:
                return value
        return None

    @staticmethod
    def _json(
        status: HTTPStatus, payload: Mapping[str, object]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        content = json.dumps(payload, ensure_ascii=False).encode()
        return status, {'Content-Type': 'application/json; charset=utf-8'}, content
