import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

EXTRA_FIELDS = (
    'request_id',
    'update_id',
    'user_id',
    'chat_id',
    'command',
    'argument',
    'timer_id',
    'duration_ms',
    'status',
    'telegram_method',
    'error_type',
    'error_message',
    'tag',
    'backup_path',
    'timezone',
    'web_host',
    'web_port',
    'health_check',
    'core_path',
    'trusted_proxy_network',
)
LOG_CONTEXT: ContextVar[dict | None] = ContextVar('log_context', default=None)


@contextmanager
def log_context(**fields):
    token = LOG_CONTEXT.set({**(LOG_CONTEXT.get() or {}), **fields})
    try:
        yield
    finally:
        LOG_CONTEXT.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = LOG_CONTEXT.get() or {}
        payload = {
            'datetime': datetime.fromtimestamp(record.created, UTC).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        for field in EXTRA_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
            elif field in context:
                payload[field] = context[field]
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(format_name: str = 'json') -> None:
    if format_name != 'json':
        raise ValueError(f'Unsupported log format: {format_name}')

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
