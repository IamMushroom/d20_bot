import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import commands
import run


def test_main_registers_all_handlers(monkeypatch):
    application = Mock()
    builder = Mock()
    post_init_builder = (
        builder.token.return_value.concurrent_updates.return_value.post_init.return_value
    )
    post_init_builder.post_shutdown.return_value.build.return_value = application
    application_builder = Mock(return_value=builder)
    monkeypatch.setattr(run, 'ApplicationBuilder', application_builder)
    monkeypatch.setattr(
        run, 'getenv', lambda name, default='': 'token' if name == 'TG_TOKEN' else default
    )
    monkeypatch.setattr(run, 'runtime_mode', lambda: 'standalone')

    run.main()

    builder.token.assert_called_once_with('token')
    builder.token.return_value.concurrent_updates.assert_called_once_with(16)
    builder.token.return_value.concurrent_updates.return_value.post_init.assert_called_once_with(
        run.initialize_application
    )
    post_init_builder.post_shutdown.assert_called_once_with(run.shutdown_application)
    expected_handlers = sum(
        1 + len(command.aliases) for command in commands.commands_for(platform_enabled=False)
    )
    assert application.add_handler.call_count == expected_handlers
    application.add_error_handler.assert_called_once_with(commands.handle_error)
    application.run_polling.assert_called_once_with()


def test_main_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(run, 'getenv', lambda _name, default='': default)

    with pytest.raises(RuntimeError, match='TG_TOKEN environment variable is not set'):
        run.main()


def test_bootstrap_configures_environment_and_starts_bot(monkeypatch):
    load_dotenv = Mock()
    configure_logging = Mock()
    main = Mock()
    loggers = {
        'httpx': Mock(),
        'telegram.ext.Application': Mock(),
    }
    original_get_logger = run.logging.getLogger

    def get_logger(name=None):
        return loggers.get(name, original_get_logger(name))

    monkeypatch.setattr(run, 'load_dotenv', load_dotenv)
    monkeypatch.setattr(
        run, 'getenv', lambda name, default=None: 'json' if name == 'LOG_FORMAT' else default
    )
    monkeypatch.setattr(run.log_format, 'configure_logging', configure_logging)
    monkeypatch.setattr(run.logging, 'getLogger', get_logger)
    monkeypatch.setattr(run, 'main', main)

    run.bootstrap()

    load_dotenv.assert_called_once_with()
    configure_logging.assert_called_once_with('json')
    loggers['httpx'].setLevel.assert_called_once_with(run.logging.WARNING)
    loggers['telegram.ext.Application'].setLevel.assert_called_once_with(run.logging.WARNING)
    main.assert_called_once_with()


def test_initialize_and_shutdown_application(monkeypatch, tmp_path):
    runtime = SimpleNamespace(
        database=object(),
        campaigns=object(),
        sessions=object(),
        access=object(),
        web_base_url='https://d20.example',
        web_server=object(),
        close=AsyncMock(),
    )
    start_core = AsyncMock(return_value=runtime)
    set_bot_commands = AsyncMock()
    application = SimpleNamespace(bot_data={}, bot=AsyncMock())
    values = {
        'DATABASE_URL': 'sqlite:///:memory:',
        'WEB_BASE_URL': 'https://d20.example',
        'WEB_HOST': '127.0.0.1',
        'WEB_PORT': '9000',
    }
    monkeypatch.setattr(run, 'getenv', lambda name, default=None: values.get(name, default))
    monkeypatch.setattr(run.CoreRuntime, 'start', start_core)
    monkeypatch.setattr(run, 'set_bot_commands', set_bot_commands)
    monkeypatch.setattr(run, 'MIGRATIONS_DIRECTORY', tmp_path)
    monkeypatch.setattr(run, 'runtime_mode', lambda: 'full')

    asyncio.run(run.initialize_application(application))

    start_core.assert_awaited_once_with(
        database_url='sqlite:///:memory:',
        migrations_directory=tmp_path,
        web_host='127.0.0.1',
        web_port=9000,
        web_base_url='https://d20.example',
        internal_token='',
        telegram_bot=application.bot,
    )
    set_bot_commands.assert_awaited_once_with(application)
    assert application.bot_data[run.DATABASE_KEY] is runtime.database
    assert application.bot_data[run.CAMPAIGN_SERVICE_KEY] is runtime.campaigns
    assert application.bot_data[run.SESSION_SERVICE_KEY] is runtime.sessions

    asyncio.run(run.shutdown_application(application))

    runtime.close.assert_awaited_once_with()
    assert run.DATABASE_KEY not in application.bot_data
    assert run.CAMPAIGN_SERVICE_KEY not in application.bot_data
    assert run.SESSION_SERVICE_KEY not in application.bot_data


def test_standalone_lifecycle_does_not_open_database(monkeypatch):
    async def scenario():
        application = SimpleNamespace(bot_data={}, bot=AsyncMock())
        start_core = AsyncMock()
        set_bot_commands = AsyncMock()
        monkeypatch.setattr(run, 'runtime_mode', lambda: 'standalone')
        monkeypatch.setattr(run.CoreRuntime, 'start', start_core)
        monkeypatch.setattr(run, 'set_bot_commands', set_bot_commands)

        await run.initialize_application(application)
        enabled_during_run = application.bot_data[run.PLATFORM_ENABLED_KEY]
        await run.shutdown_application(application)
        return application, start_core, set_bot_commands, enabled_during_run

    application, start_core, set_bot_commands, enabled = asyncio.run(scenario())
    assert not enabled
    start_core.assert_not_awaited()
    set_bot_commands.assert_awaited_once()
    assert application.bot_data == {}


def test_connected_lifecycle_creates_core_client_without_database(monkeypatch):
    application = SimpleNamespace(bot_data={}, bot=AsyncMock())
    client = object()
    start_core = AsyncMock()
    set_bot_commands = AsyncMock()
    monkeypatch.setattr(run, 'runtime_mode', lambda: 'connected')
    monkeypatch.setattr(
        run,
        'required_environment',
        lambda name: {'CORE_URL': 'http://core:8190', 'CORE_TOKEN': 'secret'}[name],
    )
    monkeypatch.setattr(run, 'CoreClient', Mock(return_value=client))
    monkeypatch.setattr(run.CoreRuntime, 'start', start_core)
    monkeypatch.setattr(run, 'set_bot_commands', set_bot_commands)

    asyncio.run(run.initialize_application(application))

    run.CoreClient.assert_called_once_with('http://core:8190', 'secret')
    assert application.bot_data[run.CORE_CLIENT_KEY] is client
    assert application.bot_data[run.CORE_CONNECTED_KEY]
    start_core.assert_not_awaited()
    asyncio.run(run.shutdown_application(application))
    assert application.bot_data == {}


def test_platform_mode_defaults_to_standalone_and_validates(monkeypatch):
    monkeypatch.delenv('D20_MODE', raising=False)
    assert run.runtime_mode() == 'standalone'
    assert not run.platform_enabled()
    monkeypatch.setenv('D20_MODE', 'connected')
    assert run.runtime_mode() == 'connected'
    monkeypatch.setenv('D20_MODE', 'full')
    assert run.platform_enabled()
    monkeypatch.setenv('D20_MODE', 'invalid')
    with pytest.raises(ValueError, match='D20_MODE'):
        run.platform_enabled()


def test_initialize_application_clears_state_after_core_error(monkeypatch):
    monkeypatch.setattr(run.CoreRuntime, 'start', AsyncMock(side_effect=RuntimeError('broken')))
    monkeypatch.setattr(run, 'runtime_mode', lambda: 'full')
    application = SimpleNamespace(bot_data={}, bot=AsyncMock())

    with pytest.raises(RuntimeError, match='broken'):
        asyncio.run(run.initialize_application(application))

    assert application.bot_data == {}


def test_shutdown_application_without_database():
    asyncio.run(run.shutdown_application(SimpleNamespace(bot_data={})))
