# telegram_bot/bot.py
import os
import django
from django.conf import settings
from telegram.ext import MessageHandler, filters


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dream_interpreter.settings')
django.setup()

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler
)
from telegram_bot.handlers import (
    start,
    handle_message,
    clear_chat,
    profile_start,
    handle_name,
    handle_contact,
    handle_birth_date,
    cancel,
    guide_command,
    history_command,
    ASK_NAME,
    ASK_BIRTH_DATE
)



def run_telegram_bot():
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        print("Ошибка: TELEGRAM_BOT_TOKEN не задан в .env")
        return

    application = Application.builder().token(token).build()

    # Профиль — диалог
    profile_conv = ConversationHandler(
        entry_points=[CommandHandler("profile", profile_start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)],
            ASK_BIRTH_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_birth_date)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("profile", profile_start))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("guide", guide_command))
    application.add_handler(CommandHandler("clear", clear_chat))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))  # ← новое
    application.add_handler(profile_conv)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Telegram-бот запущен...")
    application.run_polling()