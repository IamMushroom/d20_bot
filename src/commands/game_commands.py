import logging
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from os import getenv
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from database.models import GameSchedule
from database.repositories import GameScheduleRepository

DATABASE_KEY = 'database'
USAGE = '⚠️ Формат: /game ДД.ММ.ГГГГ ЧЧ:ММ [https://foundry.example]'


def _timezone() -> tzinfo:
    name = getenv('GAME_TIMEZONE', 'Europe/Moscow')
    if name == 'UTC':
        return UTC
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == 'Europe/Moscow':
            return timezone(timedelta(hours=3), name='Europe/Moscow')
        logging.error('Unknown GAME_TIMEZONE, falling back to UTC', extra={'timezone': name})
        return UTC


def _parse_date(date_text: str, time_text: str, now: datetime) -> datetime:
    timezone = _timezone()
    now = now.astimezone(timezone)
    if date_text.count('.') == 2:
        parsed = datetime.strptime(f'{date_text} {time_text}', '%d.%m.%Y %H:%M')
    else:
        parsed = datetime.strptime(f'{date_text}.{now.year} {time_text}', '%d.%m.%Y %H:%M')
        if parsed.replace(tzinfo=timezone) <= now:
            parsed = parsed.replace(year=now.year + 1)
    return parsed.replace(tzinfo=timezone).astimezone(UTC)


def _valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {'http', 'https'} and bool(parsed.netloc)


def _message(schedule: GameSchedule) -> str:
    local = schedule.scheduled_at.astimezone(_timezone())
    timezone_name = getenv('GAME_TIMEZONE', 'Europe/Moscow')
    return (
        f'🎲 Следующая игра: {local:%d.%m.%Y в %H:%M} ({timezone_name})\n'
        f'🏰 Foundry: {schedule.foundry_url}'
    )


async def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return False
    if getattr(chat, 'type', None) == 'private':
        return True
    member = await context.bot.get_chat_member(chat.id, user.id)
    return member.status in {'administrator', 'creator', 'owner'}


async def game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the next game or let a chat administrator schedule it."""
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return

    repository = GameScheduleRepository(context.application.bot_data[DATABASE_KEY])
    if not context.args:
        schedule = await repository.get(chat.id)
        text = _message(schedule) if schedule else '📅 Следующая игра пока не назначена.'
        await context.bot.send_message(chat_id=chat.id, text=text, reply_to_message_id=message.id)
        return

    try:
        allowed = await _is_admin(update, context)
    except TelegramError:
        allowed = False
    if not allowed:
        await context.bot.send_message(
            chat_id=chat.id,
            text='⛔ Назначать игру могут только администраторы чата.',
            reply_to_message_id=message.id,
        )
        return

    if len(context.args) not in {2, 3}:
        await context.bot.send_message(chat_id=chat.id, text=USAGE, reply_to_message_id=message.id)
        return
    foundry_url = context.args[2] if len(context.args) == 3 else getenv('FOUNDRY_URL', '')
    if not _valid_url(foundry_url):
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                f'⚠️ Укажи ссылку третьим аргументом или настрой корректный FOUNDRY_URL.\n{USAGE}'
            ),
            reply_to_message_id=message.id,
        )
        return
    try:
        scheduled_at = _parse_date(context.args[0], context.args[1], datetime.now(UTC))
    except ValueError:
        await context.bot.send_message(chat_id=chat.id, text=USAGE, reply_to_message_id=message.id)
        return

    previous = await repository.get(chat.id)
    schedule = GameSchedule(
        chat_id=chat.id,
        scheduled_at=scheduled_at,
        foundry_url=foundry_url,
        message_id=None,
        updated_at=datetime.now(UTC),
    )
    schedule = await repository.save(schedule)
    announcement = await context.bot.send_message(chat_id=chat.id, text=_message(schedule))
    await repository.set_message_id(chat.id, announcement.id)

    try:
        await context.bot.pin_chat_message(
            chat_id=chat.id, message_id=announcement.id, disable_notification=True
        )
    except TelegramError:
        logging.warning('Could not pin game schedule', extra={'chat_id': chat.id})
        await context.bot.send_message(
            chat_id=chat.id,
            text='ℹ️ Расписание сохранено, но закрепить его не удалось. Дайте боту право закреплять сообщения.',
        )
        return
    if previous is not None and previous.message_id is not None:
        try:
            await context.bot.unpin_chat_message(chat_id=chat.id, message_id=previous.message_id)
        except TelegramError:
            logging.warning('Could not unpin previous game schedule', extra={'chat_id': chat.id})
