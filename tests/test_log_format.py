import json
import logging

import pytest

from log_format import JsonFormatter, configure_logging


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

    payload = json.loads(JsonFormatter().format(record))

    assert payload['level'] == 'INFO'
    assert payload['logger'] == 'test'
    assert payload['message'] == 'Dice "rolled"'
    assert payload['chat_id'] == 123
    assert payload['command'] == 'roll'
    assert payload['argument'] == '1d20 + "4"'
    assert payload['datetime'].endswith('+00:00')


def test_configure_logging_rejects_unknown_format():
    with pytest.raises(ValueError, match='Unsupported LOG_FORMAT'):
        configure_logging('xml')
