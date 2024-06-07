from dice.roll import roll_regular, roll_d20
from utils import normalize_input
from telegram import Update
from telegram.ext import ContextTypes

async def roll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    input: str = update.message.text # type: ignore
    try: input = input.split(' ')[1]
    except:
        await context.bot.send_message(
            chat_id = update.effective_chat.id, # type: ignore
            text = 'Нет аргумента. Примеры: /roll 2d6, /roll 8к20',
            reply_to_message_id = update.effective_message.id) # type: ignore
        return
    ni = normalize_input(input)
    if ni[0] == 0:
        text = 'Не верный разделитель. Поддерживается либо латинская d (3d12), либо русская к (8к10)'
    else:
        r = roll_regular(ni[0], ni[1])
        text = f'Your roll: {sum(r)} ({" + ".join(map(str, r))})'
    await context.bot.send_message(
        chat_id = update.effective_chat.id, # type: ignore
        text = text,
        reply_to_message_id = update.effective_message.id) # type: ignore