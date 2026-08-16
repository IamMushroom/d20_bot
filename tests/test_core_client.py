import asyncio
import io
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from urllib.error import HTTPError, URLError

import pytest

import core.client as client_module
from core import CoreClient, CoreClientError


def test_core_client_requests_admin_link(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=io.StringIO('{"url":"https://d20.example/login"}'))
    response.__exit__ = Mock(return_value=False)
    urlopen = Mock(return_value=response)
    monkeypatch.setattr(client_module, 'urlopen', urlopen)

    client = CoreClient('http://core:8190/', 'secret')
    result = asyncio.run(client.create_admin_link(-100, 7, 'Campaign'))

    assert result == 'https://d20.example/login'
    request = urlopen.call_args.args[0]
    assert request.full_url == 'http://core:8190/api/admin-link'
    assert request.headers['Authorization'] == 'Bearer secret'
    assert b'chat_id=-100' in request.data


def test_core_client_requests_registration_code(monkeypatch):
    request = AsyncMock(return_value={'code': 'ABCD-EFGH-JKLM'})
    monkeypatch.setattr(CoreClient, '_request', request)
    code = asyncio.run(CoreClient('http://core', 'secret').create_registration_code(7))
    assert code == 'ABCD-EFGH-JKLM'
    request.assert_awaited_once_with('/api/auth/registration', {'user_id': 7})


@pytest.mark.parametrize(
    ('error', 'message'),
    [
        (HTTPError('http://core', 403, 'Forbidden', {}, None), 'HTTP 403'),
        (URLError('offline'), 'unavailable'),
    ],
)
def test_core_client_translates_transport_errors(monkeypatch, error, message):
    monkeypatch.setattr(client_module, 'urlopen', Mock(side_effect=error))
    with pytest.raises(CoreClientError, match=message):
        CoreClient('http://core:8190', 'secret')._request_sync('/api/admin-link', {})


def test_core_client_rejects_invalid_response(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=io.StringIO('{}'))
    response.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(client_module, 'urlopen', Mock(return_value=response))
    with pytest.raises(CoreClientError, match='invalid response'):
        asyncio.run(CoreClient('http://core:8190', 'secret').create_admin_link(-100, 7, None))


def test_core_client_supports_get_and_reads_structured_error_code(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=io.StringIO('{"events":[]}'))
    response.__exit__ = Mock(return_value=False)
    urlopen = Mock(return_value=response)
    monkeypatch.setattr(client_module, 'urlopen', urlopen)
    client = CoreClient('http://core:8190', 'secret')

    assert client._request_sync('/internal/events', {}, method='GET') == {'events': []}
    request = urlopen.call_args.args[0]
    assert request.method == 'GET'
    assert request.data is None

    error_body = io.BytesIO(b'{"error":{"code":"unauthorized","message":"Token required"}}')
    monkeypatch.setattr(
        client_module,
        'urlopen',
        Mock(side_effect=HTTPError('http://core', 401, 'Unauthorized', {}, error_body)),
    )
    with pytest.raises(CoreClientError) as raised:
        client._request_sync('/internal/events', {}, method='GET')
    assert raised.value.code == 'unauthorized'


def test_core_client_game_api(monkeypatch):
    request = AsyncMock(
        side_effect=[
            {'message': 'next game'},
            {'session_id': 3, 'message': 'scheduled', 'previous_message_id': 2},
            {'ok': True},
            {'url': 'https://foundry.example'},
            {'ok': True},
            {'status': 'started', 'number': 4, 'title': 'Tower', 'announcement_message_id': 9},
            {'status': 'stopped', 'number': 4},
            {'ok': True},
            {'status': 'registered', 'name': 'Tilly'},
            {'url': 'https://d20.example'},
            {'ok': True},
        ]
    )
    monkeypatch.setattr(CoreClient, '_request', request)

    async def scenario():
        client = CoreClient('http://core:8190', 'secret')
        shown = await client.get_game(-100)
        scheduled = await client.schedule_game(
            -100, 'Campaign', datetime(2026, 7, 20, tzinfo=UTC), None
        )
        await client.set_game_announcement(3, 10)
        url = await client.get_game_url(-100)
        await client.set_game_url(-100, 'https://foundry.example')
        started = await client.start_session(-100, 7, 'Tower')
        stopped = await client.stop_session(-100, 7)
        await client.assign_master(-100, 7, 'Campaign')
        player = await client.register_player(-100, 8, 'Tilly', 'Campaign')
        web_url = await client.get_web_url(-100)
        await client.set_web_url(-100, 'https://d20.example')
        return client, shown, scheduled, url, started, stopped, player, web_url

    client, shown, scheduled, url, started, stopped, player, web_url = asyncio.run(scenario())
    assert shown == 'next game'
    assert scheduled.session_id == 3
    assert scheduled.previous_message_id == 2
    assert url == 'https://foundry.example'
    assert started.status == 'started' and started.number == 4
    assert stopped.status == 'stopped' and stopped.number == 4
    assert player.name == 'Tilly'
    assert web_url == 'https://d20.example'
    assert request.await_count == 11
    assert request.await_args_list[0].args[0] == '/internal/campaigns/-100/game'
    assert request.await_args_list[0].kwargs == {'method': 'GET'}
    assert request.await_args_list[1].args[0] == '/internal/campaigns/-100/game'
    assert request.await_args_list[1].kwargs == {'method': 'PUT'}
    assert request.await_args_list[2].args[0] == '/internal/sessions/3/announcement'
    assert request.await_args_list[5].args[0] == '/internal/campaigns/-100/sessions/start'
    assert request.await_args_list[6].args[0] == '/internal/campaigns/-100/sessions/stop'


def test_core_client_rejects_invalid_game_payloads(monkeypatch):
    monkeypatch.setattr(
        CoreClient, '_request', AsyncMock(side_effect=[{'session_id': 'bad'}, {'url': 42}])
    )

    async def scenario():
        client = CoreClient('http://core:8190', 'secret')
        with pytest.raises(CoreClientError):
            await client.schedule_game(-1, None, datetime.now(UTC), None)
        with pytest.raises(CoreClientError):
            await client.get_game_url(-1)

    asyncio.run(scenario())


def test_core_client_rejects_invalid_session_payload(monkeypatch):
    monkeypatch.setattr(
        CoreClient, '_request', AsyncMock(side_effect=[{'status': 42}, {'status': 'unknown'}])
    )
    client = CoreClient('http://core', 'secret')
    with pytest.raises(CoreClientError):
        asyncio.run(client.stop_session(-1, 1))
    with pytest.raises(CoreClientError):
        asyncio.run(client.start_session(-1, 1, None))


def test_core_client_rejects_invalid_player_payload(monkeypatch):
    monkeypatch.setattr(CoreClient, '_request', AsyncMock(return_value={'status': 'unknown'}))
    with pytest.raises(CoreClientError):
        asyncio.run(CoreClient('http://core', 'secret').register_player(-1, 1, 'T', None))
