from dice.roll import Roller, dgh, evaluate_roll_expression, roll_d20, roll_regular
from telegram import Update
from telegram.ext import ContextTypes
from asyncio import sleep
import logging
import inspect

INVALID_ROLL_MESSAGE = (
    '⚠️ Неверный формат броска.\nПримеры: d20, 1d12 + 1d6, '
    '1d10 + 4, 2d20 - 1d4. Максимум: 100 кубов и 1000 граней'
)
MIN_TIMER_SECONDS = 1
MAX_TIMER_SECONDS = 86_400


def _seconds_word(seconds: int) -> str:
    if seconds % 100 in range(11, 15):
        return 'секунд'
    if seconds % 10 == 1:
        return 'секунду'
    if seconds % 10 in range(2, 5):
        return 'секунды'
    return 'секунд'


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

async def timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set a timer between 1 second and 24 hours."""
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return

    argument = context.args[0] if len(context.args) == 1 else '60'
    try:
        seconds = int(argument)
    except ValueError:
        seconds = 0

    if len(context.args) > 1 or not MIN_TIMER_SECONDS <= seconds <= MAX_TIMER_SECONDS:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⚠️ Укажи целое число от 1 до 86400.\nПримеры: /timer 60, /timer 180',
            reply_to_message_id=message.id,
        )
        logging.warning(
            'Invalid timer argument',
            extra={'chat_id': chat.id, 'command': 'timer', 'argument': ' '.join(context.args)},
        )
        return

    logging.info(
        'Timer started',
        extra={'chat_id': chat.id, 'command': 'timer', 'argument': seconds},
    )
    await context.bot.send_message(
        chat_id=chat.id,
        text=f'⏳ Таймер поставлен на {seconds} {_seconds_word(seconds)}',
        reply_to_message_id=message.id,
    )
    await sleep(seconds)
    await context.bot.send_message(
        chat_id=chat.id,
        text='⏰ Время истекло!',
        reply_to_message_id=message.id,
    )

async def duality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roll duality cubes. Example: /duality
    """
    frame = inspect.currentframe()
    f_name = frame.f_code.co_name # type: ignore
    input: str = update.message.text # type: ignore
    text = dgh()
    logging.info(
        'Duality dice rolled',
        extra={'chat_id': update.effective_chat.id, 'command': f_name, 'argument': input}, # type: ignore
    )
    await context.bot.send_message(
        chat_id = update.effective_chat.id, # type: ignore
        text = text,
        reply_to_message_id = update.effective_message.id) # type: ignore
