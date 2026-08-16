import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from core import CORE_CLIENT_KEY, CoreClient, CoreClientError


async def session_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start the planned session, or create an unplanned active session."""
    chat = update.effective_chat
    message = update.effective_message
    user = update.effective_user
    if chat is None or message is None or user is None:
        return
    title = ' '.join(context.args).strip() or None
    core: CoreClient = context.application.bot_data[CORE_CLIENT_KEY]
    try:
        remote = await core.start_session(chat.id, user.id, title)
        status = remote.status
        number = remote.number
        session_title = remote.title
        announcement_message_id = remote.announcement_message_id
    except CoreClientError:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Core недоступен или отклонил запрос.',
            reply_to_message_id=message.id,
        )
        return
    if status == 'forbidden':
        await context.bot.send_message(
            chat_id=chat.id,
            text='⛔ Запускать сессию может только назначенный мастер.',
            reply_to_message_id=message.id,
        )
        return
    if status == 'already_active':
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ В этой кампании уже идёт активная сессия.',
            reply_to_message_id=message.id,
        )
        return
    assert number is not None
    if announcement_message_id is not None:
        try:
            await context.bot.unpin_chat_message(
                chat_id=chat.id, message_id=announcement_message_id
            )
        except TelegramError:
            logging.warning('Could not unpin started session', extra={'chat_id': chat.id})
    title_text = f' — {session_title}' if session_title else ''
    await context.bot.send_message(
        chat_id=chat.id,
        text=f'▶️ Сессия №{number}{title_text} началась!',
        reply_to_message_id=message.id,
    )


async def session_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Finish the active campaign session."""
    chat = update.effective_chat
    message = update.effective_message
    user = update.effective_user
    if chat is None or message is None or user is None:
        return
    core: CoreClient = context.application.bot_data[CORE_CLIENT_KEY]
    try:
        remote = await core.stop_session(chat.id, user.id)
        status = remote.status
        number = remote.number
    except CoreClientError:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Core недоступен или отклонил запрос.',
            reply_to_message_id=message.id,
        )
        return
    if status == 'forbidden':
        await context.bot.send_message(
            chat_id=chat.id,
            text='⛔ Завершать сессию может только назначенный мастер.',
            reply_to_message_id=message.id,
        )
        return
    if status == 'no_active_session':
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Активной сессии сейчас нет.',
            reply_to_message_id=message.id,
        )
        return
    assert number is not None
    await context.bot.send_message(
        chat_id=chat.id,
        text=f'⏹️ Сессия №{number} завершена.',
        reply_to_message_id=message.id,
    )
