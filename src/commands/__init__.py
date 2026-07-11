from dice.roll import Roller, dgh, evaluate_roll_expression, roll_d20, roll_regular
from telegram import Update
from telegram.ext import ContextTypes
from asyncio import sleep
import logging
import inspect

INVALID_ROLL_MESSAGE = (
    'Неверный формат броска. Примеры: d20, 1d12 + 1d6, '
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
            text=f'Нет аргумента. Примеры: /{command_name} 2d6, /{command_name} 1d20 + 4',
            reply_to_message_id=message.id,
        )
        logging.error(
            f'"chat_id": "{chat.id}", "function": "{command_name}", "message": "lack of argument"'
        )
        return

    text = evaluate_roll_expression(expression, roller)
    if text is None:
        text = INVALID_ROLL_MESSAGE
        logging.warning(
            f'"chat_id": "{chat.id}", "function": "{command_name}", '
            f'"message": "invalid expression", "argument": "{expression}"'
        )
    else:
        logging.info(
            f'"chat_id": "{chat.id}", "function": "{command_name}", "argument": "{expression}"'
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

async def timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set timer. Example: /timer 180, /timer
    """
    o = {1: 'у', 2: 'ы', 3: 'ы', 4: 'ы'}
    frame = inspect.currentframe()
    f_name = frame.f_code.co_name # type: ignore
    input: str = update.message.text # type: ignore
    try: sec = input.split(' ')[1]
    except:
        sec = 60
    try: sec = int(sec)
    except:
        await context.bot.send_message(
            chat_id = update.effective_chat.id, # type: ignore
            text = 'Аргументом должно быть целое число. Примеры: /timer 60, /timer 180',
            reply_to_message_id = update.effective_message.id) # type: ignore
        logging.error(f'"chat_id": "{update.effective_chat.id}", "function": "{f_name}", "message": "argument mistype"') # type: ignore
        return
    logging.info(f'"chat_id": "{update.effective_chat.id}", "function": "{f_name}", "argument": "{input}"') # type: ignore
    text_o = sec % 10
    try: text = f'Поставлен таймер на {sec} секунд{o[text_o]}'
    except: text = f'Поставлен таймер на {sec} секунд'
    await context.bot.send_message(
        chat_id = update.effective_chat.id, # type: ignore
        text = text,
        reply_to_message_id = update.effective_message.id) # type: ignore
    await sleep(sec)
    await context.bot.send_message(
        chat_id = update.effective_chat.id, # type: ignore
        text = 'Время истекло',
        reply_to_message_id = update.effective_message.id) # type: ignore

async def duality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roll duality cubes. Example: /duality
    """
    frame = inspect.currentframe()
    f_name = frame.f_code.co_name # type: ignore
    input: str = update.message.text # type: ignore
    text = dgh()
    logging.info(f'"chat_id": "{update.effective_chat.id}", "function": "{f_name}", "argument": "{input}"') # type: ignore
    await context.bot.send_message(
        chat_id = update.effective_chat.id, # type: ignore
        text = text,
        reply_to_message_id = update.effective_message.id) # type: ignore
