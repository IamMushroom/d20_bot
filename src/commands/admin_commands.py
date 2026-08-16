import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from commands.game_utils import valid_url
from commands.helpers import is_admin
from core import CORE_CLIENT_KEY, CoreClient, CoreClientError


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the campaign master a short-lived link to the web panel."""
    chat = update.effective_chat
    message = update.effective_message
    user = update.effective_user
    if chat is None or message is None or user is None:
        return
    if getattr(chat, 'type', None) == 'private':
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Вызовите /admin в группе кампании. Ссылку бот пришлёт сюда, в личный чат.',
            reply_to_message_id=message.id,
        )
        return
    core_client: CoreClient = context.application.bot_data[CORE_CLIENT_KEY]
    try:
        url = await core_client.create_admin_link(chat.id, user.id, getattr(chat, 'title', None))
    except CoreClientError as error:
        logging.warning(
            'Could not create admin link through Core',
            extra={
                'error_type': type(error).__name__,
                'error_message': str(error),
                'core_path': '/api/admin-link',
            },
        )
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Core недоступен или отклонил запрос.',
            reply_to_message_id=message.id,
        )
        return
    await _send_admin_link(update, context, url)


async def web_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Issue a one-time code that binds a local account to the Telegram user."""
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    core: CoreClient = context.application.bot_data[CORE_CLIENT_KEY]
    try:
        code = await core.create_registration_code(user.id)
    except CoreClientError:
        await context.bot.send_message(
            chat_id=message.chat_id,
            text='⚠️ Не удалось выпустить код. Сначала зарегистрируйтесь в кампании командой /player или /master.',
            reply_to_message_id=message.id,
        )
        return
    await context.bot.send_message(
        chat_id=user.id,
        text=f'🔐 Код регистрации в D20 Control: `{code}`\nОн действует 15 минут.',
        parse_mode='Markdown',
    )
    if message.chat_id != user.id:
        await context.bot.send_message(
            chat_id=message.chat_id,
            text='✅ Код регистрации отправлен в личные сообщения.',
            reply_to_message_id=message.id,
        )


async def _send_admin_link(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    chat = update.effective_chat
    message = update.effective_message
    user = update.effective_user
    assert chat is not None and message is not None and user is not None
    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=f'🔐 Панель мастера: {url}\nСсылка одноразовая и действует 15 минут.',
        )
    except TelegramError:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Не удалось отправить ссылку в личные сообщения. Снача откройте диалог с ботом.',
            reply_to_message_id=message.id,
        )


async def web_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show or set the web panel URL for this chat."""
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return
    core: CoreClient = context.application.bot_data[CORE_CLIENT_KEY]
    if not context.args:
        try:
            value = await core.get_web_url(chat.id)
        except CoreClientError:
            value = None
        text = f'🌐 Адрес панели: {value}' if value else '📭 Адрес панели пока не задан.'
        await context.bot.send_message(chat_id=chat.id, text=text, reply_to_message_id=message.id)
        return
    try:
        allowed = await is_admin(update, context)
    except TelegramError:
        allowed = False
    if not allowed:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⛔ Менять адрес панели могут только администраторы чата.',
            reply_to_message_id=message.id,
        )
        return
    if len(context.args) != 1 or not valid_url(context.args[0]):
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Формат: /web_url https://d20.example',
            reply_to_message_id=message.id,
        )
        return
    value = context.args[0].rstrip('/')
    try:
        await core.set_web_url(chat.id, value)
    except CoreClientError:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Core недоступен или отклонил запрос.',
            reply_to_message_id=message.id,
        )
        return
    await context.bot.send_message(
        chat_id=chat.id,
        text=f'✅ Адрес панели сохранён: {value}',
        reply_to_message_id=message.id,
    )
