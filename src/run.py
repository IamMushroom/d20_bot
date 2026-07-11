from dotenv import load_dotenv
from os import getenv
from telegram.ext import ApplicationBuilder, CommandHandler, filters
import commands
import logging
import log_format

def main() -> None:
    logging.info('Loading token from TG_TOKEN environment variable')
    token = getenv('TG_TOKEN')
    if not token:
        logging.critical('TG_TOKEN environment variable is not set')
        raise RuntimeError('TG_TOKEN environment variable is not set')
    logging.info('Token has been successfully loaded')
    app = ApplicationBuilder().token(token).concurrent_updates(16).build()
    app.add_handler(CommandHandler("roll", commands.roll, filters.TEXT))
    app.add_handler(CommandHandler("roll20", commands.roll20, filters.TEXT))
    app.add_handler(CommandHandler("rolld20", commands.rolld20, filters.TEXT))
    app.add_handler(CommandHandler("timer", commands.timer, filters.TEXT))
    app.add_handler(CommandHandler("duality", commands.duality, filters.TEXT))
    app.add_handler(CommandHandler("dgh", commands.duality, filters.TEXT))
    app.add_handler(CommandHandler("daggerheart", commands.duality, filters.TEXT))
    app.add_error_handler(commands.handle_error)
    logging.info('Application started')
    app.run_polling()

if __name__ == '__main__':
    load_dotenv()
    format_name = getenv('LOG_FORMAT', 'json')
    log_format.configure_logging(format_name)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)
    main()
