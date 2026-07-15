import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import BadRequest

import commands
from commands.game_commands import _parse_date, _valid_url
from database import SQLiteDatabase, apply_migrations

MIGRATIONS = Path(__file__).resolve().parent.parent / 'migrations'


def test_parse_date_supports_full_and_short_dates(monkeypatch):
    monkeypatch.setenv('GAME_TIMEZONE', 'UTC')
    now = datetime(2026, 7, 15, 12, tzinfo=UTC)
    assert _parse_date('20.07.2026', '19:00', now) == datetime(2026, 7, 20, 19, tzinfo=UTC)
    assert _parse_date('10.07', '19:00', now) == datetime(2027, 7, 10, 19, tzinfo=UTC)
    assert _valid_url('https://foundry.example/game')
    assert not _valid_url('foundry.example')


def test_game_schedule_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv('GAME_TIMEZONE', 'UTC')
    monkeypatch.setenv('FOUNDRY_URL', 'https://foundry.example/default')

    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'game.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='administrator')),
            pin_chat_message=AsyncMock(),
            unpin_chat_message=AsyncMock(),
        )
        bot.send_message.return_value = SimpleNamespace(id=777)
        context = SimpleNamespace(
            args=['20.07.2026', '19:00'],
            bot=bot,
            application=SimpleNamespace(bot_data={'database': database}),
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-100, type='supergroup'),
            effective_message=SimpleNamespace(id=42),
            effective_user=SimpleNamespace(id=7),
        )
        await commands.game(update, context)
        context.args = []
        await commands.game(update, context)
        await database.close()
        return bot

    bot = asyncio.run(scenario())
    bot.pin_chat_message.assert_awaited_once_with(
        chat_id=-100, message_id=777, disable_notification=True
    )
    assert 'Foundry: https://foundry.example/default' in bot.send_message.await_args.kwargs['text']


def test_game_rejects_non_admin_and_invalid_input(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'invalid.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(id=1)),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')),
            pin_chat_message=AsyncMock(),
            unpin_chat_message=AsyncMock(),
        )
        context = SimpleNamespace(
            args=['bad'], bot=bot, application=SimpleNamespace(bot_data={'database': database})
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-1, type='group'),
            effective_message=SimpleNamespace(id=2),
            effective_user=SimpleNamespace(id=3),
        )
        await commands.game(update, context)
        bot.get_chat_member.return_value.status = 'administrator'
        await commands.game(update, context)
        await database.close()
        return bot

    bot = asyncio.run(scenario())
    assert 'Формат' in bot.send_message.await_args.kwargs['text']
    bot.pin_chat_message.assert_not_awaited()


def test_game_requires_default_or_explicit_foundry_url(tmp_path, monkeypatch):
    monkeypatch.delenv('FOUNDRY_URL', raising=False)

    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'missing-url.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(id=1)),
            get_chat_member=AsyncMock(),
            pin_chat_message=AsyncMock(),
            unpin_chat_message=AsyncMock(),
        )
        context = SimpleNamespace(
            args=['20.07.2026', '19:00'],
            bot=bot,
            application=SimpleNamespace(bot_data={'database': database}),
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=1, type='private'),
            effective_message=SimpleNamespace(id=2),
            effective_user=SimpleNamespace(id=3),
        )
        await commands.game(update, context)
        await database.close()
        return bot

    bot = asyncio.run(scenario())
    assert 'FOUNDRY_URL' in bot.send_message.await_args.kwargs['text']
    bot.pin_chat_message.assert_not_awaited()


def test_game_reports_pin_failure_in_private_chat(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'pin.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(id=9)),
            get_chat_member=AsyncMock(),
            pin_chat_message=AsyncMock(side_effect=BadRequest('no rights')),
            unpin_chat_message=AsyncMock(),
        )
        context = SimpleNamespace(
            args=['20.07.2026', '19:00', 'https://foundry.example'],
            bot=bot,
            application=SimpleNamespace(bot_data={'database': database}),
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=1, type='private'),
            effective_message=SimpleNamespace(id=2),
            effective_user=SimpleNamespace(id=3),
        )
        await commands.game(update, context)
        await database.close()
        return bot

    bot = asyncio.run(scenario())
    assert 'закрепить его не удалось' in bot.send_message.await_args.kwargs['text']
