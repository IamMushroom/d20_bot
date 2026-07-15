import logging
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from os import getenv
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from database.models import Session


def game_timezone() -> tzinfo:
    name = getenv('D20_BOT_GAME_TIMEZONE', 'Europe/Moscow')
    if name == 'UTC':
        return UTC
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == 'Europe/Moscow':
            return timezone(timedelta(hours=3), name='Europe/Moscow')
        logging.error(
            'Unknown D20_BOT_GAME_TIMEZONE, falling back to UTC', extra={'timezone': name}
        )
        return UTC


def parse_game_date(date_text: str, time_text: str, now: datetime) -> datetime:
    timezone = game_timezone()
    now = now.astimezone(timezone)
    date_text = date_text.rstrip('.')
    if date_text.count('.') == 2:
        parsed = datetime.strptime(f'{date_text} {time_text}', '%d.%m.%Y %H:%M')
    else:
        parsed = datetime.strptime(f'{date_text}.{now.year} {time_text}', '%d.%m.%Y %H:%M')
        if parsed.replace(tzinfo=timezone) <= now:
            parsed = parsed.replace(year=now.year + 1)
    return parsed.replace(tzinfo=timezone).astimezone(UTC)


def valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {'http', 'https'} and bool(parsed.netloc)


def game_message(session: Session) -> str:
    assert session.scheduled_at is not None
    assert session.foundry_url is not None
    local = session.scheduled_at.astimezone(game_timezone())
    timezone_name = getenv('D20_BOT_GAME_TIMEZONE', 'Europe/Moscow')
    return (
        f'🎲 Следующая игра: {local:%d.%m.%Y в %H:%M} ({timezone_name})\n'
        f'🏰 Foundry: {session.foundry_url}'
    )
