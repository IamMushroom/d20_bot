import logging
from datetime import UTC, datetime
from os import getenv

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from commands.game_utils import game_message, parse_game_date, valid_url
from commands.helpers import is_admin, session_service

USAGE = '⚠️ Формат: /game ДД.ММ.ГГГГ ЧЧ:ММ [https://foundry.example]'


async def game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the next game or let a chat administrator schedule it."""
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return

    service = session_service(context)
    if not context.args:
        session = await service.get_planned(chat.id)
        text = game_message(session) if session else '📅 Следующая игра пока не назначена.'
        await context.bot.send_message(chat_id=chat.id, text=text, reply_to_message_id=message.id)
        return

    try:
        allowed = await is_admin(update, context)
    except TelegramError:
        allowed = False
    if not allowed:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⛔ Назначать игру могут только администраторы чата.',
            reply_to_message_id=message.id,
        )
        return

    if len(context.args) not in {2, 3}:
        await context.bot.send_message(chat_id=chat.id, text=USAGE, reply_to_message_id=message.id)
        return
    default_url = await service.get_default_url(chat.id)
    foundry_url = (
        context.args[2] if len(context.args) == 3 else default_url or getenv('FOUNDRY_URL', '')
    )
    if not valid_url(foundry_url):
        await context.bot.send_message(
            chat_id=chat.id,
            text=f'⚠️ Укажи ссылку третьим аргументом или настрой корректный FOUNDRY_URL.\n{USAGE}',
            reply_to_message_id=message.id,
        )
        return
    try:
        scheduled_at = parse_game_date(context.args[0], context.args[1], datetime.now(UTC))
    except ValueError:
        await context.bot.send_message(chat_id=chat.id, text=USAGE, reply_to_message_id=message.id)
        return

    result = await service.schedule(
        chat.id, getattr(chat, 'title', None), scheduled_at, foundry_url
    )
    announcement = await context.bot.send_message(
        chat_id=chat.id, text=game_message(result.session)
    )
    await service.set_announcement(result.session.id, announcement.id)

    try:
        await context.bot.pin_chat_message(
            chat_id=chat.id, message_id=announcement.id, disable_notification=True
        )
    except TelegramError:
        logging.warning('Could not pin game schedule', extra={'chat_id': chat.id})
        await context.bot.send_message(
            chat_id=chat.id,
            text='ℹ️ Расписание сохранено, но закрепить его не удалось. Дайте боту право закреплять сообщения.',
        )
        return
    if result.previous_message_id is not None:
        try:
            await context.bot.unpin_chat_message(
                chat_id=chat.id, message_id=result.previous_message_id
            )
        except TelegramError:
            logging.warning('Could not unpin previous game schedule', extra={'chat_id': chat.id})
