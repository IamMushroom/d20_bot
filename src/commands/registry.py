from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from commands.admin_commands import admin, web_url
from commands.duality_commands import duality
from commands.game_config_commands import game_url
from commands.game_schedule_commands import game
from commands.help_commands import help_command
from commands.role_commands import master, player
from commands.roll_commands import roll, roll20
from commands.session_commands import session_start, session_stop
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
    show_in_menu: bool = False
    requires_core: bool = True


COMMANDS = (
    CommandSpec(
        name='admin',
        callback=admin,
        menu_description='открыть панель мастера',
        help_lines=('/admin — получить в личку ссылку на веб-панель',),
    ),
    CommandSpec(
        name='web_url',
        callback=web_url,
        menu_description='показать или задать URL панели',
        help_lines=(
            '/web_url — показать адрес панели',
            '/web_url https://d20.example — сохранить адрес (для администраторов)',
        ),
    ),
    CommandSpec(
        name='master',
        callback=master,
        menu_description='назначить мастера кампании',
        help_lines=('/master — назначить себя или автора сообщения через reply мастером',),
    ),
    CommandSpec(
        name='player',
        callback=player,
        menu_description='зарегистрировать персонажа игрока',
        help_lines=('/player <имя> — зарегистрироваться и получить тег персонажа',),
        aliases=('character',),
    ),
    CommandSpec(
        name='session_start',
        callback=session_start,
        menu_description='начать игровую сессию',
        help_lines=('/session_start [название] — начать сессию (для мастера)',),
    ),
    CommandSpec(
        name='session_stop',
        callback=session_stop,
        menu_description='завершить игровую сессию',
        help_lines=('/session_stop — завершить активную сессию (для мастера)',),
        aliases=('session_finish',),
    ),
    CommandSpec(
        name='game',
        callback=game,
        menu_description='показать или назначить следующую игру',
        help_lines=(
            '/game — показать следующую игру',
            '/game 20.07 19:00 [ссылка] — назначить игру (для администраторов)',
        ),
    ),
    CommandSpec(
        name='game_url',
        callback=game_url,
        menu_description='показать или задать адрес Foundry',
        help_lines=(
            '/game_url — показать адрес Foundry по умолчанию',
            '/game_url https://foundry.example — сохранить адрес (для администраторов)',
        ),
    ),
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
        show_in_menu=True,
        requires_core=False,
    ),
    CommandSpec(
        name='roll20',
        callback=roll20,
        menu_description='бросок с усиленными крайними значениями',
        help_lines=('/roll20 d20 — повышенный шанс минимума и максимума',),
        aliases=('rolld20',),
        show_in_menu=True,
        requires_core=False,
    ),
    CommandSpec(
        name='duality',
        callback=duality,
        menu_description='бросок Daggerheart',
        help_lines=('/duality 5 — бросок Daggerheart с модификатором',),
        aliases=('dgh', 'daggerheart'),
        show_in_menu=True,
        requires_core=False,
    ),
    CommandSpec(
        name='timer',
        callback=timer,
        menu_description='поставить таймер',
        help_lines=('/timer 60 — таймер в секундах',),
        requires_core=False,
    ),
    CommandSpec(
        name='help',
        callback=help_command,
        menu_description='показать справку',
        help_lines=('/help — эта справка',),
        aliases=('start',),
        requires_core=False,
    ),
    CommandSpec(
        name='version',
        callback=version_command,
        menu_description='показать версию бота',
        help_lines=('/version — версия бота',),
        requires_core=False,
    ),
)

MENU_COMMANDS = tuple(command for command in COMMANDS if command.show_in_menu)
CORE_COMMANDS = tuple(command for command in COMMANDS if command.requires_core)


def commands_for(*, core_connected: bool) -> tuple[CommandSpec, ...]:
    return tuple(command for command in COMMANDS if core_connected or not command.requires_core)


def help_message(*, core_connected: bool) -> str:
    return '🎲 Команды бота\n\n' + '\n'.join(
        line
        for command in commands_for(core_connected=core_connected)
        for line in command.help_lines
    )


HELP_MESSAGE = help_message(core_connected=True)
BASIC_HELP_MESSAGE = help_message(core_connected=False)
