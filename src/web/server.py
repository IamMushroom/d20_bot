import asyncio
import json
import logging
from collections.abc import Mapping
from http import HTTPStatus
from importlib.resources import files

from auth import IdentityProvider, RateLimiter
from database import Database
from services import CampaignService, GameWorkflowService, OutboxService, SessionService
from web.access import AdminAccessService
from web.api import InternalApi
from web.http import Request, Response, ResponseTuple, read_request, serialize_response
from web.middleware import trusted_proxy
from web.pages import PageHandlers
from web.router import Router
from web.views import page_response

APP_JS = files('web').joinpath('static/app.js').read_bytes()

PAGE_ROUTES = (
    ('GET', '/'),
    ('GET', '/campaigns'),
    ('GET', '/login'),
    ('GET', '/register'),
    ('GET', '/sessions'),
    ('GET', '/settings'),
    ('POST', '/login'),
    ('POST', '/logout'),
    ('POST', '/master/transfer'),
    ('POST', '/player/invite'),
    ('POST', '/player/remove'),
    ('POST', '/player/rename'),
    ('POST', '/register'),
    ('POST', '/schedule'),
    ('POST', '/session/start'),
    ('POST', '/session/stop'),
    ('POST', '/sessions/revoke'),
    ('POST', '/settings'),
)


class AdminWebServer:
    def __init__(
        self,
        database: Database,
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
        self._api = InternalApi(
            access,
            campaigns,
            sessions,
            outbox,
            identities,
            rate_limiter,
            internal_token,
            web_base_url,
        )
        self._pages = PageHandlers(
            access,
            campaigns,
            sessions,
            GameWorkflowService(database, sessions, outbox),
            identities,
            rate_limiter,
        )
        self._router = Router()
        self._router.add('GET', '/health', self._health_route)
        self._router.add('GET', '/static/app.js', self._javascript_route)
        self._router.add('POST', '/api/admin-link', self._api.admin_link)
        self._router.add('POST', '/api/auth/registration', self._api.registration)
        self._router.add('POST', '/api/game', self._api.game)
        self._router.add('POST', '/api/game-url', self._api.game_url)
        self._router.add('POST', '/api/session', self._api.session)
        self._router.add('POST', '/api/role', self._api.role)
        self._router.add('POST', '/api/web-url', self._api.web_url)
        self._router.add('POST', '/api/events', self._api.events)
        for method, path in PAGE_ROUTES:
            self._router.add(method, path, self._pages.dispatch)

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
        return await self._pages.dispatch(request)

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
