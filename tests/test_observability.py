import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from commands.observability import observed_callback


def make_update():
    return SimpleNamespace(
        update_id=10,
        effective_user=SimpleNamespace(id=20),
        effective_chat=SimpleNamespace(id=30),
    )


def test_observed_callback_logs_success(caplog):
    callback = AsyncMock()

    with caplog.at_level(logging.INFO):
        asyncio.run(observed_callback('roll', callback)(make_update(), SimpleNamespace()))

    callback.assert_awaited_once()
    assert 'Command started' in caplog.messages
    assert 'Command completed' in caplog.messages


def test_observed_callback_logs_failure(caplog):
    callback = AsyncMock(side_effect=RuntimeError('failed'))

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match='failed'):
        asyncio.run(observed_callback('roll', callback)(make_update(), SimpleNamespace()))

    assert 'Command failed' in caplog.messages
