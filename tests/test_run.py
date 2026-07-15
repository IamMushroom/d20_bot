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
    monkeypatch.setattr(run, 'getenv', lambda name: 'token' if name == 'TG_TOKEN' else None)

    run.main()

    builder.token.assert_called_once_with('token')
    builder.token.return_value.concurrent_updates.assert_called_once_with(16)
    builder.token.return_value.concurrent_updates.return_value.post_init.assert_called_once_with(
        run.initialize_application
    )
    post_init_builder.post_shutdown.assert_called_once_with(run.shutdown_application)
    expected_handlers = sum(1 + len(command.aliases) for command in commands.COMMANDS)
    assert application.add_handler.call_count == expected_handlers
    application.add_error_handler.assert_called_once_with(commands.handle_error)
    application.run_polling.assert_called_once_with()


def test_main_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(run, 'getenv', lambda _name: None)

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
    database = AsyncMock()
    create_database = AsyncMock(return_value=database)
    apply_migrations = AsyncMock()
    set_bot_commands = AsyncMock()
    application = SimpleNamespace(bot_data={})
    monkeypatch.setattr(run, 'getenv', lambda name, default=None: 'sqlite:///:memory:')
    monkeypatch.setattr(run, 'create_database', create_database)
    monkeypatch.setattr(run, 'apply_migrations', apply_migrations)
    monkeypatch.setattr(run, 'set_bot_commands', set_bot_commands)
    monkeypatch.setattr(run, 'MIGRATIONS_DIRECTORY', tmp_path)

    asyncio.run(run.initialize_application(application))

    create_database.assert_awaited_once_with('sqlite:///:memory:')
    apply_migrations.assert_awaited_once_with(database, tmp_path)
    set_bot_commands.assert_awaited_once_with(application)
    assert application.bot_data[run.DATABASE_KEY] is database

    asyncio.run(run.shutdown_application(application))

    database.close.assert_awaited_once_with()
    assert run.DATABASE_KEY not in application.bot_data


def test_initialize_application_closes_database_after_migration_error(monkeypatch):
    database = AsyncMock()
    monkeypatch.setattr(run, 'create_database', AsyncMock(return_value=database))
    monkeypatch.setattr(run, 'apply_migrations', AsyncMock(side_effect=RuntimeError('broken')))

    with pytest.raises(RuntimeError, match='broken'):
        asyncio.run(run.initialize_application(SimpleNamespace(bot_data={})))

    database.close.assert_awaited_once_with()


def test_initialize_application_uses_absolute_container_database_path(monkeypatch, tmp_path):
    database = AsyncMock()
    create_database = AsyncMock(return_value=database)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr(run, 'create_database', create_database)
    monkeypatch.setattr(run, 'apply_migrations', AsyncMock())
    monkeypatch.setattr(run, 'set_bot_commands', AsyncMock())
    monkeypatch.setattr(run, 'MIGRATIONS_DIRECTORY', tmp_path)

    asyncio.run(run.initialize_application(SimpleNamespace(bot_data={})))

    create_database.assert_awaited_once_with('sqlite:////data/d20.sqlite3')


def test_shutdown_application_without_database():
    asyncio.run(run.shutdown_application(SimpleNamespace(bot_data={})))
