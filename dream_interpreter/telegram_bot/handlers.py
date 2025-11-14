# telegram_bot/handlers.py
import re
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CommandHandler,
    filters
)
from dreambot.models import User, DreamSession, Message
from dreambot.views import get_llm_response

# Состояния диалога
ASK_NAME, ASK_BIRTH_DATE = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌙 Привет! Я — ИИ сонник.\n\n"
        "Расскажи мне свой сон, и я помогу понять, что твоё подсознание хочет тебе сказать.\n\n"
        "❗ Чтобы я мог помнить тебя и твои сны, пришли свой номер телефона в формате:\n"
        "`+79991234567`"
    )

# === РЕГИСТРАЦИЯ ПО НОМЕРУ ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    telegram_id = str(update.effective_user.id)

    # Проверяем, есть ли уже пользователь в сессии
    if 'user_id' in context.user_data:
        try:
            user = User.objects.get(id=context.user_data['user_id'])
        except User.DoesNotExist:
            del context.user_data['user_id']
        else:
            # Сохраняем сообщение и отвечаем через LLM
            session, _ = DreamSession.objects.get_or_create(user=user)
            Message.objects.create(session=session, is_user=True, content=text)
            bot_reply = get_llm_response(user, text)
            Message.objects.create(session=session, is_user=False, content=bot_reply)
            await update.message.reply_text(bot_reply)
            return

    # Пытаемся распознать номер телефона
    phone_match = re.search(r'(\+?7|8)?\s?[\d\s\-\(\)]{10,}', text)
    if phone_match:
        digits = re.sub(r'\D', '', text)
        if digits.startswith('8'):
            digits = '7' + digits[1:]
        if len(digits) == 11 and digits.startswith('7'):
            phone = '+' + digits
        elif len(digits) == 10:
            phone = '+7' + digits
        else:
            phone = None

        if phone:
            user, created = User.objects.get_or_create(phone_number=phone)
            context.user_data['user_id'] = user.id
            reply = f"{'Рад знакомству' if created else 'С возвращением'}! ✨\n"
            if not user.name or not user.birth_date:
                reply += "Чтобы я мог лучше понимать тебя, заполни профиль: /profile"
            await update.message.reply_text(reply)
            return

    await update.message.reply_text(
        "Я не узнаю тебя 😊\nПришли номер в формате +79991234567 или команду /profile, если уже зарегистрирован."
    )

# === /profile ===
async def profile_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'user_id' not in context.user_data:
        await update.message.reply_text("Сначала пришли свой номер телефона.")
        return ConversationHandler.END

    try:
        user = User.objects.get(id=context.user_data['user_id'])
    except User.DoesNotExist:
        await update.message.reply_text("Ошибка. Пришли номер снова.")
        return ConversationHandler.END

    # Показ текущего профиля
    info = f"Твой профиль:\n"
    info += f"Имя: {user.name or 'не указано'}\n"
    info += f"Дата рождения: {user.birth_date or 'не указана'}\n\n"
    info += "Хочешь изменить имя? Напиши его или нажми «Пропустить»."

    await update.message.reply_text(info)
    return ASK_NAME

async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    if user_input.lower() in ["пропустить", "skip", "нет"]:
        name = None
    else:
        name = user_input if len(user_input) <= 100 else user_input[:100]

    context.user_data['temp_name'] = name

    await update.message.reply_text(
        "Теперь укажи дату рождения в формате ДД.ММ.ГГГГ (например, 15.03.1995) или нажми «Пропустить»."
    )
    return ASK_BIRTH_DATE

async def handle_birth_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    birth_date = None

    if user_input.lower() not in ["пропустить", "skip", "нет"]:
        try:
            birth_date = datetime.strptime(user_input, "%d.%m.%Y").date()
        except ValueError:
            await update.message.reply_text("Неверный формат. Попробуй: 15.03.1995 или «Пропустить».")
            return ASK_BIRTH_DATE

    # Сохраняем в БД
    user = User.objects.get(id=context.user_data['user_id'])
    user.name = context.user_data.get('temp_name')
    user.birth_date = birth_date
    user.save()

    await update.message.reply_text("✅ Профиль обновлён! Теперь я лучше понимаю тебя.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Настройка профиля отменена.")
    return ConversationHandler.END