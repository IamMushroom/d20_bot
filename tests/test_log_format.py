import json
import logging
import sys

import pytest

from log_format import JsonFormatter, configure_logging, log_context


def test_json_formatter_produces_valid_structured_log():
    record = logging.LogRecord(
        name='test',
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='Dice "rolled"',
        args=(),
        exc_info=None,
    )
    record.chat_id = 123
    record.command = 'roll'
    record.argument = '1d20 + "4"'
    record.timer_id = '123:456'
    record.telegram_method = 'setChatMemberTag'
    record.error_type = 'BadRequest'
    record.error_message = 'Chat member is an administrator'
    record.tag = 'Мастер'

    payload = json.loads(JsonFormatter().format(record))

    assert payload['level'] == 'INFO'
    assert payload['logger'] == 'test'
    assert payload['message'] == 'Dice "rolled"'
    assert payload['chat_id'] == 123
    assert payload['command'] == 'roll'
    assert payload['argument'] == '1d20 + "4"'
    assert payload['timer_id'] == '123:456'
    assert payload['telegram_method'] == 'setChatMemberTag'
    assert payload['error_type'] == 'BadRequest'
    assert payload['error_message'] == 'Chat member is an administrator'
    assert payload['tag'] == 'Мастер'
    assert payload['datetime'].endswith('+00:00')


def test_configure_logging_rejects_unknown_format():
    with pytest.raises(ValueError, match='Unsupported log format'):
        configure_logging('xml')


def test_json_formatter_includes_exception_traceback():
    try:
        raise RuntimeError('dice failed')
    except RuntimeError:
        exception_info = sys.exc_info()

    record = logging.LogRecord(
        name='test',
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg='Unexpected error',
        args=(),
        exc_info=exception_info,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert 'RuntimeError: dice failed' in payload['exception']


def test_configure_logging_uses_json_formatter(monkeypatch):
    config = {}
    monkeypatch.setattr(logging, 'basicConfig', lambda **kwargs: config.update(kwargs))

    configure_logging()

    assert config['level'] == logging.INFO
    assert config['force'] is True
    assert len(config['handlers']) == 1
    assert isinstance(config['handlers'][0].formatter, JsonFormatter)


def test_json_formatter_includes_context_fields():
    record = logging.LogRecord('test', logging.INFO, __file__, 1, 'message', (), None)

    with log_context(request_id='request', update_id=10, user_id=20):
        payload = json.loads(JsonFormatter().format(record))

    assert payload['request_id'] == 'request'
    assert payload['update_id'] == 10
    assert payload['user_id'] == 20
