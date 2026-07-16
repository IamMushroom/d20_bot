import asyncio
import io
import logging
from pathlib import Path
from types import SimpleNamespace

import healthcheck


def test_is_healthy_checks_heartbeat_age(tmp_path):
    path = tmp_path / 'heartbeat'

    assert not healthcheck.is_healthy(path, now=100)
    path.touch()
    timestamp = path.stat().st_mtime
    assert healthcheck.is_healthy(path, now=timestamp + 10)
    assert not healthcheck.is_healthy(path, now=timestamp + 21)
    assert not healthcheck.is_healthy(path, now=timestamp - 1)


def test_heartbeat_lifecycle(monkeypatch, tmp_path):
    async def scenario():
        path = tmp_path / 'health' / 'heartbeat'
        application = SimpleNamespace(bot_data={})
        monkeypatch.setattr(healthcheck, 'heartbeat_path', lambda: path)

        healthcheck.start_heartbeat(application)
        await asyncio.sleep(0)
        assert path.exists()
        assert healthcheck.HEARTBEAT_TASK_KEY in application.bot_data

        await healthcheck.stop_heartbeat(application)
        assert application.bot_data == {}
        assert not path.exists()

    asyncio.run(scenario())


def test_stop_heartbeat_without_started_task(monkeypatch, tmp_path):
    path = Path(tmp_path / 'missing')
    monkeypatch.setattr(healthcheck, 'heartbeat_path', lambda: path)

    asyncio.run(healthcheck.stop_heartbeat(SimpleNamespace(bot_data={})))


def test_telegram_readiness_calls_get_me(monkeypatch):
    response = io.BytesIO(b'{"ok": true}')
    response.status = 200

    def urlopen(_url, timeout):
        assert timeout == healthcheck.TELEGRAM_TIMEOUT_SECONDS
        return response

    monkeypatch.setattr(healthcheck.urllib.request, 'urlopen', urlopen)

    assert healthcheck.telegram_is_ready('secret-token')


def test_telegram_readiness_warns_without_exposing_token(monkeypatch, caplog):
    def fail(_url, timeout):
        raise OSError('network unavailable for secret-token')

    monkeypatch.setattr(healthcheck.urllib.request, 'urlopen', fail)
    with caplog.at_level(logging.WARNING):
        assert not healthcheck.telegram_is_ready('secret-token')

    record = caplog.records[-1]
    assert record.message == 'Telegram readiness check failed'
    assert record.health_check == 'telegram_readiness'
    assert record.error_type == 'OSError'
    assert record.error_message == 'network unavailable for [REDACTED]'
    assert 'secret-token' not in caplog.text


def test_readiness_requires_fresh_heartbeat(monkeypatch, caplog):
    monkeypatch.setattr(healthcheck, 'is_healthy', lambda: False)
    monkeypatch.setattr(healthcheck, 'telegram_is_ready', lambda: True)

    with caplog.at_level(logging.WARNING):
        assert not healthcheck.readiness()

    assert 'application heartbeat is stale' in caplog.text
    assert caplog.records[-1].health_check == 'heartbeat'
