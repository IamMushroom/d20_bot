from telegram import Update
from telegram.ext import ContextTypes

from app_version import get_version


async def version_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return

    await context.bot.send_message(
        chat_id=chat.id,
        text=f'🤖 D20 Bot v{get_version()}',
        reply_to_message_id=message.id,
    )
