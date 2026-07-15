import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import run_core


def test_run_core_starts_and_stops_runtime(monkeypatch, tmp_path):
    async def scenario():
        bot = SimpleNamespace(initialize=AsyncMock(), shutdown=AsyncMock())
        runtime = SimpleNamespace(
            web_server=SimpleNamespace(serve_forever=AsyncMock()), close=AsyncMock()
        )
        values = {
            'TG_TOKEN': 'telegram-token',
            'CORE_TOKEN': 'core-token',
            'DATABASE_URL': 'sqlite:///:memory:',
            'WEB_HOST': '127.0.0.1',
            'WEB_PORT': '9000',
            'WEB_BASE_URL': 'https://d20.example',
        }
        monkeypatch.setattr(run_core, 'getenv', lambda name, default='': values.get(name, default))
        monkeypatch.setattr(run_core, 'Bot', Mock(return_value=bot))
        start = AsyncMock(return_value=runtime)
        monkeypatch.setattr(run_core.CoreRuntime, 'start', start)
        monkeypatch.setattr(run_core, 'MIGRATIONS_DIRECTORY', tmp_path)

        await run_core.run_core()
        return bot, runtime, start

    bot, runtime, start = asyncio.run(scenario())
    bot.initialize.assert_awaited_once()
    start.assert_awaited_once()
    runtime.web_server.serve_forever.assert_awaited_once()
    runtime.close.assert_awaited_once()
    bot.shutdown.assert_awaited_once()


def test_run_core_requires_environment_and_shuts_down_bot(monkeypatch):
    monkeypatch.setattr(run_core, 'getenv', lambda _name, default='': default)
    with pytest.raises(RuntimeError, match='TG_TOKEN'):
        asyncio.run(run_core.run_core())

    bot = SimpleNamespace(initialize=AsyncMock(), shutdown=AsyncMock())
    monkeypatch.setattr(
        run_core,
        'getenv',
        lambda name, default='': 'telegram-token' if name == 'TG_TOKEN' else default,
    )
    monkeypatch.setattr(run_core, 'Bot', Mock(return_value=bot))
    with pytest.raises(RuntimeError, match='CORE_TOKEN'):
        asyncio.run(run_core.run_core())
    bot.shutdown.assert_awaited_once()


def test_core_bootstrap_configures_logging(monkeypatch):
    coroutine = object()
    load_dotenv = Mock()
    configure = Mock()
    run = Mock(return_value=coroutine)
    asyncio_run = Mock()
    monkeypatch.setattr(run_core, 'load_dotenv', load_dotenv)
    monkeypatch.setattr(run_core.log_format, 'configure_logging', configure)
    monkeypatch.setattr(run_core, 'getenv', lambda name, default='': default)
    monkeypatch.setattr(run_core, 'run_core', run)
    monkeypatch.setattr(run_core.asyncio, 'run', asyncio_run)

    run_core.bootstrap()

    load_dotenv.assert_called_once()
    configure.assert_called_once_with('json')
    asyncio_run.assert_called_once_with(coroutine)
