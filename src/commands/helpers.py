from telegram import Update
from telegram.ext import ContextTypes

from services import CampaignService, SessionService

DATABASE_KEY = 'database'
CAMPAIGN_SERVICE_KEY = 'campaign_service'
SESSION_SERVICE_KEY = 'session_service'


def campaign_service(context: ContextTypes.DEFAULT_TYPE) -> CampaignService:
    return context.application.bot_data[CAMPAIGN_SERVICE_KEY]


def session_service(context: ContextTypes.DEFAULT_TYPE) -> SessionService:
    return context.application.bot_data[SESSION_SERVICE_KEY]


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return False
    if getattr(chat, 'type', None) == 'private':
        return True
    member = await context.bot.get_chat_member(chat.id, user.id)
    return member.status in {'administrator', 'creator', 'owner'}
