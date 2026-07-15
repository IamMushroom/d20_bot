import logging
from datetime import UTC, datetime
from os import getenv

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from commands.game_utils import game_message, parse_game_date, valid_url
from commands.helpers import is_admin, session_service
from core import CORE_CLIENT_KEY, CoreClient, CoreClientError

USAGE = '⚠️ Формат: /game ДД.ММ.ГГГГ ЧЧ:ММ [https://foundry.example]'


async def game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the next game or let a chat administrator schedule it."""
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return

    core: CoreClient | None = context.application.bot_data.get(CORE_CLIENT_KEY)
    if not context.args:
        if core is not None:
            try:
                text = await core.get_game(chat.id)
            except CoreClientError:
                text = '⚠️ Core недоступен или отклонил запрос.'
        else:
            session = await session_service(context).get_planned(chat.id)
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
    explicit_url = context.args[2] if len(context.args) == 3 else None
    default_url = await session_service(context).get_default_url(chat.id) if core is None else None
    foundry_url = explicit_url or default_url or (getenv('FOUNDRY_URL', '') if core is None else '')
    if explicit_url is not None and not valid_url(explicit_url):
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

    if core is not None:
        try:
            remote = await core.schedule_game(
                chat.id, getattr(chat, 'title', None), scheduled_at, foundry_url or None
            )
        except CoreClientError:
            await context.bot.send_message(
                chat_id=chat.id,
                text='⚠️ Core недоступен, отклонил запрос или адрес Foundry не настроен.',
                reply_to_message_id=message.id,
            )
            return
        announcement = await context.bot.send_message(chat_id=chat.id, text=remote.message)
        try:
            await core.set_game_announcement(remote.session_id, announcement.id)
        except CoreClientError:
            logging.warning('Could not save game announcement in Core', extra={'chat_id': chat.id})
        previous_message_id = remote.previous_message_id
    else:
        if not valid_url(foundry_url):
            await context.bot.send_message(
                chat_id=chat.id,
                text=f'⚠️ Укажи ссылку третьим аргументом или настрой корректный FOUNDRY_URL.\n{USAGE}',
                reply_to_message_id=message.id,
            )
            return
        service = session_service(context)
        result = await service.schedule(
            chat.id, getattr(chat, 'title', None), scheduled_at, foundry_url
        )
        announcement = await context.bot.send_message(
            chat_id=chat.id, text=game_message(result.session)
        )
        await service.set_announcement(result.session.id, announcement.id)
        previous_message_id = result.previous_message_id

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
    if previous_message_id is not None:
        try:
            await context.bot.unpin_chat_message(chat_id=chat.id, message_id=previous_message_id)
        except TelegramError:
            logging.warning('Could not unpin previous game schedule', extra={'chat_id': chat.id})
