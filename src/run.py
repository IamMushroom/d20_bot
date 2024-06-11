from dotenv import load_dotenv
from os import getenv
from telegram.ext import ApplicationBuilder, CommandHandler, filters
import commands
import logging
import log_format

def main() -> None:
    logging.info('"message": "Try to load token from TG_TOKEN env variable"')
    token: str = getenv('TG_TOKEN', '0')
    logging.error('"message": "Can\'t load token"') if token == 0 else logging.info('"message": "Token has been successfuly loaded"')
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("roll", commands.roll, filters.TEXT))
    app.add_handler(CommandHandler("rolld20", commands.rolld20, filters.TEXT))
    app.add_handler(CommandHandler("timer", commands.timer, filters.TEXT))
    logging.info('"message": "Application started"')
    app.run_polling()

if __name__ == '__main__':
    load_dotenv()
    format: str = getenv('LOG_FORMAT', 'json')
    logging.basicConfig(level=logging.INFO, format=log_format.format(format))
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)
    main()
