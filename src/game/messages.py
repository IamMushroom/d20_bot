from os import getenv

from domain import Session
from game.scheduling import game_timezone


def game_message(session: Session, timezone_name: str | None = None) -> str:
    """Format the schedule announcement shared by Core responses and outbox events."""
    assert session.scheduled_at is not None
    assert session.foundry_url is not None
    timezone_name = timezone_name or getenv('D20_BOT_GAME_TIMEZONE', 'Europe/Moscow')
    local = session.scheduled_at.astimezone(game_timezone(timezone_name))
    return (
        f'🎲 Следующая игра: {local:%d.%m.%Y в %H:%M} ({timezone_name})\n'
        f'🏰 Foundry: {session.foundry_url}'
    )
