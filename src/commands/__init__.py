from dice.roll import roll_regular, roll_d20
from utils import normalize_input
from telegram import Update
from telegram.ext import ContextTypes
import logging
import inspect

async def roll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roll cubes. Example: /roll 2d6, /roll 8к20
    """
    frame = inspect.currentframe()
    f_name = frame.f_code.co_name # type: ignore
    input: str = update.message.text # type: ignore
    try: input = input.split(' ')[1]
    except:
        await context.bot.send_message(
            chat_id = update.effective_chat.id, # type: ignore
            text = 'Нет аргумента. Примеры: /roll 2d6, /roll 8к20',
            reply_to_message_id = update.effective_message.id) # type: ignore
        logging.error(f'"chat_id": "{update.effective_chat.id}", "function": "{f_name}", "message": "leak of argument"') # type: ignore
        return
    ni = normalize_input(input)
    if ni[0] == 0:
        text = 'Не верный разделитель. Поддерживается либо латинская d (3d12), либо русская к (8к10)'
        logging.warning(f'"chat_id": "{update.effective_chat.id}", "function": "{f_name}", "message": "wrong delimeter", "argument": "{input}"') # type: ignore
    else:
        r = roll_regular(ni[0], ni[1])
        text = f'Your roll: {sum(r)} ({" + ".join(map(str, r))})'
        logging.info(f'"chat_id": "{update.effective_chat.id}", "function": "{f_name}", "argument": "{input}"') # type: ignore
    await context.bot.send_message(
        chat_id = update.effective_chat.id, # type: ignore
        text = text,
        reply_to_message_id = update.effective_message.id) # type: ignore

async def rolld20(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roll cubes with increased chances for max and min roll. Example: /rolld20 2d6, /rolld20 8к20
    """
    frame = inspect.currentframe()
    f_name = frame.f_code.co_name # type: ignore
    input: str = update.message.text # type: ignore
    try: input = input.split(' ')[1]
    except:
        await context.bot.send_message(
            chat_id = update.effective_chat.id, # type: ignore
            text = 'Нет аргумента. Примеры: /roll 2d6, /roll 8к20',
            reply_to_message_id = update.effective_message.id) # type: ignore
        logging.error(f'"chat_id": "{update.effective_chat.id}", "function": "{f_name}", "message": "leak of argument"') # type: ignore
        return
    ni = normalize_input(input)
    if ni[0] == 0:
        text = 'Не верный разделитель. Поддерживается либо латинская d (3d12), либо русская к (8к10)'
        logging.warning(f'"chat_id": "{update.effective_chat.id}", "function": "{f_name}", "message": "wrong delimeter", "argument": "{input}"') # type: ignore
    else:
        r = roll_d20(ni[0], ni[1])
        text = f'Your roll: {sum(r)} ({" + ".join(map(str, r))})'
        logging.info(f'"chat_id": "{update.effective_chat.id}", "function": "{f_name}", "argument": "{input}"') # type: ignore
    await context.bot.send_message(
        chat_id = update.effective_chat.id, # type: ignore
        text = text,
        reply_to_message_id = update.effective_message.id) # type: ignore
