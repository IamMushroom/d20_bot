import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

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
        user_data={},
    )


def test_roll_handles_effective_message_without_direct_message():
    update = make_update(text='/roll 1d6')
    context = make_context(('1d6',))

    asyncio.run(commands.roll(update, context))

    sent = context.bot.send_message.await_args.kwargs
    assert sent['chat_id'] == 123
    assert sent['reply_to_message_id'] == 456
    assert sent['text'].startswith('🎲 Бросок:')


def test_roll_without_argument_defaults_to_d20():
    update = make_update(text='/roll')
    context = make_context()

    asyncio.run(commands.roll(update, context))

    sent = context.bot.send_message.await_args.kwargs
    assert sent['text'].startswith('🎲 Бросок:')
    assert '• 1d20:' in sent['text']


def test_roll_rejects_invalid_expression():
    update = make_update(text='/roll 1d6 * 2')
    context = make_context(('1d6', '*', '2'))

    asyncio.run(commands.roll(update, context))

    sent = context.bot.send_message.await_args.kwargs
    assert '⚠️ Не удалось разобрать бросок' in sent['text']
    assert 'Проблемный фрагмент: `*`' in sent['text']


@pytest.mark.parametrize('handler', [commands.roll20, commands.rolld20])
def test_weighted_roll_aliases(handler):
    update = make_update(text='/roll20 d20')
    context = make_context(('d20',))

    asyncio.run(handler(update, context))

    assert context.bot.send_message.await_args.kwargs['text'].startswith('🎲 Бросок:')


def test_reroll_repeats_last_successful_expression(monkeypatch):
    context = make_context(('2d6',))
    monkeypatch.setattr(commands.roll_commands, 'roll_regular', lambda count, _sides: (3,) * count)

    asyncio.run(commands.roll(make_update(text='/roll 2d6'), context))
    context.args = []
    asyncio.run(commands.reroll(make_update(text='/reroll'), context))

    assert '🎲 Бросок: 2d6' in context.bot.send_message.await_args.kwargs['text']
    assert '🎯 Итог: 6' in context.bot.send_message.await_args.kwargs['text']


def test_reroll_reports_when_there_is_nothing_to_repeat():
    context = make_context()

    asyncio.run(commands.reroll(make_update(text='/reroll'), context))

    assert 'Пока нечего перебрасывать' in context.bot.send_message.await_args.kwargs['text']


@pytest.mark.parametrize(
    'handler',
    [commands.roll, commands.timer, commands.duality, commands.help_command],
)
def test_handlers_ignore_update_without_effective_context(handler):
    update = SimpleNamespace(effective_chat=None, effective_message=None)
    context = make_context()

    asyncio.run(handler(update, context))

    context.bot.send_message.assert_not_awaited()


def test_help_sends_command_reference():
    update = make_update(text='/help')
    context = make_context()

    asyncio.run(commands.help_command(update, context))

    assert context.bot.send_message.await_args.kwargs['text'] == commands.BASIC_HELP_MESSAGE


def test_core_required_explains_connected_mode():
    update = make_update(text='/game')
    context = make_context()

    asyncio.run(commands.core_required(update, context))

    sent = context.bot.send_message.await_args.kwargs
    assert sent['reply_to_message_id'] == 456
    assert 'D20_BOT_MODE=connected' in sent['text']


def test_core_required_ignores_incomplete_update():
    context = make_context()

    asyncio.run(
        commands.core_required(
            SimpleNamespace(effective_chat=None, effective_message=None), context
        )
    )

    context.bot.send_message.assert_not_awaited()


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


@pytest.mark.parametrize('args', [('nope',), ('1', '2')])
def test_timer_rejects_non_numeric_or_extra_arguments(args):
    update = make_update(text='/timer ' + ' '.join(args))
    context = make_context(args)

    asyncio.run(commands.timer(update, context))

    context.application.create_task.assert_not_called()
    assert '⚠️' in context.bot.send_message.await_args.kwargs['text']


@pytest.mark.parametrize(
    ('seconds', 'word'),
    [(1, 'секунду'), (2, 'секунды'), (5, 'секунд'), (11, 'секунд'), (21, 'секунду')],
)
def test_seconds_word(seconds, word):
    assert commands.timer_commands._seconds_word(seconds) == word


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


def test_duality_rejects_extra_arguments():
    update = make_update(text='/duality 1 2')
    context = make_context(('1', '2'))

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


def test_error_handler_ignores_non_update():
    context = make_context()
    context.error = None

    asyncio.run(commands.handle_error(object(), context))

    context.bot.send_message.assert_not_awaited()


def test_error_handler_ignores_update_without_chat(monkeypatch):
    class FakeUpdate:
        effective_chat = None
        effective_message = None

    monkeypatch.setattr(commands.error_commands, 'Update', FakeUpdate)
    context = make_context()
    context.error = None

    asyncio.run(commands.handle_error(FakeUpdate(), context))

    context.bot.send_message.assert_not_awaited()
