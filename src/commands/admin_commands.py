from datetime import UTC, datetime
from urllib.parse import urlencode

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from commands.game_utils import valid_url
from commands.helpers import campaign_service, is_admin, session_service
from core import CORE_CLIENT_KEY, CoreClient, CoreClientError
from web.access import AdminAccessService, AdminIdentity

ADMIN_ACCESS_KEY = 'admin_access'
WEB_BASE_URL_KEY = 'web_base_url'


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the campaign master a short-lived link to the web panel."""
    chat = update.effective_chat
    message = update.effective_message
    user = update.effective_user
    if chat is None or message is None or user is None:
        return
    core_client: CoreClient | None = context.application.bot_data.get(CORE_CLIENT_KEY)
    if core_client is not None:
        try:
            url = await core_client.create_admin_link(
                chat.id, user.id, getattr(chat, 'title', None)
            )
        except CoreClientError:
            await context.bot.send_message(
                chat_id=chat.id,
                text='⚠️ Core недоступен или отклонил запрос.',
                reply_to_message_id=message.id,
            )
            return
        await _send_admin_link(update, context, url)
        return
    base_url = await session_service(context).get_web_base_url(
        chat.id
    ) or context.application.bot_data.get(WEB_BASE_URL_KEY)
    if not base_url:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Адрес веб-панели не задан. Используйте /web_url.',
            reply_to_message_id=message.id,
        )
        return
    if not await campaign_service(context).is_master(chat.id, user.id):
        await context.bot.send_message(
            chat_id=chat.id,
            text='⛔ Веб-панель доступна только назначенному мастеру.',
            reply_to_message_id=message.id,
        )
        return
    access: AdminAccessService = context.application.bot_data[ADMIN_ACCESS_KEY]
    token = access.create_login(AdminIdentity(chat.id, user.id, getattr(chat, 'title', None)))
    url = f'{base_url.rstrip("/")}/login?{urlencode({"token": token})}'
    await _send_admin_link(update, context, url)


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
    core: CoreClient | None = context.application.bot_data.get(CORE_CLIENT_KEY)
    if not context.args:
        try:
            value = (
                await core.get_web_url(chat.id)
                if core is not None
                else await session_service(context).get_web_base_url(chat.id)
                or context.application.bot_data.get(WEB_BASE_URL_KEY)
            )
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
        if core is not None:
            await core.set_web_url(chat.id, value)
        else:
            await session_service(context).set_web_base_url(chat.id, value, datetime.now(UTC))
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
