from random import randint
from typing import Tuple
from dotenv import load_dotenv
from os import getenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, filters


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
        r = roll_dice(ni[0], ni[1])
        text = f'Your roll: {sum(r)} ({" + ".join(map(str, r))})'
    await context.bot.send_message(
        chat_id = update.effective_chat.id, # type: ignore
        text = text,
        reply_to_message_id = update.effective_message.id) # type: ignore

def roll_dice(count: int, dice: int) -> Tuple[int, ...]:
    result = ()
    for _ in range(count):
        result += (randint (1, dice),)
    return result

def normalize_input(string: str) -> Tuple[int, int]:
    r = string.split('d')    
    if len(r) == 1:
        r = string.split('к')
    if len(r) == 1:
        return (0,0)
    return (int(r[0]), int(r[1]))

def main() -> None:
    load_dotenv()
    token: str = getenv('TG_TOKEN', '0')
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("roll", roll, filters.TEXT))
    app.run_polling()

if __name__ == '__main__':
    main()