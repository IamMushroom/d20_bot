import logging

from telegram import Update
from telegram.ext import ContextTypes

from dice.expression import RollParseError
from dice.roll import Roller, evaluate_roll_expression, roll_d20, roll_regular

LAST_ROLL_KEY = 'last_roll_expressions'


def _invalid_roll_message(error: RollParseError) -> str:
    fragment = f'\nПроблемный фрагмент: `{error.fragment}`' if error.fragment else ''
    return (
        f'⚠️ Не удалось разобрать бросок: {error.message}.{fragment}\n'
        'Примеры: d20, 1d12 + 1d6, 4d6kh3, 2d20kl'
    )


async def _handle_roll(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    roller: Roller,
    command_name: str,
    expression: str | None = None,
) -> None:
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return

    expression = expression or ' '.join(context.args) or 'd20'

    try:
        text = evaluate_roll_expression(expression, roller)
    except RollParseError as error:
        text = _invalid_roll_message(error)
        logging.warning(
            'Invalid roll expression',
            extra={'chat_id': chat.id, 'command': command_name, 'argument': expression},
        )
    else:
        context.user_data[LAST_ROLL_KEY] = (expression, roller.__name__)
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


async def reroll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Repeat the user's last successful roll with fresh random values."""
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return
    saved = context.user_data.get(LAST_ROLL_KEY)
    if not isinstance(saved, tuple) or len(saved) != 2:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Пока нечего перебрасывать. Сначала сделайте бросок.',
            reply_to_message_id=message.id,
        )
        return
    expression, roller_name = saved
    roller = roll_d20 if roller_name == roll_d20.__name__ else roll_regular
    await _handle_roll(update, context, roller, 'reroll', expression)
