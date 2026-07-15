import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import BadRequest

import commands
from database import SQLiteDatabase, apply_migrations
from database.repositories import CampaignRepository, SessionRepository

MIGRATIONS = Path(__file__).resolve().parent.parent / 'migrations'


def make_update(user_id=7, *, status='administrator'):
    user = SimpleNamespace(id=user_id, full_name=f'User {user_id}', is_bot=False)
    message = SimpleNamespace(id=42, reply_to_message=None)
    return (
        SimpleNamespace(
            effective_chat=SimpleNamespace(id=-100, type='supergroup', title='Campaign'),
            effective_message=message,
            effective_user=user,
        ),
        status,
    )


def test_master_player_and_session_lifecycle(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'campaign.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='administrator')),
            set_chat_member_tag=AsyncMock(),
            unpin_chat_message=AsyncMock(),
        )
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={'database': database})
        )
        master_update, _ = make_update(7)
        await commands.master(master_update, context)

        player_update, _ = make_update(8)
        context.args = ['Тилли']
        await commands.player(player_update, context)

        campaign = await CampaignRepository(database).get_by_chat_id(-100)
        assert campaign is not None
        planned = await SessionRepository(database).schedule(
            campaign.id,
            datetime(2026, 7, 20, 16, tzinfo=UTC),
            'https://foundry.example',
        )
        await SessionRepository(database).set_message_id(planned.id, 99)

        context.args = ['Башня']
        await commands.session_start(master_update, context)
        context.args = []
        await commands.session_stop(master_update, context)
        sessions = await SessionRepository(database).list(campaign.id)
        await database.close()
        return bot, campaign, sessions

    bot, campaign, sessions = asyncio.run(scenario())
    assert campaign.master_user_id == 7
    assert bot.set_chat_member_tag.await_args_list[0].kwargs['tag'] == 'Мастер'
    assert bot.set_chat_member_tag.await_args_list[1].kwargs['tag'] == 'Тилли'
    bot.unpin_chat_message.assert_awaited_once_with(chat_id=-100, message_id=99)
    assert sessions[0].title == 'Башня'
    assert sessions[0].finished_at is not None
    assert 'завершена' in bot.send_message.await_args.kwargs['text']


def test_role_and_session_validation_messages(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'validation.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')),
            set_chat_member_tag=AsyncMock(side_effect=BadRequest('no rights')),
            unpin_chat_message=AsyncMock(),
        )
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={'database': database})
        )
        update, _ = make_update(10)
        await commands.master(update, context)
        non_admin_text = bot.send_message.await_args.kwargs['text']

        context.args = ['x' * 17]
        await commands.player(update, context)
        invalid_player_text = bot.send_message.await_args.kwargs['text']

        context.args = []
        await commands.session_start(update, context)
        non_master_text = bot.send_message.await_args.kwargs['text']

        bot.get_chat_member.return_value.status = 'administrator'
        await commands.master(update, context)
        tag_warning = bot.send_message.await_args.kwargs['text']
        await commands.session_stop(update, context)
        no_active_text = bot.send_message.await_args.kwargs['text']
        await database.close()
        return non_admin_text, invalid_player_text, non_master_text, tag_warning, no_active_text

    messages = asyncio.run(scenario())
    assert 'администраторы' in messages[0]
    assert 'до 16' in messages[1]
    assert 'назначенный мастер' in messages[2]
    assert 'тег установить не удалось' in messages[3]
    assert 'Активной сессии' in messages[4]


def test_master_rejects_bot_selected_by_reply(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'bot-master.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='administrator')),
            set_chat_member_tag=AsyncMock(),
        )
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={'database': database})
        )
        update, _ = make_update(7)
        update.effective_message.reply_to_message = SimpleNamespace(
            from_user=SimpleNamespace(id=99, full_name='Some Bot', is_bot=True)
        )
        await commands.master(update, context)
        campaign = await CampaignRepository(database).get_by_chat_id(-100)
        await database.close()
        return bot, campaign

    bot, campaign = asyncio.run(scenario())
    assert 'Бота нельзя' in bot.send_message.await_args.kwargs['text']
    assert campaign is None
    bot.set_chat_member_tag.assert_not_awaited()


def test_master_cannot_register_as_player(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'master-player.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        await CampaignRepository(database).set_master(-100, 7, 'Campaign')
        bot = SimpleNamespace(send_message=AsyncMock(), set_chat_member_tag=AsyncMock())
        context = SimpleNamespace(
            args=['Герой'], bot=bot, application=SimpleNamespace(bot_data={'database': database})
        )
        update, _ = make_update(7)
        await commands.player(update, context)
        character = await database.fetch_one(
            'SELECT * FROM characters WHERE telegram_user_id = ?', (7,)
        )
        await database.close()
        return bot, character

    bot, character = asyncio.run(scenario())
    assert 'не может зарегистрироваться игроком' in bot.send_message.await_args.kwargs['text']
    assert character is None
    bot.set_chat_member_tag.assert_not_awaited()


def test_session_start_reports_existing_active_session(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'active.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        campaign = await CampaignRepository(database).set_master(-100, 7, 'Campaign')
        await SessionRepository(database).start(campaign.id, 'Already running')
        bot = SimpleNamespace(send_message=AsyncMock(), unpin_chat_message=AsyncMock())
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={'database': database})
        )
        update, _ = make_update(7)
        await commands.session_start(update, context)
        sessions = await SessionRepository(database).list(campaign.id)
        await database.close()
        return bot, sessions

    bot, sessions = asyncio.run(scenario())
    assert 'уже идёт активная сессия' in bot.send_message.await_args.kwargs['text']
    assert len(sessions) == 1


def test_session_start_survives_unpin_failure(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'unpin.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        campaign = await CampaignRepository(database).set_master(-100, 7, 'Campaign')
        sessions = SessionRepository(database)
        planned = await sessions.schedule(
            campaign.id,
            datetime(2026, 7, 20, 16, tzinfo=UTC),
            'https://foundry.example',
        )
        await sessions.set_message_id(planned.id, 55)
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            unpin_chat_message=AsyncMock(side_effect=BadRequest('cannot unpin')),
        )
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={'database': database})
        )
        update, _ = make_update(7)
        await commands.session_start(update, context)
        active = await sessions.get_active(campaign.id)
        await database.close()
        return bot, active

    bot, active = asyncio.run(scenario())
    assert active is not None
    assert 'началась' in bot.send_message.await_args.kwargs['text']
