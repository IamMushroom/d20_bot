import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from commands.helpers import session_service
from services import SessionStartStatus, SessionStopStatus


async def session_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start the planned session, or create an unplanned active session."""
    chat = update.effective_chat
    message = update.effective_message
    user = update.effective_user
    if chat is None or message is None or user is None:
        return
    service = session_service(context)
    title = ' '.join(context.args).strip() or None
    result = await service.start(chat.id, user.id, title)
    if result.status is SessionStartStatus.FORBIDDEN:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⛔ Запускать сессию может только назначенный мастер.',
            reply_to_message_id=message.id,
        )
        return
    if result.status is SessionStartStatus.ALREADY_ACTIVE:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ В этой кампании уже идёт активная сессия.',
            reply_to_message_id=message.id,
        )
        return
    session = result.session
    assert session is not None
    if result.announcement_message_id is not None:
        try:
            await context.bot.unpin_chat_message(
                chat_id=chat.id, message_id=result.announcement_message_id
            )
        except TelegramError:
            logging.warning('Could not unpin started session', extra={'chat_id': chat.id})
    title_text = f' — {session.title}' if session.title else ''
    await context.bot.send_message(
        chat_id=chat.id,
        text=f'▶️ Сессия №{session.number}{title_text} началась!',
        reply_to_message_id=message.id,
    )


async def session_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Finish the active campaign session."""
    chat = update.effective_chat
    message = update.effective_message
    user = update.effective_user
    if chat is None or message is None or user is None:
        return
    service = session_service(context)
    result = await service.stop(chat.id, user.id)
    if result.status is SessionStopStatus.FORBIDDEN:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⛔ Завершать сессию может только назначенный мастер.',
            reply_to_message_id=message.id,
        )
        return
    if result.status is SessionStopStatus.NO_ACTIVE_SESSION:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Активной сессии сейчас нет.',
            reply_to_message_id=message.id,
        )
        return
    session = result.session
    assert session is not None
    await context.bot.send_message(
        chat_id=chat.id,
        text=f'⏹️ Сессия №{session.number} завершена.',
        reply_to_message_id=message.id,
    )
