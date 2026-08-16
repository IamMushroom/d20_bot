import asyncio
from http import HTTPStatus

import pytest

from web.http import Request, Response, serialize_response
from web.router import Router


def test_request_parses_target_and_keeps_legacy_tuple_compatibility():
    request = Request('POST', '/schedule?campaign=-100', {'x-test': 'yes'}, b'name=one')

    assert request.path == '/schedule'
    assert request.query == {'campaign': ['-100']}
    assert request.form == {'name': ['one']}
    assert tuple(request) == ('POST', '/schedule?campaign=-100', {'x-test': 'yes'}, b'name=one')


def test_response_serialization_adds_security_and_transport_headers():
    raw = serialize_response(
        Response(HTTPStatus.OK, {'Content-Type': 'application/json'}, b'{"ok": true}')
    )

    assert raw.startswith(b'HTTP/1.1 200 OK\r\n')
    assert b'Content-Length: 12\r\n' in raw
    assert b'Content-Type: application/json\r\n' in raw
    assert b'X-Content-Type-Options: nosniff\r\n' in raw


def test_router_dispatches_exact_method_and_path():
    router = Router()

    async def handler(request):
        return HTTPStatus.OK, {}, request.path.encode()

    router.add('GET', '/health', handler)
    result = asyncio.run(router.dispatch(Request('GET', '/health?full=1', {}, b'')))

    assert result == (HTTPStatus.OK, {}, b'/health')
    assert asyncio.run(router.dispatch(Request('POST', '/health', {}, b''))) is None
    assert router.supports_path('/health')


def test_router_rejects_duplicate_routes():
    router = Router()

    async def handler(_request):
        return HTTPStatus.OK, {}, b''

    router.add('GET', '/', handler)
    with pytest.raises(ValueError, match='already registered'):
        router.add('GET', '/', handler)
