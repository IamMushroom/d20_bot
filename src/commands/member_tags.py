import logging

from telegram.error import TelegramError
from telegram.ext import ContextTypes

TAG_SET = 'set'
TAG_ADMINISTRATOR = 'administrator'
TAG_UNSUPPORTED = 'unsupported'
TAG_FAILED = 'failed'


async def set_member_tag(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, tag: str
) -> str:
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
