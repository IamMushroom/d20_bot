import logging
from os import getenv
from pathlib import Path

from dotenv import load_dotenv
from telegram import BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, filters

import commands
import log_format
from commands.admin_commands import ADMIN_ACCESS_KEY, CORE_CLIENT_KEY, WEB_BASE_URL_KEY
from commands.helpers import CAMPAIGN_SERVICE_KEY, DATABASE_KEY, SESSION_SERVICE_KEY
from core import CoreClient, CoreRuntime

MIGRATIONS_DIRECTORY = Path(__file__).resolve().parent.parent / 'migrations'
WEB_SERVER_KEY = 'web_server'
PLATFORM_ENABLED_KEY = 'platform_enabled'
CORE_CONNECTED_KEY = 'core_connected'
CORE_RUNTIME_KEY = 'core_runtime'


def runtime_mode() -> str:
    mode = getenv('D20_MODE', 'standalone').lower()
    if mode not in {'standalone', 'connected', 'full'}:
        raise ValueError('D20_MODE must be standalone, connected or full')
    return mode


def platform_enabled() -> bool:
    return runtime_mode() == 'full'


async def set_bot_commands(application) -> None:
    await application.bot.set_my_commands(
        [BotCommand(command.name, command.menu_description) for command in commands.MENU_COMMANDS]
    )
    logging.info('Application started')


async def initialize_application(application) -> None:
    mode = runtime_mode()
    enabled = mode == 'full'
    application.bot_data[PLATFORM_ENABLED_KEY] = enabled
    application.bot_data[CORE_CONNECTED_KEY] = mode == 'connected'
    if mode == 'connected':
        application.bot_data[CORE_CLIENT_KEY] = CoreClient(
            required_environment('CORE_URL'), required_environment('CORE_TOKEN')
        )
        await set_bot_commands(application)
        return
    if not enabled:
        await set_bot_commands(application)
        return
    try:
        runtime = await CoreRuntime.start(
            database_url=getenv('DATABASE_URL', 'sqlite:////data/d20.sqlite3'),
            migrations_directory=MIGRATIONS_DIRECTORY,
            web_host=getenv('WEB_HOST', '0.0.0.0'),
            web_port=int(getenv('WEB_PORT', '8190')),
            web_base_url=getenv('WEB_BASE_URL', '').strip(),
            internal_token=getenv('CORE_TOKEN', ''),
            telegram_bot=application.bot,
        )
        application.bot_data[CORE_RUNTIME_KEY] = runtime
        application.bot_data[DATABASE_KEY] = runtime.database
        application.bot_data[CAMPAIGN_SERVICE_KEY] = runtime.campaigns
        application.bot_data[SESSION_SERVICE_KEY] = runtime.sessions
        application.bot_data[ADMIN_ACCESS_KEY] = runtime.access
        application.bot_data[WEB_BASE_URL_KEY] = runtime.web_base_url
        application.bot_data[WEB_SERVER_KEY] = runtime.web_server
        await set_bot_commands(application)
    except BaseException:
        application.bot_data.clear()
        raise


async def shutdown_application(application) -> None:
    runtime = application.bot_data.pop(CORE_RUNTIME_KEY, None)
    application.bot_data.pop(WEB_SERVER_KEY, None)
    application.bot_data.pop(ADMIN_ACCESS_KEY, None)
    application.bot_data.pop(WEB_BASE_URL_KEY, None)
    application.bot_data.pop(CAMPAIGN_SERVICE_KEY, None)
    application.bot_data.pop(SESSION_SERVICE_KEY, None)
    application.bot_data.pop(DATABASE_KEY, None)
    if runtime is not None:
        await runtime.close()
    application.bot_data.pop(PLATFORM_ENABLED_KEY, None)
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
    for command in commands.commands_for(
        platform_enabled=mode == 'full', core_connected=mode == 'connected'
    ):
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
