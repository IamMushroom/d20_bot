import io
from unittest.mock import Mock

import healthcheck


class Response(io.BytesIO):
    def __init__(self, payload: bytes, status: int = 200):
        super().__init__(payload)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_telegram_is_available(monkeypatch):
    urlopen = Mock(return_value=Response(b'{"ok": true}'))
    monkeypatch.setattr(healthcheck, 'urlopen', urlopen)

    assert healthcheck.telegram_is_available('token') is True
    urlopen.assert_called_once_with('https://api.telegram.org/bottoken/getMe', timeout=5)


def test_telegram_healthcheck_rejects_empty_token():
    assert healthcheck.telegram_is_available('') is False


def test_telegram_healthcheck_handles_api_failure(monkeypatch):
    monkeypatch.setattr(healthcheck, 'urlopen', Mock(side_effect=OSError('offline')))

    assert healthcheck.telegram_is_available('token') is False


def test_telegram_healthcheck_rejects_unsuccessful_response(monkeypatch):
    monkeypatch.setattr(healthcheck, 'urlopen', Mock(return_value=Response(b'{"ok": false}')))

    assert healthcheck.telegram_is_available('token') is False


def test_healthcheck_main(monkeypatch):
    monkeypatch.setattr(healthcheck, 'getenv', lambda _name, _default: 'token')
    monkeypatch.setattr(healthcheck, 'telegram_is_available', lambda _token: True)

    assert healthcheck.main() == 0
