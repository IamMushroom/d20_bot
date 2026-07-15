import logging
from os import getenv
from pathlib import Path

from dotenv import load_dotenv
from telegram import BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, filters

import commands
import log_format
from commands.admin_commands import ADMIN_ACCESS_KEY, WEB_BASE_URL_KEY
from commands.helpers import CAMPAIGN_SERVICE_KEY, DATABASE_KEY, SESSION_SERVICE_KEY
from database import apply_migrations, create_database
from services import CampaignService, SessionService
from web import AdminAccessService, AdminWebServer

MIGRATIONS_DIRECTORY = Path(__file__).resolve().parent.parent / 'migrations'
WEB_SERVER_KEY = 'web_server'


async def set_bot_commands(application) -> None:
    await application.bot.set_my_commands(
        [BotCommand(command.name, command.menu_description) for command in commands.COMMANDS]
    )
    logging.info('Application started')


async def initialize_application(application) -> None:
    database_url = getenv('DATABASE_URL', 'sqlite:////data/d20.sqlite3')
    database = await create_database(database_url)
    try:
        await apply_migrations(database, MIGRATIONS_DIRECTORY)
    except BaseException:
        await database.close()
        raise
    try:
        campaign_service = CampaignService(database)
        session_service = SessionService(database)
        application.bot_data[DATABASE_KEY] = database
        application.bot_data[CAMPAIGN_SERVICE_KEY] = campaign_service
        application.bot_data[SESSION_SERVICE_KEY] = session_service
        base_url = getenv('WEB_BASE_URL', '').strip()
        if base_url:
            access = AdminAccessService()
            server = AdminWebServer(access, session_service, application.bot)
            await server.start(getenv('WEB_HOST', '0.0.0.0'), int(getenv('WEB_PORT', '8190')))
            application.bot_data[ADMIN_ACCESS_KEY] = access
            application.bot_data[WEB_BASE_URL_KEY] = base_url
            application.bot_data[WEB_SERVER_KEY] = server
        await set_bot_commands(application)
    except BaseException:
        await database.close()
        application.bot_data.clear()
        raise


async def shutdown_application(application) -> None:
    server = application.bot_data.pop(WEB_SERVER_KEY, None)
    if server is not None:
        await server.close()
    application.bot_data.pop(ADMIN_ACCESS_KEY, None)
    application.bot_data.pop(WEB_BASE_URL_KEY, None)
    application.bot_data.pop(CAMPAIGN_SERVICE_KEY, None)
    application.bot_data.pop(SESSION_SERVICE_KEY, None)
    database = application.bot_data.pop(DATABASE_KEY, None)
    if database is not None:
        await database.close()


def main() -> None:
    logging.info('Loading token from TG_TOKEN environment variable')
    token = getenv('TG_TOKEN')
    if not token:
        logging.critical('TG_TOKEN environment variable is not set')
        raise RuntimeError('TG_TOKEN environment variable is not set')
    logging.info('Token has been successfully loaded')
    app = (
        ApplicationBuilder()
        .token(token)
        .concurrent_updates(16)
        .post_init(initialize_application)
        .post_shutdown(shutdown_application)
        .build()
    )
    for command in commands.COMMANDS:
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


if __name__ == '__main__':  # pragma: no cover
    bootstrap()
