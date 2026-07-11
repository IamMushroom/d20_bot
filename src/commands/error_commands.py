import logging

from telegram import Update
from telegram.ext import ContextTypes


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unexpected handler errors and notify the affected chat."""
    error = context.error
    logging.error(
        'Unhandled exception while processing Telegram update',
        exc_info=(type(error), error, error.__traceback__) if error else None,
    )

    if not isinstance(update, Update):
        return
    chat = update.effective_chat
    message = update.effective_message
    if chat is None:
        return

    await context.bot.send_message(
        chat_id=chat.id,
        text='⚠️ Не удалось обработать команду. Попробуй ещё раз.',
        reply_to_message_id=message.id if message else None,
    )
