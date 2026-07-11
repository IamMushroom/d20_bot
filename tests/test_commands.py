import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import commands


def make_update(chat_id=123, message_id=456, text='/command'):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=SimpleNamespace(id=message_id, text=text),
    )


def make_context(args=()):
    return SimpleNamespace(
        args=list(args),
        bot=SimpleNamespace(send_message=AsyncMock()),
        application=SimpleNamespace(create_task=Mock()),
    )


def test_roll_handles_effective_message_without_direct_message():
    update = make_update(text='/roll 1d6')
    context = make_context(('1d6',))

    asyncio.run(commands.roll(update, context))

    sent = context.bot.send_message.await_args.kwargs
    assert sent['chat_id'] == 123
    assert sent['reply_to_message_id'] == 456
    assert sent['text'].startswith('🎲 Итог:')


def test_help_sends_command_reference():
    update = make_update(text='/help')
    context = make_context()

    asyncio.run(commands.help_command(update, context))

    assert context.bot.send_message.await_args.kwargs['text'] == commands.HELP_MESSAGE


def test_timer_creates_independent_background_tasks():
    context = make_context(('10',))
    first_update = make_update(message_id=1, text='/timer 10')
    second_update = make_update(message_id=2, text='/timer 10')

    asyncio.run(commands.timer(first_update, context))
    asyncio.run(commands.timer(second_update, context))

    assert context.application.create_task.call_count == 2
    first_call, second_call = context.application.create_task.call_args_list
    assert first_call.kwargs['name'] == 'timer-123:1'
    assert second_call.kwargs['name'] == 'timer-123:2'

    # The fake application does not schedule coroutines, so close them explicitly.
    first_call.args[0].close()
    second_call.args[0].close()


def test_timer_rejects_invalid_argument():
    update = make_update(text='/timer -1')
    context = make_context(('-1',))

    asyncio.run(commands.timer(update, context))

    context.application.create_task.assert_not_called()
    assert '⚠️' in context.bot.send_message.await_args.kwargs['text']


def test_finish_timer_sends_notification_and_logs_completion(monkeypatch, caplog):
    context = make_context()
    monkeypatch.setattr(commands.timer_commands, 'sleep', AsyncMock())

    with caplog.at_level(logging.INFO):
        asyncio.run(commands._finish_timer(context, 123, 456, 10, '123:456'))

    context.bot.send_message.assert_awaited_once_with(
        chat_id=123,
        text='⏰ Время истекло!',
        reply_to_message_id=456,
    )
    assert 'Timer completed' in caplog.messages


def test_duality_passes_modifier_to_roll(monkeypatch):
    update = make_update(text='/duality 5')
    context = make_context(('5',))
    dgh = Mock(return_value='duality result')
    monkeypatch.setattr(commands.duality_commands, 'dgh', dgh)

    asyncio.run(commands.duality(update, context))

    dgh.assert_called_once_with(5)
    assert context.bot.send_message.await_args.kwargs['text'] == 'duality result'


def test_duality_rejects_invalid_modifier():
    update = make_update(text='/duality nope')
    context = make_context(('nope',))

    asyncio.run(commands.duality(update, context))

    assert '⚠️' in context.bot.send_message.await_args.kwargs['text']


def test_error_handler_supports_edited_update(monkeypatch, caplog):
    class FakeUpdate:
        effective_chat = SimpleNamespace(id=123)
        effective_message = SimpleNamespace(id=456)

    monkeypatch.setattr(commands.error_commands, 'Update', FakeUpdate)
    context = make_context()
    context.error = RuntimeError('handler failed')

    with caplog.at_level(logging.ERROR):
        asyncio.run(commands.handle_error(FakeUpdate(), context))

    assert 'Unhandled exception while processing Telegram update' in caplog.messages
    assert context.bot.send_message.await_args.kwargs['reply_to_message_id'] == 456
