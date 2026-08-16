import asyncio
import json
import logging
from collections.abc import Mapping
from http import HTTPStatus
from importlib.resources import files

from auth import IdentityProvider, RateLimiter
from services import CampaignService, GameWorkflowService, OutboxService, SessionService
from web.access import AdminAccessService
from web.api import AuthApi, CampaignsApi, EventsApi, GamesApi, LegacyApi, SessionsApi
from web.http import Request, Response, ResponseTuple, read_request, serialize_response
from web.middleware import trusted_proxy
from web.pages import PageHandlers
from web.router import Router
from web.views import page_response

APP_JS = files('web').joinpath('static/app.js').read_bytes()


class AdminWebServer:
    def __init__(
        self,
        workflows: GameWorkflowService,
        access: AdminAccessService,
        campaigns: CampaignService,
        sessions: SessionService,
        outbox: OutboxService,
        identities: IdentityProvider | None = None,
        rate_limiter: RateLimiter | None = None,
        internal_token: str = '',
        web_base_url: str = '',
    ) -> None:
        self._server: asyncio.Server | None = None
        legacy = LegacyApi(
            access,
            campaigns,
            sessions,
            outbox,
            identities,
            rate_limiter,
            internal_token,
            web_base_url,
        )
        auth_api = AuthApi(identities, rate_limiter, internal_token)
        campaigns_api = CampaignsApi(
            access, campaigns, sessions, rate_limiter, internal_token, web_base_url
        )
        events_api = EventsApi(outbox, internal_token)
        games_api = GamesApi(sessions, internal_token)
        sessions_api = SessionsApi(sessions, internal_token)
        self._pages = PageHandlers(
            access,
            campaigns,
            sessions,
            workflows,
            identities,
            rate_limiter,
        )
        self._router = Router()
        self._router.add('GET', '/health', self._health_route)
        self._router.add('GET', '/static/app.js', self._javascript_route)
        self._router.add('POST', '/api/admin-link', legacy.admin_link)
        self._router.add('POST', '/api/auth/registration', legacy.registration)
        self._router.add('POST', '/api/game', legacy.game)
        self._router.add('POST', '/api/game-url', legacy.game_url)
        self._router.add('POST', '/api/session', legacy.session)
        self._router.add('POST', '/api/role', legacy.role)
        self._router.add('POST', '/api/web-url', legacy.web_url)
        self._router.add('POST', '/api/events', legacy.events)
        self._router.add('GET', '/internal/events', events_api.list_events)
        self._router.add('POST', '/internal/events/{event_id}/ack', events_api.acknowledge_event)
        self._router.add('GET', '/internal/campaigns/{chat_id}/game', games_api.get_game)
        self._router.add('PUT', '/internal/campaigns/{chat_id}/game', games_api.schedule_game)
        self._router.add(
            'POST',
            '/internal/sessions/{session_id}/announcement',
            games_api.set_announcement,
        )
        self._router.add(
            'POST',
            '/internal/campaigns/{chat_id}/sessions/start',
            sessions_api.start,
        )
        self._router.add(
            'POST',
            '/internal/campaigns/{chat_id}/sessions/stop',
            sessions_api.stop,
        )
        self._router.add(
            'POST', '/internal/auth/registration-codes', auth_api.create_registration_code
        )
        self._router.add(
            'POST',
            '/internal/campaigns/{chat_id}/admin-links',
            campaigns_api.create_admin_link,
        )
        self._router.add(
            'PUT',
            '/internal/campaigns/{chat_id}/master',
            campaigns_api.assign_master,
        )
        self._router.add(
            'POST',
            '/internal/campaigns/{chat_id}/players',
            campaigns_api.register_player,
        )
        self._router.add(
            'GET',
            '/internal/campaigns/{chat_id}/foundry-url',
            games_api.get_foundry_url,
        )
        self._router.add(
            'PUT',
            '/internal/campaigns/{chat_id}/foundry-url',
            games_api.set_foundry_url,
        )
        self._router.add(
            'GET',
            '/internal/campaigns/{chat_id}/web-url',
            campaigns_api.get_web_url,
        )
        self._router.add(
            'PUT',
            '/internal/campaigns/{chat_id}/web-url',
            campaigns_api.set_web_url,
        )
        page_routes = (
            ('GET', '/', self._pages.dashboard),
            ('GET', '/campaigns', self._pages.campaigns),
            ('GET', '/login', self._pages.login_link),
            ('GET', '/register', self._pages.register_page),
            ('GET', '/sessions', self._pages.sessions),
            ('GET', '/settings', self._pages.settings),
            ('POST', '/login', self._pages.login),
            ('POST', '/logout', self._pages.logout),
            ('POST', '/master/transfer', self._pages.transfer_master),
            ('POST', '/player/invite', self._pages.invite_player),
            ('POST', '/player/remove', self._pages.remove_player),
            ('POST', '/player/rename', self._pages.rename_player),
            ('POST', '/register', self._pages.register),
            ('POST', '/schedule', self._pages.schedule),
            ('POST', '/session/start', self._pages.start_session),
            ('POST', '/session/stop', self._pages.stop_session),
            ('POST', '/sessions/revoke', self._pages.revoke_session),
            ('POST', '/settings', self._pages.save_settings),
        )
        for method, path, handler in page_routes:
            self._router.add(method, path, handler)

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
            peer = writer.get_extra_info('peername')
            remote_host = str(peer[0]) if isinstance(peer, tuple) and peer else None
            request = await read_request(reader, remote_host)
            response = Response.from_tuple(await self._dispatch(request))
        except ValueError, UnicodeError:
            response = Response(HTTPStatus.BAD_REQUEST, body=b'Bad request')
        except Exception:
            logging.exception('Admin web request failed')
            response = Response(HTTPStatus.INTERNAL_SERVER_ERROR, body=b'Error')
        writer.write(serialize_response(response))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def _read_request(self, reader: asyncio.StreamReader) -> Request:
        return await read_request(reader)

    async def _dispatch(self, request: Request) -> ResponseTuple:
        routed = await self._router.dispatch(request)
        if routed is not None:
            return routed
        if self._router.supports_path(request.path):
            return page_response(HTTPStatus.METHOD_NOT_ALLOWED, 'Метод не поддерживается.')
        return page_response(HTTPStatus.NOT_FOUND, 'Страница не найдена.')

    async def _route(
        self,
        method: str,
        target: str,
        headers: Mapping[str, str],
        body: bytes,
        remote_host: str | None = None,
    ) -> ResponseTuple:
        return await self._dispatch(Request(method, target, headers, body, remote_host))

    async def _health_route(self, _request: Request) -> ResponseTuple:
        return self._json(HTTPStatus.OK, {'status': 'ok'})

    async def _javascript_route(self, _request: Request) -> ResponseTuple:
        return (
            HTTPStatus.OK,
            {
                'Content-Type': 'text/javascript; charset=utf-8',
                'Cache-Control': 'public, max-age=3600',
            },
            APP_JS,
        )

    @staticmethod
    def _trusted_proxy(remote_host: str | None) -> bool:
        return trusted_proxy(remote_host)

    @staticmethod
    def _json(status: HTTPStatus, payload: Mapping[str, object]) -> ResponseTuple:
        content = json.dumps(payload, ensure_ascii=False).encode()
        return status, {'Content-Type': 'application/json; charset=utf-8'}, content
