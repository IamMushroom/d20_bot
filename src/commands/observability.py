import logging
from time import perf_counter
from uuid import uuid4

from telegram import Update
from telegram.ext import ContextTypes

from commands.registry import CommandCallback
from log_format import log_context


def observed_callback(command_name: str, callback: CommandCallback) -> CommandCallback:
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        request_id = uuid4().hex
        started = perf_counter()
        fields = {
            'request_id': request_id,
            'update_id': update.update_id,
            'user_id': update.effective_user.id if update.effective_user else None,
            'chat_id': update.effective_chat.id if update.effective_chat else None,
            'command': command_name,
        }
        with log_context(**fields):
            logging.info('Command started')
            try:
                await callback(update, context)
            except Exception:
                logging.exception(
                    'Command failed',
                    extra={
                        'duration_ms': round((perf_counter() - started) * 1000, 2),
                        'status': 'failed',
                    },
                )
                raise
            logging.info(
                'Command completed',
                extra={'duration_ms': round((perf_counter() - started) * 1000, 2), 'status': 'ok'},
            )

    return wrapped
