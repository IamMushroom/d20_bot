import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import BadRequest

from commands.admin_commands import CORE_CLIENT_KEY, admin, web_register, web_url
from core import CoreClientError


def test_admin_commands_ignore_updates_without_chat():
    async def scenario():
        update = SimpleNamespace(effective_chat=None, effective_message=None, effective_user=None)
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
        await admin(update, context)
        await web_url(update, context)
        return context.bot

    bot = asyncio.run(scenario())
    bot.send_message.assert_not_awaited()


def test_web_register_command_uses_core():
    async def scenario():
        bot = SimpleNamespace(send_message=AsyncMock())
        client = SimpleNamespace(create_registration_code=AsyncMock(return_value='ABCD-EFGH-JKLM'))
        update = SimpleNamespace(
            effective_message=SimpleNamespace(id=1, chat_id=-100),
            effective_user=SimpleNamespace(id=7),
        )
        context = SimpleNamespace(
            bot=bot, application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: client})
        )
        await web_register(update, context)
        return bot, client

    bot, client = asyncio.run(scenario())
    client.create_registration_code.assert_awaited_once_with(7)
    assert bot.send_message.await_count == 2
    assert 'ABCD-EFGH-JKLM' in bot.send_message.await_args_list[0].kwargs['text']


def test_web_register_command_handles_missing_context_and_core_error():
    async def scenario():
        bot = SimpleNamespace(send_message=AsyncMock())
        empty = SimpleNamespace(effective_message=None, effective_user=None)
        context = SimpleNamespace(bot=bot, application=SimpleNamespace(bot_data={}))
        await web_register(empty, context)
        update = SimpleNamespace(
            effective_message=SimpleNamespace(id=1, chat_id=7),
            effective_user=SimpleNamespace(id=7),
        )
        context.application.bot_data[CORE_CLIENT_KEY] = SimpleNamespace(
            create_registration_code=AsyncMock(side_effect=CoreClientError('offline'))
        )
        await web_register(update, context)
        return bot

    bot = asyncio.run(scenario())
    bot.send_message.assert_awaited_once()


def test_admin_command_reports_private_message_failure():
    async def scenario():
        core = SimpleNamespace(
            create_admin_link=AsyncMock(return_value='https://d20.example/login')
        )
        bot = SimpleNamespace(send_message=AsyncMock())
        bot.send_message.side_effect = [BadRequest('blocked'), SimpleNamespace(id=1)]
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: core}),
            bot=bot,
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-100, title='Campaign'),
            effective_message=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=7),
        )
        await admin(update, context)
        return bot.send_message.await_args.kwargs['text']

    assert 'личные сообщения' in asyncio.run(scenario())


def test_admin_command_uses_connected_core_client():
    client = SimpleNamespace(create_admin_link=AsyncMock(return_value='https://d20.example/login'))
    bot = SimpleNamespace(send_message=AsyncMock())
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: client}), bot=bot
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100, title='Campaign'),
        effective_message=SimpleNamespace(id=10),
        effective_user=SimpleNamespace(id=7),
    )

    asyncio.run(admin(update, context))

    client.create_admin_link.assert_awaited_once_with(-100, 7, 'Campaign')
    assert bot.send_message.await_args.kwargs['chat_id'] == 7


def test_admin_command_reports_connected_core_error(caplog):
    client = SimpleNamespace(
        create_admin_link=AsyncMock(side_effect=CoreClientError('unavailable'))
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: client}), bot=bot
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100, title=None),
        effective_message=SimpleNamespace(id=10),
        effective_user=SimpleNamespace(id=7),
    )

    with caplog.at_level('WARNING'):
        asyncio.run(admin(update, context))

    assert bot.send_message.await_args.kwargs['chat_id'] == -100
    assert 'Core недоступен' in bot.send_message.await_args.kwargs['text']
    record = caplog.records[-1]
    assert record.core_path == '/internal/campaigns/-100/admin-links'
    assert record.error_type == 'CoreClientError'
    assert record.error_message == 'unavailable'


def test_admin_command_explains_private_chat_usage():
    client = SimpleNamespace(create_admin_link=AsyncMock())
    bot = SimpleNamespace(send_message=AsyncMock())
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: client}), bot=bot
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=7, title=None, type='private'),
        effective_message=SimpleNamespace(id=10),
        effective_user=SimpleNamespace(id=7),
    )

    asyncio.run(admin(update, context))

    client.create_admin_link.assert_not_awaited()
    assert 'в группе кампании' in bot.send_message.await_args.kwargs['text']


def test_web_url_command_uses_connected_core():
    async def scenario():
        core = SimpleNamespace(
            get_web_url=AsyncMock(return_value='https://d20.example'),
            set_web_url=AsyncMock(),
        )
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='administrator')),
        )
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: core})
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-100, type='group'),
            effective_message=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=7),
        )
        await web_url(update, context)
        context.args = ['https://new.example/']
        await web_url(update, context)
        return core, bot

    core, bot = asyncio.run(scenario())
    core.get_web_url.assert_awaited_once_with(-100)
    core.set_web_url.assert_awaited_once_with(-100, 'https://new.example')
    assert 'сохранён' in bot.send_message.await_args.kwargs['text']


def test_web_url_command_reports_connected_core_error():
    async def scenario():
        core = SimpleNamespace(
            get_web_url=AsyncMock(side_effect=CoreClientError('offline')),
            set_web_url=AsyncMock(side_effect=CoreClientError('offline')),
        )
        bot = SimpleNamespace(send_message=AsyncMock())
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: core})
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=1, type='private'),
            effective_message=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=7),
        )
        await web_url(update, context)
        missing = bot.send_message.await_args.kwargs['text']
        context.args = ['https://new.example']
        await web_url(update, context)
        failed = bot.send_message.await_args.kwargs['text']
        return missing, failed

    missing, failed = asyncio.run(scenario())
    assert 'не задан' in missing
    assert 'Core недоступен' in failed


def test_web_url_command_validates_admin_and_url():
    async def scenario():
        core = SimpleNamespace(set_web_url=AsyncMock())
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')),
        )
        context = SimpleNamespace(
            args=['https://new.example'],
            bot=bot,
            application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: core}),
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-100, type='group'),
            effective_message=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=7),
        )
        await web_url(update, context)
        denied = bot.send_message.await_args.kwargs['text']
        bot.get_chat_member.return_value.status = 'administrator'
        context.args = ['not-a-url']
        await web_url(update, context)
        return core, denied, bot.send_message.await_args.kwargs['text']

    core, denied, invalid = asyncio.run(scenario())
    assert denied != invalid
    assert '/web_url' in invalid
    core.set_web_url.assert_not_awaited()
