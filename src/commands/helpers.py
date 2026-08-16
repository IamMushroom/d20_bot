from telegram import Update
from telegram.ext import ContextTypes


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return False
    if getattr(chat, 'type', None) == 'private':
        return True
    member = await context.bot.get_chat_member(chat.id, user.id)
    return member.status in {'administrator', 'creator', 'owner'}
