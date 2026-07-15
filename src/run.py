import logging
from os import getenv

from dotenv import load_dotenv
from telegram import BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, filters

import commands
import log_format
from core import CORE_CLIENT_KEY, CoreClient
from core.events import EVENT_POLLER_KEY, poll_events, stop_event_poller

CORE_CONNECTED_KEY = 'core_connected'


def runtime_mode() -> str:
    mode = getenv('D20_MODE', 'standalone').lower()
    if mode not in {'standalone', 'connected'}:
        raise ValueError('D20_MODE must be standalone or connected')
    return mode


async def set_bot_commands(application) -> None:
    await application.bot.set_my_commands(
        [BotCommand(command.name, command.menu_description) for command in commands.MENU_COMMANDS]
    )
    logging.info('Application started')


async def initialize_application(application) -> None:
    mode = runtime_mode()
    application.bot_data[CORE_CONNECTED_KEY] = mode == 'connected'
    if mode == 'connected':
        application.bot_data[CORE_CLIENT_KEY] = CoreClient(
            required_environment('CORE_URL'), required_environment('CORE_TOKEN')
        )
        application.bot_data[EVENT_POLLER_KEY] = application.create_task(
            poll_events(application), name='core-event-poller'
        )
        await set_bot_commands(application)
        return
    await set_bot_commands(application)


async def shutdown_application(application) -> None:
    await stop_event_poller(application)
    application.bot_data.pop(CORE_CONNECTED_KEY, None)
    application.bot_data.pop(CORE_CLIENT_KEY, None)


def main() -> None:
    logging.info('Loading token from TG_TOKEN environment variable')
    token = required_environment('TG_TOKEN')
    logging.info('Token has been successfully loaded')
    app = (
        ApplicationBuilder()
        .token(token)
        .concurrent_updates(16)
        .post_init(initialize_application)
        .post_shutdown(shutdown_application)
        .build()
    )
    mode = runtime_mode()
    for command in commands.commands_for(core_connected=mode == 'connected'):
        for name in (command.name, *command.aliases):
            app.add_handler(
                CommandHandler(
                    name, commands.observed_callback(name, command.callback), filters.TEXT
                )
            )
    app.add_error_handler(commands.handle_error)
    logging.info('Starting application')
    app.run_polling()


def bootstrap() -> None:
    """Load configuration, set up logging and start the bot."""
    load_dotenv()
    format_name = getenv('LOG_FORMAT', 'json')
    log_format.configure_logging(format_name)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('telegram.ext.Application').setLevel(logging.WARNING)
    main()


def required_environment(name: str) -> str:
    value = getenv(name, '').strip()
    if not value:
        logging.critical('%s environment variable is not set', name)
        raise RuntimeError(f'{name} environment variable is not set')
    return value


if __name__ == '__main__':  # pragma: no cover
    bootstrap()
