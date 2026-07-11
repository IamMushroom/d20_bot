import asyncio
from pathlib import Path
from unittest.mock import Mock

import pytest

import healthcheck


def test_mark_ready_creates_marker(tmp_path):
    marker = tmp_path / 'ready'

    healthcheck.mark_ready(str(marker))

    assert marker.is_file()
    assert healthcheck.is_ready(str(marker)) is True


def test_is_ready_rejects_missing_marker(tmp_path):
    assert healthcheck.is_ready(str(tmp_path / 'missing')) is False


def test_is_ready_rejects_stale_marker(monkeypatch, tmp_path):
    marker = tmp_path / 'ready'
    marker.touch()
    monkeypatch.setattr(healthcheck, 'time', lambda: marker.stat().st_mtime + 31)

    assert healthcheck.is_ready(str(marker), max_age=30) is False


def test_heartbeat_refreshes_marker(monkeypatch, tmp_path):
    marker = tmp_path / 'ready'
    stop = Mock(side_effect=RuntimeError('stop heartbeat'))
    monkeypatch.setattr(healthcheck.asyncio, 'sleep', stop)

    with pytest.raises(RuntimeError, match='stop heartbeat'):
        asyncio.run(healthcheck.heartbeat(str(marker)))

    assert marker.is_file()
    stop.assert_called_once_with(healthcheck.HEARTBEAT_INTERVAL)


def test_healthcheck_main_uses_configured_marker(monkeypatch, tmp_path):
    marker = tmp_path / 'ready'
    monkeypatch.setenv('HEALTHCHECK_FILE', str(marker))
    monkeypatch.setenv('HEALTHCHECK_MAX_AGE', '60')

    assert healthcheck.main() == 1

    Path(marker).touch()

    assert healthcheck.main() == 0
