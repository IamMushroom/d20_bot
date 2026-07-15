import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import BadRequest

import commands
from commands.game_utils import parse_game_date, valid_url
from commands.helpers import CAMPAIGN_SERVICE_KEY, DATABASE_KEY, SESSION_SERVICE_KEY
from core import CoreClientError, ScheduledGame
from database import SQLiteDatabase, apply_migrations
from services import CampaignService, SessionService

MIGRATIONS = Path(__file__).resolve().parent.parent / 'migrations'


def bot_data(database):
    return {
        DATABASE_KEY: database,
        CAMPAIGN_SERVICE_KEY: CampaignService(database),
        SESSION_SERVICE_KEY: SessionService(database),
    }


def test_parse_date_supports_full_and_short_dates(monkeypatch):
    monkeypatch.setenv('D20_BOT_GAME_TIMEZONE', 'UTC')
    now = datetime(2026, 7, 15, 12, tzinfo=UTC)
    assert parse_game_date('20.07.2026', '19:00', now) == datetime(2026, 7, 20, 19, tzinfo=UTC)
    assert parse_game_date('10.07', '19:00', now) == datetime(2027, 7, 10, 19, tzinfo=UTC)
    assert parse_game_date('20.07.', '19:30', now) == datetime(2026, 7, 20, 19, 30, tzinfo=UTC)
    assert valid_url('https://foundry.example/game')
    assert not valid_url('foundry.example')


def test_game_schedule_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv('D20_BOT_GAME_TIMEZONE', 'UTC')
    monkeypatch.setenv('D20_BOT_FOUNDRY_URL', 'https://foundry.example/default')

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
            application=SimpleNamespace(bot_data=bot_data(database)),
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
            args=['bad'], bot=bot, application=SimpleNamespace(bot_data=bot_data(database))
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
    monkeypatch.delenv('D20_BOT_FOUNDRY_URL', raising=False)

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
            application=SimpleNamespace(bot_data=bot_data(database)),
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
    assert 'D20_BOT_FOUNDRY_URL' in bot.send_message.await_args.kwargs['text']
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
            application=SimpleNamespace(bot_data=bot_data(database)),
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


def test_game_url_sets_and_supplies_chat_default(tmp_path, monkeypatch):
    monkeypatch.setenv('D20_BOT_GAME_TIMEZONE', 'UTC')
    monkeypatch.setenv('D20_BOT_FOUNDRY_URL', 'https://foundry.example/environment')

    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'game-url.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(id=15)),
            get_chat_member=AsyncMock(),
            pin_chat_message=AsyncMock(),
            unpin_chat_message=AsyncMock(),
        )
        context = SimpleNamespace(
            args=['https://foundry.example/chat'],
            bot=bot,
            application=SimpleNamespace(bot_data=bot_data(database)),
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=10, type='private'),
            effective_message=SimpleNamespace(id=11),
            effective_user=SimpleNamespace(id=12),
        )
        await commands.game_url(update, context)
        context.args = []
        await commands.game_url(update, context)
        shown_url = bot.send_message.await_args.kwargs['text']
        context.args = ['20.07.2026', '19:00']
        await commands.game(update, context)
        await database.close()
        return bot, shown_url

    bot, shown_url = asyncio.run(scenario())
    assert 'https://foundry.example/chat' in shown_url
    announcement = bot.send_message.await_args_list[-1].kwargs['text']
    assert 'Foundry: https://foundry.example/chat' in announcement


def test_game_command_reschedules_existing_session_and_replaces_pin(tmp_path, monkeypatch):
    monkeypatch.setenv('D20_BOT_GAME_TIMEZONE', 'UTC')
    monkeypatch.setenv('D20_BOT_FOUNDRY_URL', 'https://foundry.example')

    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'reschedule.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(),
            pin_chat_message=AsyncMock(),
            unpin_chat_message=AsyncMock(),
        )
        bot.send_message.side_effect = [SimpleNamespace(id=100), SimpleNamespace(id=200)]
        context = SimpleNamespace(
            args=['01.01.2027', '18:00'],
            bot=bot,
            application=SimpleNamespace(bot_data=bot_data(database)),
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=20, type='private'),
            effective_message=SimpleNamespace(id=21),
            effective_user=SimpleNamespace(id=22),
        )
        await commands.game(update, context)
        context.args = ['02.02.2027', '19:30']
        await commands.game(update, context)
        campaign = await database.fetch_one('SELECT id FROM campaigns WHERE chat_id = ?', (20,))
        assert campaign is not None
        rows = await database.fetch_all(
            'SELECT * FROM sessions WHERE campaign_id = ?', (campaign['id'],)
        )
        await database.close()
        return bot, rows

    bot, rows = asyncio.run(scenario())
    assert len(rows) == 1
    assert rows[0]['scheduled_at'] == '2027-02-02T19:30:00+00:00'
    assert rows[0]['message_id'] == 200
    bot.unpin_chat_message.assert_awaited_once_with(chat_id=20, message_id=100)


def test_game_url_rejects_non_admin_and_invalid_url(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'game-url-errors.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')),
        )
        context = SimpleNamespace(
            args=['https://foundry.example'],
            bot=bot,
            application=SimpleNamespace(bot_data=bot_data(database)),
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-10, type='group'),
            effective_message=SimpleNamespace(id=11),
            effective_user=SimpleNamespace(id=12),
        )
        await commands.game_url(update, context)
        denied = bot.send_message.await_args.kwargs['text']
        bot.get_chat_member.return_value.status = 'administrator'
        context.args = ['not-a-url']
        await commands.game_url(update, context)
        invalid = bot.send_message.await_args.kwargs['text']
        saved = await database.fetch_one('SELECT * FROM game_configs WHERE chat_id = ?', (-10,))
        await database.close()
        return denied, invalid, saved

    denied, invalid, saved = asyncio.run(scenario())
    assert 'только администраторы' in denied
    assert 'Формат' in invalid
    assert saved is None


def test_connected_game_and_url_commands(monkeypatch):
    monkeypatch.setenv('D20_BOT_GAME_TIMEZONE', 'UTC')

    async def scenario():
        core = SimpleNamespace(
            get_game=AsyncMock(return_value='📅 remote game'),
            schedule_game=AsyncMock(return_value=ScheduledGame(5, '🎲 scheduled remotely', 44)),
            set_game_announcement=AsyncMock(),
            get_game_url=AsyncMock(return_value='https://foundry.remote'),
            set_game_url=AsyncMock(),
        )
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(id=55)),
            pin_chat_message=AsyncMock(),
            unpin_chat_message=AsyncMock(),
        )
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={'core_client': core})
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=10, type='private', title='Campaign'),
            effective_message=SimpleNamespace(id=11),
            effective_user=SimpleNamespace(id=12),
        )
        await commands.game(update, context)
        await commands.game_url(update, context)
        context.args = ['20.07.2026', '19:00']
        await commands.game(update, context)
        context.args = ['https://foundry.new']
        await commands.game_url(update, context)
        return core, bot

    core, bot = asyncio.run(scenario())
    core.get_game.assert_awaited_once_with(10)
    core.schedule_game.assert_awaited_once()
    core.set_game_announcement.assert_awaited_once_with(5, 55)
    core.set_game_url.assert_awaited_once_with(10, 'https://foundry.new')
    bot.pin_chat_message.assert_awaited_once()
    bot.unpin_chat_message.assert_awaited_once_with(chat_id=10, message_id=44)


def test_connected_game_reports_core_errors():
    async def scenario():
        core = SimpleNamespace(
            get_game=AsyncMock(side_effect=CoreClientError('offline')),
            schedule_game=AsyncMock(side_effect=CoreClientError('offline')),
            get_game_url=AsyncMock(side_effect=CoreClientError('offline')),
            set_game_url=AsyncMock(side_effect=CoreClientError('offline')),
        )
        bot = SimpleNamespace(send_message=AsyncMock())
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={'core_client': core})
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=10, type='private', title=None),
            effective_message=SimpleNamespace(id=11),
            effective_user=SimpleNamespace(id=12),
        )
        await commands.game(update, context)
        await commands.game_url(update, context)
        context.args = ['20.07.2026', '19:00']
        await commands.game(update, context)
        context.args = ['https://foundry.new']
        await commands.game_url(update, context)
        return bot

    bot = asyncio.run(scenario())
    assert all(
        'Core' in call.kwargs['text'] or 'не задан' in call.kwargs['text']
        for call in bot.send_message.await_args_list
    )
