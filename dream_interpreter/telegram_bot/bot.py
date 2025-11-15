# telegram_bot/bot.py
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dream_interpreter.settings')
django.setup()

from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler
from telegram_bot.handlers import *


def run_telegram_bot():
    from django.conf import settings
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        print("Ошибка: TELEGRAM_BOT_TOKEN не задан")
        return
    application = Application.builder().token(token).build()

    profile_conv = ConversationHandler(
        entry_points=[CommandHandler("profile", profile_start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)],
            ASK_BIRTH_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_birth_date)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(profile_conv)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(r'^\/'), handle_message))

    print("Telegram-бот запущен...")
    application.run_polling()