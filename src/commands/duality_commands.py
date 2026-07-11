import logging

from dice.expression import MAX_MODIFIER
from dice.roll import dgh
from telegram import Update
from telegram.ext import ContextTypes


async def duality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roll duality cubes. Example: /duality."""
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return

    command_name = message.text.split()[0].removeprefix('/').split('@')[0] if message.text else 'duality'
    modifier = 0
    if len(context.args) > 1:
        modifier_is_valid = False
    else:
        try:
            modifier = int(context.args[0]) if context.args else 0
            modifier_is_valid = abs(modifier) <= MAX_MODIFIER
        except ValueError:
            modifier_is_valid = False

    if not modifier_is_valid:
        await context.bot.send_message(
            chat_id=chat.id,
            text=f'⚠️ Модификатор должен быть целым числом.\nПример: /{command_name} 5',
            reply_to_message_id=message.id,
        )
        logging.warning(
            'Invalid duality modifier',
            extra={
                'chat_id': chat.id,
                'command': command_name,
                'argument': ' '.join(context.args),
            },
        )
        return

    text = dgh(modifier)
    logging.info(
        'Duality dice rolled',
        extra={'chat_id': chat.id, 'command': command_name, 'argument': modifier},
    )
    await context.bot.send_message(
        chat_id=chat.id,
        text=text,
        reply_to_message_id=message.id,
    )
