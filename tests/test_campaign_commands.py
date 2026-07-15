import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import BadRequest

import commands
import commands.member_tags as member_tags
from commands.helpers import CAMPAIGN_SERVICE_KEY, DATABASE_KEY, SESSION_SERVICE_KEY
from core import CoreClientError, PlayerRegistration, SessionTransition
from database import SQLiteDatabase, apply_migrations
from database.repositories import CampaignRepository, SessionRepository
from services import CampaignService, SessionService

MIGRATIONS = Path(__file__).resolve().parent.parent / 'migrations'


def bot_data(database):
    return {
        DATABASE_KEY: database,
        CAMPAIGN_SERVICE_KEY: CampaignService(database),
        SESSION_SERVICE_KEY: SessionService(database),
    }


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
            get_chat_member=AsyncMock(
                side_effect=lambda _chat_id, user_id: SimpleNamespace(
                    status='administrator' if user_id == 7 else 'member'
                )
            ),
            set_chat_member_tag=AsyncMock(),
            unpin_chat_message=AsyncMock(),
        )
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data=bot_data(database))
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
    bot.set_chat_member_tag.assert_awaited_once()
    assert bot.set_chat_member_tag.await_args.kwargs['tag'] == 'Тилли'
    bot.unpin_chat_message.assert_awaited_once_with(chat_id=-100, message_id=99)
    assert sessions[0].title == 'Башня'
    assert sessions[0].finished_at is not None
    assert 'завершена' in bot.send_message.await_args.kwargs['text']


def test_role_and_session_validation_messages(tmp_path, caplog):
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
            args=[], bot=bot, application=SimpleNamespace(bot_data=bot_data(database))
        )
        update, _ = make_update(10)
        await commands.master(update, context)
        non_admin_text = bot.send_message.await_args.kwargs['text']

        context.args = ['x' * 17]
        await commands.player(update, context)
        invalid_player_text = bot.send_message.await_args.kwargs['text']

        context.args = ['Тилли']
        await commands.player(update, context)
        player_tag_warning = bot.send_message.await_args.kwargs['text']

        context.args = []
        await commands.session_start(update, context)
        non_master_text = bot.send_message.await_args.kwargs['text']

        bot.get_chat_member.return_value.status = 'administrator'
        await commands.master(update, context)
        master_text = bot.send_message.await_args.kwargs['text']
        await commands.session_stop(update, context)
        no_active_text = bot.send_message.await_args.kwargs['text']
        await database.close()
        return (
            non_admin_text,
            invalid_player_text,
            player_tag_warning,
            non_master_text,
            master_text,
            no_active_text,
        )

    with caplog.at_level('WARNING'):
        messages = asyncio.run(scenario())
    assert 'администраторы' in messages[0]
    assert 'до 16' in messages[1]
    assert 'тег установить не удалось' in messages[2]
    assert 'назначенный мастер' in messages[3]
    assert messages[4] == '🎭 Мастер кампании назначен: User 10'
    assert 'Активной сессии' in messages[5]
    tag_record = next(
        record for record in caplog.records if getattr(record, 'telegram_method', None)
    )
    assert tag_record.telegram_method == 'setChatMemberTag'
    assert tag_record.error_type == 'BadRequest'
    assert tag_record.error_message == 'no rights'
    assert tag_record.tag == 'Тилли'
    assert tag_record.exc_info is not None


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
            args=[], bot=bot, application=SimpleNamespace(bot_data=bot_data(database))
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
            args=['Герой'], bot=bot, application=SimpleNamespace(bot_data=bot_data(database))
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
            args=[], bot=bot, application=SimpleNamespace(bot_data=bot_data(database))
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
            args=[], bot=bot, application=SimpleNamespace(bot_data=bot_data(database))
        )
        update, _ = make_update(7)
        await commands.session_start(update, context)
        active = await sessions.get_active(campaign.id)
        await database.close()
        return bot, active

    bot, active = asyncio.run(scenario())
    assert active is not None
    assert 'началась' in bot.send_message.await_args.kwargs['text']


def test_set_tag_logs_get_chat_member_failure(caplog):
    async def scenario():
        context = SimpleNamespace(
            bot=SimpleNamespace(
                get_chat_member=AsyncMock(side_effect=BadRequest('member unavailable')),
                set_chat_member_tag=AsyncMock(),
            )
        )
        result = await member_tags.set_member_tag(context, -100, 7, 'Мастер')
        return context.bot, result

    with caplog.at_level('WARNING'):
        bot, result = asyncio.run(scenario())

    assert result == member_tags.TAG_FAILED
    bot.set_chat_member_tag.assert_not_awaited()
    record = next(record for record in caplog.records if record.message.startswith('Could not get'))
    assert record.telegram_method == 'getChatMember'
    assert record.error_type == 'BadRequest'
    assert record.error_message == 'member unavailable'
    assert record.exc_info is not None


def test_private_chat_saves_master_without_attempting_tag(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'private-master.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        bot = SimpleNamespace(send_message=AsyncMock(), set_chat_member_tag=AsyncMock())
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data=bot_data(database))
        )
        update, _ = make_update(7)
        update.effective_chat.type = 'private'
        await commands.master(update, context)
        campaign = await CampaignRepository(database).get_by_chat_id(-100)
        await database.close()
        return bot, campaign

    bot, campaign = asyncio.run(scenario())
    assert campaign is not None and campaign.master_user_id == 7
    assert bot.send_message.await_args.kwargs['text'] == '🎭 Мастер кампании назначен: User 7'
    bot.set_chat_member_tag.assert_not_awaited()


def test_connected_session_lifecycle():
    async def scenario():
        core = SimpleNamespace(
            start_session=AsyncMock(return_value=SessionTransition('started', 3, 'Tower', 99)),
            stop_session=AsyncMock(return_value=SessionTransition('stopped', 3)),
        )
        bot = SimpleNamespace(send_message=AsyncMock(), unpin_chat_message=AsyncMock())
        context = SimpleNamespace(
            args=['Tower'], bot=bot, application=SimpleNamespace(bot_data={'core_client': core})
        )
        update, _ = make_update(7)
        await commands.session_start(update, context)
        context.args = []
        await commands.session_stop(update, context)
        return core, bot

    core, bot = asyncio.run(scenario())
    core.start_session.assert_awaited_once_with(-100, 7, 'Tower')
    core.stop_session.assert_awaited_once_with(-100, 7)
    bot.unpin_chat_message.assert_awaited_once_with(chat_id=-100, message_id=99)
    assert 'завершена' in bot.send_message.await_args.kwargs['text']


def test_connected_session_statuses_and_errors():
    async def scenario():
        core = SimpleNamespace(
            start_session=AsyncMock(
                side_effect=[
                    SessionTransition('forbidden'),
                    SessionTransition('already_active'),
                    CoreClientError('offline'),
                ]
            ),
            stop_session=AsyncMock(
                side_effect=[
                    SessionTransition('forbidden'),
                    SessionTransition('no_active_session'),
                    CoreClientError('offline'),
                ]
            ),
        )
        bot = SimpleNamespace(send_message=AsyncMock())
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={'core_client': core})
        )
        update, _ = make_update(7)
        messages = []
        for command in (
            commands.session_start,
            commands.session_start,
            commands.session_start,
            commands.session_stop,
            commands.session_stop,
            commands.session_stop,
        ):
            await command(update, context)
            messages.append(bot.send_message.await_args.kwargs['text'])
        return messages

    messages = asyncio.run(scenario())
    assert 'назначенный мастер' in messages[0]
    assert 'уже идёт' in messages[1]
    assert 'Core недоступен' in messages[2]
    assert 'назначенный мастер' in messages[3]
    assert 'Активной сессии' in messages[4]
    assert 'Core недоступен' in messages[5]


def test_connected_role_commands():
    async def scenario():
        core = SimpleNamespace(
            assign_master=AsyncMock(),
            register_player=AsyncMock(return_value=PlayerRegistration('registered', 'Tilly')),
        )
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='administrator')),
            set_chat_member_tag=AsyncMock(),
        )
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={'core_client': core})
        )
        master_update, _ = make_update(7)
        await commands.master(master_update, context)
        player_update, _ = make_update(8)
        context.args = ['Tilly']
        bot.get_chat_member.return_value.status = 'member'
        await commands.player(player_update, context)
        return core, bot

    core, bot = asyncio.run(scenario())
    core.assign_master.assert_awaited_once_with(-100, 7, 'Campaign')
    core.register_player.assert_awaited_once_with(-100, 8, 'Tilly', 'Campaign')
    bot.set_chat_member_tag.assert_awaited_once_with(chat_id=-100, user_id=8, tag='Tilly')


def test_connected_role_commands_report_core_errors_and_conflict():
    async def scenario():
        core = SimpleNamespace(
            assign_master=AsyncMock(side_effect=CoreClientError('offline')),
            register_player=AsyncMock(
                side_effect=[
                    PlayerRegistration('master_conflict'),
                    CoreClientError('offline'),
                ]
            ),
        )
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='administrator')),
        )
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={'core_client': core})
        )
        update, _ = make_update(7)
        await commands.master(update, context)
        master_error = bot.send_message.await_args.kwargs['text']
        context.args = ['Hero']
        await commands.player(update, context)
        conflict = bot.send_message.await_args.kwargs['text']
        await commands.player(update, context)
        player_error = bot.send_message.await_args.kwargs['text']
        return master_error, conflict, player_error

    master_error, conflict, player_error = asyncio.run(scenario())
    assert 'Core недоступен' in master_error
    assert 'не может зарегистрироваться' in conflict
    assert 'Core недоступен' in player_error
