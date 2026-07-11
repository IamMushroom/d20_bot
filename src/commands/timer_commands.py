import logging
from asyncio import sleep

from telegram import Update
from telegram.ext import ContextTypes

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


async def _finish_timer(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    seconds: int,
    timer_id: str,
) -> None:
    await sleep(seconds)
    await context.bot.send_message(
        chat_id=chat_id,
        text='⏰ Время истекло!',
        reply_to_message_id=message_id,
    )
    logging.info(
        'Timer completed',
        extra={
            'chat_id': chat_id,
            'command': 'timer',
            'argument': seconds,
            'timer_id': timer_id,
        },
    )


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

    timer_id = f'{chat.id}:{message.id}'
    logging.info(
        'Timer started',
        extra={
            'chat_id': chat.id,
            'command': 'timer',
            'argument': seconds,
            'timer_id': timer_id,
        },
    )
    await context.bot.send_message(
        chat_id=chat.id,
        text=f'⏳ Таймер поставлен на {seconds} {_seconds_word(seconds)}',
        reply_to_message_id=message.id,
    )
    context.application.create_task(
        _finish_timer(context, chat.id, message.id, seconds, timer_id),
        update=update,
        name=f'timer-{timer_id}',
    )
