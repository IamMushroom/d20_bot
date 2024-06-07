from dotenv import load_dotenv
from os import getenv
from telegram.ext import ApplicationBuilder, CommandHandler, filters
import commands

def main() -> None:
    load_dotenv()
    token: str = getenv('TG_TOKEN', '0')
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("roll", commands.roll, filters.TEXT))
    app.add_handler(CommandHandler("rolld20", commands.rolld20, filters.TEXT))
    app.run_polling()

if __name__ == '__main__':
    main()