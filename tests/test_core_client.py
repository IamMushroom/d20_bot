import asyncio
import io
from unittest.mock import Mock
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
        CoreClient('http://core:8190', 'secret')._create_admin_link(-100, 7, None)


def test_core_client_rejects_invalid_response(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=io.StringIO('{}'))
    response.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(client_module, 'urlopen', Mock(return_value=response))
    with pytest.raises(CoreClientError, match='invalid response'):
        CoreClient('http://core:8190', 'secret')._create_admin_link(-100, 7, None)
