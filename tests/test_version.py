import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app_version import get_version
from commands import version_commands


def test_get_version_reads_pyproject():
    assert re.fullmatch(r'\d+\.\d+\.\d+', get_version())


def test_version_command_sends_version(monkeypatch):
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_message=SimpleNamespace(id=2),
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

    monkeypatch.setattr(version_commands, 'get_version', lambda: '1.2.3')
    asyncio.run(version_commands.version_command(update, context))

    assert context.bot.send_message.await_args.kwargs['text'] == '🤖 D20 Bot v1.2.3'


def test_version_command_ignores_incomplete_update():
    update = SimpleNamespace(effective_chat=None, effective_message=None)
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

    asyncio.run(version_commands.version_command(update, context))

    context.bot.send_message.assert_not_awaited()
