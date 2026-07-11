from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from commands.duality_commands import duality
from commands.help_commands import help_command
from commands.roll_commands import roll, roll20
from commands.timer_commands import timer
from commands.version_commands import version_command

CommandCallback = Callable[..., Coroutine[Any, Any, None]]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    callback: CommandCallback
    menu_description: str
    help_lines: tuple[str, ...]
    aliases: tuple[str, ...] = ()


COMMANDS = (
    CommandSpec(
        name='roll',
        callback=roll,
        menu_description='бросить кубы',
        help_lines=(
            '/roll — бросить d20',
            '/roll 2d6 — обычный бросок',
            '/roll 1d20 + 4 — бросок с модификатором',
            '/roll 2d6 - 1d4 — сложное выражение',
            '/roll 4d6kh3 — оставить три лучших куба',
            '/roll 2d20kl1 — бросок с помехой',
        ),
    ),
    CommandSpec(
        name='roll20',
        callback=roll20,
        menu_description='бросок с усиленными крайними значениями',
        help_lines=('/roll20 d20 — повышенный шанс минимума и максимума',),
        aliases=('rolld20',),
    ),
    CommandSpec(
        name='duality',
        callback=duality,
        menu_description='бросок Daggerheart',
        help_lines=('/duality 5 — бросок Daggerheart с модификатором',),
        aliases=('dgh', 'daggerheart'),
    ),
    CommandSpec(
        name='timer',
        callback=timer,
        menu_description='поставить таймер',
        help_lines=('/timer 60 — таймер в секундах',),
    ),
    CommandSpec(
        name='help',
        callback=help_command,
        menu_description='показать справку',
        help_lines=('/help — эта справка',),
        aliases=('start',),
    ),
    CommandSpec(
        name='version',
        callback=version_command,
        menu_description='показать версию бота',
        help_lines=('/version — версия бота',),
    ),
)

HELP_MESSAGE = '🎲 Команды бота\n\n' + '\n'.join(
    line for command in COMMANDS for line in command.help_lines
)
