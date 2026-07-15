from telegram import Update
from telegram.ext import ContextTypes


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show available commands and usage examples."""
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return

    from commands.registry import help_message

    bot_data = getattr(context.application, 'bot_data', {})
    core_connected = bot_data.get('core_connected', False)

    await context.bot.send_message(
        chat_id=chat.id,
        text=help_message(core_connected=core_connected),
        reply_to_message_id=message.id,
    )
