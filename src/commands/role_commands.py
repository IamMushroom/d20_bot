from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from commands.helpers import campaign_service, is_admin
from commands.member_tags import (
    TAG_ADMINISTRATOR,
    TAG_SET,
    TAG_UNSUPPORTED,
    set_member_tag,
)
from core import CORE_CLIENT_KEY, CoreClient, CoreClientError
from services import PlayerRegistrationStatus

MAX_TAG_LENGTH = 16


async def master(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Assign the campaign master to the caller or the user whose message is replied to."""
    chat = update.effective_chat
    message = update.effective_message
    user = update.effective_user
    if chat is None or message is None or user is None:
        return
    try:
        allowed = await is_admin(update, context)
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

    core: CoreClient | None = context.application.bot_data.get(CORE_CLIENT_KEY)
    try:
        if core is not None:
            await core.assign_master(chat.id, target.id, getattr(chat, 'title', None))
        else:
            await campaign_service(context).assign_master(
                chat.id, target.id, getattr(chat, 'title', None)
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
        text=f'🎭 Мастер кампании назначен: {target.full_name}',
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

    core: CoreClient | None = context.application.bot_data.get(CORE_CLIENT_KEY)
    try:
        if core is not None:
            remote = await core.register_player(
                chat.id, user.id, name, getattr(chat, 'title', None)
            )
            status = remote.status
            character_name = remote.name
        else:
            local = await campaign_service(context).register_player(
                chat.id, user.id, name, getattr(chat, 'title', None)
            )
            status = local.status
            character_name = local.character.name if local.character is not None else None
    except CoreClientError:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Core недоступен или отклонил запрос.',
            reply_to_message_id=message.id,
        )
        return
    if status is PlayerRegistrationStatus.MASTER_CONFLICT or status == 'master_conflict':
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Мастер уже имеет роль «Мастер» и не может зарегистрироваться игроком.',
            reply_to_message_id=message.id,
        )
        return
    assert character_name is not None
    tag_result = (
        TAG_UNSUPPORTED
        if getattr(chat, 'type', None) == 'private'
        else await set_member_tag(context, chat.id, user.id, character_name)
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
        text=f'🧙 Игрок зарегистрирован: {character_name}{suffix}',
        reply_to_message_id=message.id,
    )
