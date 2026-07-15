import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

import run_core


def test_run_core_starts_and_stops_runtime(monkeypatch, tmp_path):
    async def scenario():
        runtime = Mock()
        runtime.web_server.serve_forever = AsyncMock()
        runtime.close = AsyncMock()
        values = {
            'CORE_TOKEN': 'core-token',
            'DATABASE_URL': 'sqlite:///:memory:',
            'WEB_HOST': '127.0.0.1',
            'WEB_PORT': '9000',
            'WEB_BASE_URL': 'https://d20.example',
        }
        monkeypatch.setattr(run_core, 'getenv', lambda name, default='': values.get(name, default))
        start = AsyncMock(return_value=runtime)
        monkeypatch.setattr(run_core.CoreRuntime, 'start', start)
        monkeypatch.setattr(run_core, 'MIGRATIONS_DIRECTORY', tmp_path)

        await run_core.run_core()
        return runtime, start

    runtime, start = asyncio.run(scenario())
    start.assert_awaited_once()
    runtime.web_server.serve_forever.assert_awaited_once()
    runtime.close.assert_awaited_once()


def test_run_core_requires_environment(monkeypatch):
    monkeypatch.setattr(run_core, 'getenv', lambda _name, default='': default)
    with pytest.raises(RuntimeError, match='CORE_TOKEN'):
        asyncio.run(run_core.run_core())


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
