from telegram import Update
from telegram.ext import ContextTypes


async def core_required(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explain why a known platform command is unavailable in standalone mode."""
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return
    await context.bot.send_message(
        chat_id=chat.id,
        text=(
            'ℹ️ Эта команда доступна только при подключении к Core. '
            'Запустите Core и установите D20_BOT_MODE=connected.'
        ),
        reply_to_message_id=message.id,
    )
