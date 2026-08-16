from datetime import datetime

from game.scheduling import game_timezone


def game_scheduled_message(
    scheduled_at: datetime,
    timezone_name: str,
    foundry_url: str,
) -> str:
    local = scheduled_at.astimezone(game_timezone(timezone_name))
    return (
        f'🎲 Следующая игра: {local:%d.%m.%Y в %H:%M} ({timezone_name})\n🏰 Foundry: {foundry_url}'
    )


def session_started_message(number: int, title: str | None) -> str:
    title_text = f' — {title}' if title else ''
    return f'▶️ Сессия №{number}{title_text} началась!'


def session_stopped_message(number: int) -> str:
    return f'⏹️ Сессия №{number} завершена.'
