import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import BadRequest

import commands
from core import CoreClientError, ScheduledGame
from game import parse_game_date, valid_url


def update():
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=10, type='private', title='Campaign'),
        effective_message=SimpleNamespace(id=11),
        effective_user=SimpleNamespace(id=12),
    )


def test_parse_date_supports_full_and_short_dates(monkeypatch):
    monkeypatch.setenv('D20_BOT_GAME_TIMEZONE', 'UTC')
    now = datetime(2026, 7, 15, 12, tzinfo=UTC)
    assert parse_game_date('20.07.2026', '19:00', now) == datetime(2026, 7, 20, 19, tzinfo=UTC)
    assert parse_game_date('10.07', '19:00', now) == datetime(2027, 7, 10, 19, tzinfo=UTC)
    assert valid_url('https://foundry.example/game')
    assert not valid_url('foundry.example')


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
        await commands.game(update(), context)
        await commands.game_url(update(), context)
        context.args = ['20.07.2026', '19:00']
        await commands.game(update(), context)
        context.args = ['https://foundry.new']
        await commands.game_url(update(), context)
        return core, bot

    core, bot = asyncio.run(scenario())
    core.get_game.assert_awaited_once_with(10)
    core.schedule_game.assert_awaited_once_with(
        10, 'Campaign', datetime(2026, 7, 20, 19, tzinfo=UTC), None
    )
    core.set_game_announcement.assert_awaited_once_with(5, 55)
    core.set_game_url.assert_awaited_once_with(10, 'https://foundry.new')
    bot.unpin_chat_message.assert_awaited_once_with(chat_id=10, message_id=44)


def test_game_validates_permissions_and_input(monkeypatch):
    monkeypatch.setenv('D20_BOT_GAME_TIMEZONE', 'UTC')

    async def scenario():
        core = SimpleNamespace(schedule_game=AsyncMock())
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')),
        )
        context = SimpleNamespace(
            args=['bad'], bot=bot, application=SimpleNamespace(bot_data={'core_client': core})
        )
        group = update()
        group.effective_chat.type = 'group'
        await commands.game(group, context)
        denied = bot.send_message.await_args.kwargs['text']
        bot.get_chat_member.return_value.status = 'administrator'
        await commands.game(group, context)
        invalid = bot.send_message.await_args.kwargs['text']
        context.args = ['20.07.2026', '19:00', 'bad-url']
        await commands.game(group, context)
        return core, denied, invalid, bot.send_message.await_args.kwargs['text']

    core, denied, invalid, bad_url = asyncio.run(scenario())
    assert 'администраторы' in denied
    assert 'Формат' in invalid
    assert 'D20_BOT_FOUNDRY_URL' in bad_url
    core.schedule_game.assert_not_awaited()


def test_game_handles_core_and_pin_errors(monkeypatch):
    monkeypatch.setenv('D20_BOT_GAME_TIMEZONE', 'UTC')

    async def scenario():
        core = SimpleNamespace(
            get_game=AsyncMock(side_effect=CoreClientError('offline')),
            schedule_game=AsyncMock(
                side_effect=[CoreClientError('offline'), ScheduledGame(5, 'scheduled', None)]
            ),
            set_game_announcement=AsyncMock(),
        )
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(id=55)),
            pin_chat_message=AsyncMock(side_effect=BadRequest('no rights')),
        )
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={'core_client': core})
        )
        await commands.game(update(), context)
        unavailable_get = bot.send_message.await_args.kwargs['text']
        context.args = ['20.07.2026', '19:00']
        await commands.game(update(), context)
        unavailable_set = bot.send_message.await_args.kwargs['text']
        await commands.game(update(), context)
        return unavailable_get, unavailable_set, bot.send_message.await_args.kwargs['text']

    unavailable_get, unavailable_set, pin_error = asyncio.run(scenario())
    assert 'Core недоступен' in unavailable_get
    assert 'Core недоступен' in unavailable_set
    assert 'закрепить' in pin_error


def test_game_logs_core_announcement_and_previous_unpin_errors(monkeypatch, caplog):
    monkeypatch.setenv('D20_BOT_GAME_TIMEZONE', 'UTC')

    async def scenario():
        core = SimpleNamespace(
            schedule_game=AsyncMock(return_value=ScheduledGame(5, 'scheduled', 44)),
            set_game_announcement=AsyncMock(side_effect=CoreClientError('offline')),
        )
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(id=55)),
            pin_chat_message=AsyncMock(),
            unpin_chat_message=AsyncMock(side_effect=BadRequest('not pinned')),
        )
        context = SimpleNamespace(
            args=['20.07.2026', '19:00'],
            bot=bot,
            application=SimpleNamespace(bot_data={'core_client': core}),
        )
        await commands.game(update(), context)

    with caplog.at_level('WARNING'):
        asyncio.run(scenario())
    assert 'Could not save game announcement in Core' in caplog.messages
    assert 'Could not unpin previous game schedule' in caplog.messages


def test_game_url_validation_and_core_errors():
    async def scenario():
        core = SimpleNamespace(
            get_game_url=AsyncMock(side_effect=CoreClientError('offline')),
            set_game_url=AsyncMock(side_effect=CoreClientError('offline')),
        )
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='administrator')),
        )
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={'core_client': core})
        )
        await commands.game_url(update(), context)
        missing = bot.send_message.await_args.kwargs['text']
        context.args = ['bad']
        await commands.game_url(update(), context)
        invalid = bot.send_message.await_args.kwargs['text']
        context.args = ['https://foundry.example']
        await commands.game_url(update(), context)
        return missing, invalid, bot.send_message.await_args.kwargs['text']

    missing, invalid, failed = asyncio.run(scenario())
    assert 'не задан' in missing
    assert 'Формат' in invalid
    assert 'Core недоступен' in failed
