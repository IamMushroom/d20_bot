from telegram import Update
from telegram.ext import ContextTypes


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show available commands and usage examples."""
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return

    from commands.registry import HELP_MESSAGE

    await context.bot.send_message(
        chat_id=chat.id,
        text=HELP_MESSAGE,
        reply_to_message_id=message.id,
    )
