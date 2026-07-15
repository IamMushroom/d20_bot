from datetime import UTC, datetime
from os import getenv

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from commands.game_utils import valid_url
from commands.helpers import is_admin, session_service
from core import CORE_CLIENT_KEY, CoreClient, CoreClientError


async def game_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show or set the default Foundry URL for this chat."""
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return

    core: CoreClient | None = context.application.bot_data.get(CORE_CLIENT_KEY)
    if not context.args:
        try:
            foundry_url = (
                await core.get_game_url(chat.id)
                if core is not None
                else await session_service(context).get_default_url(chat.id)
                or getenv('FOUNDRY_URL', '')
            )
        except CoreClientError:
            foundry_url = None
        text = (
            f'🏰 Адрес Foundry по умолчанию: {foundry_url}'
            if valid_url(foundry_url)
            else '📭 Адрес Foundry по умолчанию пока не задан.'
        )
        await context.bot.send_message(chat_id=chat.id, text=text, reply_to_message_id=message.id)
        return

    try:
        allowed = await is_admin(update, context)
    except TelegramError:
        allowed = False
    if not allowed:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⛔ Менять адрес игры могут только администраторы чата.',
            reply_to_message_id=message.id,
        )
        return

    if len(context.args) != 1 or not valid_url(context.args[0]):
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Формат: /game_url https://foundry.example',
            reply_to_message_id=message.id,
        )
        return

    try:
        if core is not None:
            await core.set_game_url(chat.id, context.args[0])
        else:
            await session_service(context).set_default_url(
                chat.id, context.args[0], datetime.now(UTC)
            )
    except CoreClientError:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Core недоступен или отклонил запрос.',
            reply_to_message_id=message.id,
        )
        return
    await context.bot.send_message(
        chat_id=chat.id,
        text=f'✅ Адрес Foundry по умолчанию сохранён: {context.args[0]}',
        reply_to_message_id=message.id,
    )
