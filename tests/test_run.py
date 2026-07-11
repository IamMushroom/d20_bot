from unittest.mock import Mock

import pytest

import commands
import run


def test_main_registers_all_handlers(monkeypatch):
    application = Mock()
    builder = Mock()
    builder.token.return_value.concurrent_updates.return_value.post_init.return_value.build.return_value = application
    application_builder = Mock(return_value=builder)
    monkeypatch.setattr(run, 'ApplicationBuilder', application_builder)
    monkeypatch.setattr(run, 'getenv', lambda name: 'token' if name == 'TG_TOKEN' else None)

    run.main()

    builder.token.assert_called_once_with('token')
    builder.token.return_value.concurrent_updates.assert_called_once_with(16)
    builder.token.return_value.concurrent_updates.return_value.post_init.assert_called_once_with(
        run.set_bot_commands
    )
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
