import logging
from os import getenv

from dotenv import load_dotenv
from telegram import BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, filters

import commands
import log_format


async def set_bot_commands(application) -> None:
    await application.bot.set_my_commands(
        [BotCommand(command.name, command.menu_description) for command in commands.COMMANDS]
    )


def main() -> None:
    logging.info('Loading token from TG_TOKEN environment variable')
    token = getenv('TG_TOKEN')
    if not token:
        logging.critical('TG_TOKEN environment variable is not set')
        raise RuntimeError('TG_TOKEN environment variable is not set')
    logging.info('Token has been successfully loaded')
    app = (
        ApplicationBuilder().token(token).concurrent_updates(16).post_init(set_bot_commands).build()
    )
    for command in commands.COMMANDS:
        for name in (command.name, *command.aliases):
            app.add_handler(CommandHandler(name, command.callback, filters.TEXT))
    app.add_error_handler(commands.handle_error)
    logging.info('Application started')
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
