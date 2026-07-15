import asyncio
import html
import json
import logging
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from http import HTTPStatus
from os import getenv
from urllib.parse import parse_qs, urlsplit

from commands.game_utils import game_message, game_timezone, valid_url
from services import (
    CampaignService,
    OutboxService,
    PlayerRegistrationStatus,
    SessionService,
    SessionStartStatus,
    SessionStopStatus,
)
from web.access import AdminAccessService, AdminIdentity

MAX_REQUEST_SIZE = 16 * 1024


class AdminWebServer:
    def __init__(
        self,
        access: AdminAccessService,
        campaigns: CampaignService,
        sessions: SessionService,
        outbox: OutboxService,
        internal_token: str = '',
        web_base_url: str = '',
    ) -> None:
        self._access = access
        self._campaigns = campaigns
        self._sessions = sessions
        self._outbox = outbox
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
            status, response_headers, content = await self._route(method, target, headers, body)
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
            'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'",
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
        self, method: str, target: str, headers: Mapping[str, str], body: bytes
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        url = urlsplit(target)
        if method == 'POST' and url.path == '/api/admin-link':
            return await self._admin_link(headers, parse_qs(body.decode()))
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
        if method == 'GET' and url.path == '/login':
            token = parse_qs(url.query).get('token', [''])[0]
            session_id = self._access.consume_login(token)
            if session_id is None:
                return self._page(
                    HTTPStatus.UNAUTHORIZED, 'Ссылка недействительна или уже использована.'
                )
            cookie = f'd20_admin={session_id}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'
            secure_mode = getenv('WEB_SECURE_COOKIE', 'auto').lower()
            forwarded_protocol = headers.get('x-forwarded-proto', 'http').split(',', 1)[0].strip()
            if secure_mode == 'true' or (secure_mode == 'auto' and forwarded_protocol == 'https'):
                cookie += '; Secure'
            return HTTPStatus.SEE_OTHER, {'Location': '/', 'Set-Cookie': cookie}, b''

        identity = self._access.authenticate(self._cookie(headers, 'd20_admin'))
        if identity is None:
            return self._page(HTTPStatus.UNAUTHORIZED, 'Запросите новую ссылку командой /admin.')
        if method == 'GET' and url.path == '/':
            return await self._dashboard(identity)
        if method == 'POST' and url.path == '/schedule':
            return await self._schedule(identity, parse_qs(body.decode()))
        if method == 'POST' and url.path == '/session/start':
            return await self._start_session(identity, parse_qs(body.decode()))
        if method == 'POST' and url.path == '/session/stop':
            return await self._stop_session(identity)
        return self._page(HTTPStatus.NOT_FOUND, 'Страница не найдена.')

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
        base_url = await self._sessions.get_web_base_url(chat_id) or self._web_base_url
        if not base_url:
            return self._json(HTTPStatus.CONFLICT, {'error': 'web_url_not_configured'})
        token = self._access.create_login(AdminIdentity(chat_id, user_id, chat_title))
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
                message = (
                    game_message(session) if session else '📅 Следующая игра пока не назначена.'
                )
                return self._json(HTTPStatus.OK, {'message': message})
            if action == 'schedule':
                chat_id = int(form['chat_id'][0])
                scheduled_at = datetime.fromisoformat(form['scheduled_at'][0])
                chat_title = form.get('chat_title', [''])[0] or None
                foundry_url = form.get('foundry_url', [''])[0]
                if not foundry_url:
                    foundry_url = await self._sessions.get_default_url(chat_id) or getenv(
                        'FOUNDRY_URL', ''
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
                        'message': game_message(result.session),
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
                url = await self._sessions.get_default_url(chat_id) or getenv('FOUNDRY_URL', '')
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

    async def _dashboard(self, identity: AdminIdentity) -> tuple[HTTPStatus, dict[str, str], bytes]:
        session = await self._sessions.get_planned(identity.chat_id)
        active = await self._sessions.get_active(identity.chat_id)
        roster = await self._campaigns.get_roster(identity.chat_id)
        current = (
            html.escape(game_message(session)).replace('\n', '<br>')
            if session
            else 'Игра не назначена.'
        )
        default_url = await self._sessions.get_default_url(identity.chat_id) or getenv(
            'FOUNDRY_URL', ''
        )
        title = html.escape(identity.chat_title or str(identity.chat_id))
        if roster is None:
            roster_html = '<p>Состав кампании не найден.</p>'
        else:
            players = ''.join(
                f'<li>{html.escape(character.name)}</li>' for character in roster.characters
            )
            roster_html = (
                f'<h2>Состав</h2><p>Мастер: Telegram ID '
                f'{roster.campaign.master_user_id or "не назначен"}</p>'
                f'<ul>{players or "<li>Игроки не зарегистрированы</li>"}</ul>'
            )
        if active is None:
            lifecycle = """
            <form method="post" action="/session/start">
              <label>Название сессии <input name="title" maxlength="100"></label>
              <button type="submit">▶️ Начать сессию</button>
            </form>"""
        else:
            active_title = f' — {html.escape(active.title)}' if active.title else ''
            lifecycle = f"""<p>▶️ Активная сессия №{active.number}{active_title}</p>
            <form method="post" action="/session/stop">
              <button type="submit">⏹️ Завершить сессию</button>
            </form>"""
        content = f'''
        <h1>{title}</h1>{roster_html}<p>{current}</p>{lifecycle}
        <form method="post" action="/schedule">
          <label>Дата и время <input required type="datetime-local" name="scheduled_at"></label>
          <label>Foundry URL <input required type="url" name="foundry_url" value="{html.escape(default_url)}"></label>
          <button type="submit">Сохранить и опубликовать</button>
        </form>'''
        return self._page(HTTPStatus.OK, content, raw=True)

    async def _schedule(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        try:
            local = datetime.fromisoformat(form['scheduled_at'][0])
            scheduled_at = local.replace(tzinfo=game_timezone()).astimezone(UTC)
            foundry_url = form['foundry_url'][0]
        except KeyError, ValueError, IndexError:
            return self._page(HTTPStatus.BAD_REQUEST, 'Неверные дата или URL.')
        if not valid_url(foundry_url):
            return self._page(HTTPStatus.BAD_REQUEST, 'Неверный Foundry URL.')
        result = await self._sessions.schedule(
            identity.chat_id, identity.chat_title, scheduled_at, foundry_url
        )
        await self._outbox.publish(
            'game_scheduled',
            {
                'chat_id': identity.chat_id,
                'session_id': result.session.id,
                'message': game_message(result.session),
                'previous_message_id': result.previous_message_id,
            },
        )
        return HTTPStatus.SEE_OTHER, {'Location': '/'}, b''

    async def _start_session(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        title = form.get('title', [''])[0].strip() or None
        if title is not None and len(title) > 100:
            return self._page(HTTPStatus.BAD_REQUEST, 'Название слишком длинное.')
        result = await self._sessions.start(identity.chat_id, identity.user_id, title)
        if result.status is SessionStartStatus.FORBIDDEN:
            return self._page(HTTPStatus.FORBIDDEN, 'Доступ к кампании отозван.')
        if result.status is SessionStartStatus.ALREADY_ACTIVE:
            return self._page(HTTPStatus.CONFLICT, 'Сессия уже активна.')
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
        return HTTPStatus.SEE_OTHER, {'Location': '/'}, b''

    async def _stop_session(
        self, identity: AdminIdentity
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        result = await self._sessions.stop(identity.chat_id, identity.user_id)
        if result.status is SessionStopStatus.FORBIDDEN:
            return self._page(HTTPStatus.FORBIDDEN, 'Доступ к кампании отозван.')
        if result.status is SessionStopStatus.NO_ACTIVE_SESSION:
            return self._page(HTTPStatus.CONFLICT, 'Активной сессии нет.')
        session = result.session
        assert session is not None
        await self._outbox.publish(
            'session_stopped',
            {'chat_id': identity.chat_id, 'number': session.number},
        )
        return HTTPStatus.SEE_OTHER, {'Location': '/'}, b''

    @staticmethod
    def _cookie(headers: Mapping[str, str], name: str) -> str | None:
        cookies = headers.get('cookie', '').split(';')
        for cookie in cookies:
            key, separator, value = cookie.strip().partition('=')
            if separator and key == name:
                return value
        return None

    @staticmethod
    def _page(
        status: HTTPStatus, content: str, *, raw: bool = False
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        body = content if raw else html.escape(content)
        document = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>D20 Admin</title><style>body{{font:16px system-ui;max-width:42rem;margin:3rem auto;padding:0 1rem;background:#17151c;color:#eee}}label,input,button{{display:block;width:100%;box-sizing:border-box;margin:.8rem 0}}input,button{{padding:.7rem}}button{{cursor:pointer}}</style><main>{body}</main></html>"""
        return status, {}, document.encode()

    @staticmethod
    def _json(
        status: HTTPStatus, payload: Mapping[str, object]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        content = json.dumps(payload, ensure_ascii=False).encode()
        return status, {'Content-Type': 'application/json; charset=utf-8'}, content
