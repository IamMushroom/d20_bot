import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import commands
from run import set_bot_commands


def test_command_names_and_aliases_are_unique():
    names = [name for command in commands.COMMANDS for name in (command.name, *command.aliases)]

    assert names
    assert len(names) == len(set(names))
    assert all(re.fullmatch(r'[a-z0-9_]{1,32}', name) for name in names)


def test_help_message_is_built_from_registry():
    for command in commands.COMMANDS:
        for line in command.help_lines:
            assert line in commands.HELP_MESSAGE


def test_set_bot_commands_uses_registry():
    application = SimpleNamespace(bot=SimpleNamespace(set_my_commands=AsyncMock()))

    asyncio.run(set_bot_commands(application))

    registered = application.bot.set_my_commands.await_args.args[0]
    assert [command.command for command in registered] == [
        command.name for command in commands.COMMANDS
    ]
    assert [command.description for command in registered] == [
        command.menu_description for command in commands.COMMANDS
    ]
