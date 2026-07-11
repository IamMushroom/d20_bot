import logging

from telegram import Update
from telegram.ext import ContextTypes

from dice.roll import Roller, evaluate_roll_expression, roll_d20, roll_regular

INVALID_ROLL_MESSAGE = (
    '⚠️ Неверный формат броска.\nПримеры: d20, 1d12 + 1d6, '
    '1d10 + 4, 2d20 - 1d4. Максимум: 100 кубов и 1000 граней'
)


async def _handle_roll(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    roller: Roller,
    command_name: str,
) -> None:
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return

    expression = ' '.join(context.args)
    if not expression:
        await context.bot.send_message(
            chat_id=chat.id,
            text=f'⚠️ Нет аргумента.\nПримеры: /{command_name} 2d6, /{command_name} 1d20 + 4',
            reply_to_message_id=message.id,
        )
        logging.warning(
            'Roll command has no argument',
            extra={'chat_id': chat.id, 'command': command_name},
        )
        return

    text = evaluate_roll_expression(expression, roller)
    if text is None:
        text = INVALID_ROLL_MESSAGE
        logging.warning(
            'Invalid roll expression',
            extra={'chat_id': chat.id, 'command': command_name, 'argument': expression},
        )
    else:
        logging.info(
            'Dice rolled',
            extra={'chat_id': chat.id, 'command': command_name, 'argument': expression},
        )

    await context.bot.send_message(
        chat_id=chat.id,
        text=text,
        reply_to_message_id=message.id,
    )


async def roll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roll cubes using a regular random distribution."""
    await _handle_roll(update, context, roll_regular, 'roll')


async def rolld20(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roll cubes with increased chances for minimum and maximum values."""
    await _handle_roll(update, context, roll_d20, 'rolld20')


async def roll20(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roll cubes with increased chances for minimum and maximum values."""
    await _handle_roll(update, context, roll_d20, 'roll20')
