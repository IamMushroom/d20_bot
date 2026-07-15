from urllib.parse import urlencode

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from commands.helpers import campaign_service
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
    base_url = context.application.bot_data.get(WEB_BASE_URL_KEY)
    if not base_url:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Веб-панель не включена. Задайте WEB_BASE_URL.',
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
