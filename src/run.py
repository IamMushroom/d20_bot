import logging
from os import getenv
from pathlib import Path

from dotenv import load_dotenv
from telegram import BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, filters

import commands
import log_format
from commands.helpers import CAMPAIGN_SERVICE_KEY, DATABASE_KEY, SESSION_SERVICE_KEY
from database import apply_migrations, create_database
from services import CampaignService, SessionService

MIGRATIONS_DIRECTORY = Path(__file__).resolve().parent.parent / 'migrations'


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
    application.bot_data[DATABASE_KEY] = database
    application.bot_data[CAMPAIGN_SERVICE_KEY] = CampaignService(database)
    application.bot_data[SESSION_SERVICE_KEY] = SessionService(database)
    await set_bot_commands(application)


async def shutdown_application(application) -> None:
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
