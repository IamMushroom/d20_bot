import logging
import sqlite3

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from database.repositories import CampaignRepository, CharacterRepository, SessionRepository

DATABASE_KEY = 'database'
MAX_TAG_LENGTH = 16
TAG_SET = 'set'
TAG_ADMINISTRATOR = 'administrator'
TAG_UNSUPPORTED = 'unsupported'
TAG_FAILED = 'failed'


async def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return False
    if getattr(chat, 'type', None) == 'private':
        return True
    member = await context.bot.get_chat_member(chat.id, user.id)
    return member.status in {'administrator', 'creator', 'owner'}


async def _set_tag(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, tag: str) -> str:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
    except TelegramError as error:
        logging.warning(
            'Could not get chat member before setting tag',
            extra={
                'chat_id': chat_id,
                'user_id': user_id,
                'telegram_method': 'getChatMember',
                'error_type': type(error).__name__,
                'error_message': str(error),
                'tag': tag,
            },
            exc_info=True,
        )
        return TAG_FAILED
    if member.status in {'administrator', 'creator', 'owner'}:
        return TAG_ADMINISTRATOR
    try:
        await context.bot.set_chat_member_tag(chat_id=chat_id, user_id=user_id, tag=tag)
    except TelegramError as error:
        logging.warning(
            'Could not set chat member tag',
            extra={
                'chat_id': chat_id,
                'user_id': user_id,
                'telegram_method': 'setChatMemberTag',
                'error_type': type(error).__name__,
                'error_message': str(error),
                'tag': tag,
            },
            exc_info=True,
        )
        return TAG_FAILED
    return TAG_SET


async def master(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Assign the campaign master to the caller or the user whose message is replied to."""
    chat = update.effective_chat
    message = update.effective_message
    user = update.effective_user
    if chat is None or message is None or user is None:
        return
    try:
        allowed = await _is_admin(update, context)
    except TelegramError:
        allowed = False
    if not allowed:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⛔ Назначать мастера могут только администраторы чата.',
            reply_to_message_id=message.id,
        )
        return

    replied = getattr(message, 'reply_to_message', None)
    target = getattr(replied, 'from_user', None) or user
    if getattr(target, 'is_bot', False):
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Бота нельзя назначить мастером.',
            reply_to_message_id=message.id,
        )
        return

    campaigns = CampaignRepository(context.application.bot_data[DATABASE_KEY])
    await campaigns.set_master(chat.id, target.id, getattr(chat, 'title', None))
    tag_result = (
        TAG_UNSUPPORTED
        if getattr(chat, 'type', None) == 'private'
        else await _set_tag(context, chat.id, target.id, 'Мастер')
    )
    if tag_result == TAG_SET:
        suffix = ''
    elif tag_result == TAG_ADMINISTRATOR:
        suffix = (
            '\nℹ️ Telegram не позволяет боту ставить member tag владельцу или администратору. '
            'Задайте заголовок «Мастер» вручную в настройках группы.'
        )
    elif tag_result == TAG_UNSUPPORTED:
        suffix = '\nℹ️ Telegram-теги доступны только в группах.'
    else:
        suffix = '\nℹ️ Роль сохранена, но Telegram-тег установить не удалось.'
    await context.bot.send_message(
        chat_id=chat.id,
        text=f'🎭 Мастер кампании назначен: {target.full_name}{suffix}',
        reply_to_message_id=message.id,
    )


async def player(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Register the caller as a player and use the character name as their member tag."""
    chat = update.effective_chat
    message = update.effective_message
    user = update.effective_user
    if chat is None or message is None or user is None:
        return
    name = ' '.join(context.args).strip()
    if not name or len(name) > MAX_TAG_LENGTH:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Формат: /player <имя персонажа> (до 16 символов)',
            reply_to_message_id=message.id,
        )
        return

    database = context.application.bot_data[DATABASE_KEY]
    campaigns = CampaignRepository(database)
    campaign = await campaigns.get_or_create(chat.id, getattr(chat, 'title', None))
    if campaign.master_user_id == user.id:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Мастер уже имеет роль «Мастер» и не может зарегистрироваться игроком.',
            reply_to_message_id=message.id,
        )
        return
    character = await CharacterRepository(database).register(campaign.id, user.id, name)
    tag_result = (
        TAG_UNSUPPORTED
        if getattr(chat, 'type', None) == 'private'
        else await _set_tag(context, chat.id, user.id, character.name)
    )
    if tag_result == TAG_SET:
        suffix = ''
    elif tag_result == TAG_ADMINISTRATOR:
        suffix = '\nℹ️ Персонаж сохранён, но Telegram member tag доступен только обычным участникам.'
    elif tag_result == TAG_UNSUPPORTED:
        suffix = '\nℹ️ Telegram-теги доступны только в группах.'
    else:
        suffix = '\nℹ️ Персонаж сохранён, но Telegram-тег установить не удалось.'
    await context.bot.send_message(
        chat_id=chat.id,
        text=f'🧙 Игрок зарегистрирован: {character.name}{suffix}',
        reply_to_message_id=message.id,
    )


async def _master_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return None
    campaign = await CampaignRepository(context.application.bot_data[DATABASE_KEY]).get_by_chat_id(
        chat.id
    )
    return campaign if campaign is not None and campaign.master_user_id == user.id else None


async def session_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start the planned session, or create an unplanned active session."""
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return
    campaign = await _master_campaign(update, context)
    if campaign is None:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⛔ Запускать сессию может только назначенный мастер.',
            reply_to_message_id=message.id,
        )
        return

    sessions = SessionRepository(context.application.bot_data[DATABASE_KEY])
    planned = await sessions.get_planned(campaign.id)
    title = ' '.join(context.args).strip() or None
    try:
        session = await sessions.start(campaign.id, title)
    except sqlite3.IntegrityError:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ В этой кампании уже идёт активная сессия.',
            reply_to_message_id=message.id,
        )
        return
    if planned is not None and planned.message_id is not None:
        try:
            await context.bot.unpin_chat_message(chat_id=chat.id, message_id=planned.message_id)
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
    if chat is None or message is None:
        return
    campaign = await _master_campaign(update, context)
    if campaign is None:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⛔ Завершать сессию может только назначенный мастер.',
            reply_to_message_id=message.id,
        )
        return
    sessions = SessionRepository(context.application.bot_data[DATABASE_KEY])
    active = await sessions.get_active(campaign.id)
    if active is None:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Активной сессии сейчас нет.',
            reply_to_message_id=message.id,
        )
        return
    session = await sessions.finish(active.id)
    assert session is not None
    await context.bot.send_message(
        chat_id=chat.id,
        text=f'⏹️ Сессия №{session.number} завершена.',
        reply_to_message_id=message.id,
    )
