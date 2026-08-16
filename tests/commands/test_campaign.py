import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import BadRequest

import commands
import commands.member_tags as member_tags
from core import CoreClientError, PlayerRegistration, SessionTransition


def make_update(user_id=7):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100, type='supergroup', title='Campaign'),
        effective_message=SimpleNamespace(id=42, reply_to_message=None),
        effective_user=SimpleNamespace(id=user_id, full_name=f'User {user_id}', is_bot=False),
    )


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
        await commands.session_start(make_update(), context)
        context.args = []
        await commands.session_stop(make_update(), context)
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
        messages = []
        for command in (
            commands.session_start,
            commands.session_start,
            commands.session_start,
            commands.session_stop,
            commands.session_stop,
            commands.session_stop,
        ):
            await command(make_update(), context)
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
        await commands.master(make_update(7), context)
        context.args = ['Tilly']
        bot.get_chat_member.return_value.status = 'member'
        await commands.player(make_update(8), context)
        return core, bot

    core, bot = asyncio.run(scenario())
    core.assign_master.assert_awaited_once_with(-100, 7, 'Campaign')
    core.register_player.assert_awaited_once_with(-100, 8, 'Tilly', 'Campaign')
    bot.set_chat_member_tag.assert_awaited_once_with(chat_id=-100, user_id=8, tag='Tilly')


def test_connected_role_commands_report_errors_and_conflict():
    async def scenario():
        core = SimpleNamespace(
            assign_master=AsyncMock(side_effect=CoreClientError('offline')),
            register_player=AsyncMock(
                side_effect=[PlayerRegistration('master_conflict'), CoreClientError('offline')]
            ),
        )
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='administrator')),
        )
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={'core_client': core})
        )
        update = make_update()
        await commands.master(update, context)
        master_error = bot.send_message.await_args.kwargs['text']
        context.args = ['Hero']
        await commands.player(update, context)
        conflict = bot.send_message.await_args.kwargs['text']
        await commands.player(update, context)
        return master_error, conflict, bot.send_message.await_args.kwargs['text']

    master_error, conflict, player_error = asyncio.run(scenario())
    assert 'Core недоступен' in master_error
    assert 'не может зарегистрироваться' in conflict
    assert 'Core недоступен' in player_error


def test_master_validation_and_bot_reply():
    async def scenario():
        core = SimpleNamespace(assign_master=AsyncMock())
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')),
        )
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={'core_client': core})
        )
        update = make_update()
        await commands.master(update, context)
        denied = bot.send_message.await_args.kwargs['text']
        bot.get_chat_member.return_value.status = 'administrator'
        update.effective_message.reply_to_message = SimpleNamespace(
            from_user=SimpleNamespace(id=99, full_name='Bot', is_bot=True)
        )
        await commands.master(update, context)
        return core, denied, bot.send_message.await_args.kwargs['text']

    core, denied, rejected = asyncio.run(scenario())
    assert 'администраторы' in denied
    assert 'Бота нельзя' in rejected
    core.assign_master.assert_not_awaited()


def test_set_tag_logs_get_chat_member_failure(caplog):
    context = SimpleNamespace(
        bot=SimpleNamespace(
            get_chat_member=AsyncMock(side_effect=BadRequest('member unavailable')),
            set_chat_member_tag=AsyncMock(),
        )
    )
    with caplog.at_level('WARNING'):
        result = asyncio.run(member_tags.set_member_tag(context, -100, 7, 'Мастер'))
    assert result == member_tags.TAG_FAILED
    context.bot.set_chat_member_tag.assert_not_awaited()
    record = next(record for record in caplog.records if record.message.startswith('Could not get'))
    assert record.error_message == 'member unavailable'
