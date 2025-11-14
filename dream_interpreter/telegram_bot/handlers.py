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
from asgiref.sync import sync_to_async
from dreambot.models import User, DreamSession, Message
from dreambot.views import get_llm_response

# === АСИНХРОННЫЕ ОБЁРТКИ ДЛЯ ORM ===
get_or_create_user = sync_to_async(User.objects.get_or_create)
get_user_by_id = sync_to_async(User.objects.get)
create_message = sync_to_async(Message.objects.create)
get_or_create_session = sync_to_async(DreamSession.objects.get_or_create)
all_user_sessions = sync_to_async(lambda user: list(DreamSession.objects.filter(user=user).prefetch_related('messages').order_by('-created_at')[:3]))

# Обёртка для LLM (синхронная функция → асинхронный вызов)
get_llm_response_async = sync_to_async(get_llm_response)

# Состояния диалога
ASK_NAME, ASK_BIRTH_DATE = range(2)

from telegram import ReplyKeyboardMarkup

from telegram import KeyboardButton, ReplyKeyboardMarkup

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact_button = KeyboardButton("📱 Отправить номер", request_contact=True)
    keyboard = [
        [contact_button],
        ["/profile", "/history"],
        ["/guide", "/clear"]
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Расскажи мне свой сон или отправь номер"
    )

    await update.message.reply_text(
        "🌙 Привет! Я — ИИ сонник.\n\n"
        "Чтобы начать, просто нажми кнопку ниже — я получу твой номер и сохраню твои сны в защищённом профиле.",
        reply_markup=reply_markup
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверка: уже в сессии?
    if 'user_id' in context.user_data:
        try:
            user = await get_user_by_id(id=context.user_data['user_id'])
        except User.DoesNotExist:
            del context.user_data['user_id']
        else:
            # ... обработка сообщения ...
            session, _ = await get_or_create_session(user=user)
            await create_message(session=session, is_user=True, content=update.message.text.strip())
            bot_reply = await get_llm_response_async(user, update.message.text.strip())
            await create_message(session=session, is_user=False, content=bot_reply)
            await update.message.reply_text(bot_reply)
            return

    # Проверка: есть ли привязка по telegram_id?
    telegram_id = str(update.effective_user.id)
    try:
        user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
        context.user_data['user_id'] = user.id
        # ... обработка сообщения ...
        session, _ = await get_or_create_session(user=user)
        await create_message(session=session, is_user=True, content=update.message.text.strip())
        bot_reply = await get_llm_response_async(user, update.message.text.strip())
        await create_message(session=session, is_user=False, content=bot_reply)
        await update.message.reply_text(bot_reply)
        return
    except User.DoesNotExist:
        pass

    # Если не авторизован — просим номер
    await update.message.reply_text(
        "Я не узнаю тебя 😊\nПожалуйста, нажми «📱 Отправить номер» или пришли его вручную в формате +79991234567."
    )



# === /profile ===
async def profile_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'user_id' not in context.user_data:
        await update.message.reply_text("Сначала пришли свой номер телефона.")
        return ConversationHandler.END

    try:
        user = await get_user_by_id(id=context.user_data['user_id'])
    except User.DoesNotExist:
        await update.message.reply_text("Ошибка. Пришли номер снова.")
        return ConversationHandler.END

    info = f"Твой профиль:\nИмя: {user.name or 'не указано'}\nДата рождения: {user.birth_date or 'не указана'}\n\n"
    info += "Хочешь изменить имя? Напиши его или нажми «Пропустить»."
    await update.message.reply_text(info)
    return ASK_NAME



async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    name = None if user_input.lower() in ["пропустить", "skip", "нет"] else user_input[:100]
    context.user_data['temp_name'] = name
    await update.message.reply_text("Теперь укажи дату рождения в формате ДД.ММ.ГГГГ или «Пропустить».")
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

    user = await get_user_by_id(id=context.user_data['user_id'])
    user.name = context.user_data.get('temp_name')
    user.birth_date = birth_date
    await sync_to_async(user.save)()

    await update.message.reply_text("✅ Профиль обновлён! Теперь я лучше понимаю тебя.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Настройка профиля отменена.")
    return ConversationHandler.END



# === /history ===
async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'user_id' not in context.user_data:
        await update.message.reply_text("Сначала пришли номер телефона.")
        return

    try:
        user = await get_user_by_id(id=context.user_data['user_id'])
        sessions = await all_user_sessions(user)
        if not sessions:
            await update.message.reply_text("У тебя пока нет записанных снов.")
            return

        text = "✨ Твои последние сны:\n\n"
        for session in sessions:
            messages = await sync_to_async(list)(session.messages.all())
            for i in range(0, len(messages) - 1, 2):
                if messages[i].is_user and not messages[i+1].is_user:
                    dream = messages[i].content[:50] + "..." if len(messages[i].content) > 50 else messages[i].content
                    text += f"• {dream}\n"
                    break
            if len(text) > 300:
                break

        text += "\nПолная история — на сайте: http://твой-домен.ru/history/"
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text("Ошибка загрузки истории.")



async def clear_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'user_id' not in context.user_:
        await update.message.reply_text("Сначала пришли номер телефона.")
        return

    try:
        user = await get_user_by_id(id=context.user_data['user_id'])
        # Деактивируем текущие сессии
        await sync_to_async(DreamSession.objects.filter(user=user, is_active=True).update)(is_active=False)
        # Создаём новую
        await get_or_create_session(user=user, is_active=True)
        await update.message.reply_text("🧹 Чат очищен. История сохранена — ты можешь посмотреть её через /history.")
    except Exception as e:
        await update.message.reply_text("Не удалось очистить чат.")



async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>Как пользоваться ИИ-сонником</b>\n\n"
        "1. <b>Расскажи сон подробно</b>: эмоции, люди, места, символы.\n"
        "   Пример: «Мне снилось, что я теряю зубы перед зеркалом, а за спиной стоит мама в чёрном».\n\n"
        "2. <b>Не бойся быть уязвимым</b> — сны отражают внутреннее состояние.\n\n"
        "3. <b>Это не эзотерика</b> — я не предсказываю будущее, а помогаю понять себя.\n\n"
        "4. Ты всегда можешь:\n"
        "   • /profile — указать имя и дату рождения\n"
        "   • /history — посмотреть прошлые сны\n"
        "   • /clear — начать диалог с чистого листа (история сохраняется!)"
    )
    await update.message.reply_text(text, parse_mode="HTML")




async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    if not contact:
        await update.message.reply_text("Не удалось получить номер.")
        return

    # Получаем номер в формате +7...
    phone = contact.phone_number
    if phone.startswith('8'):
        phone = '+7' + phone[1:]
    elif phone.startswith('7'):
        phone = '+' + phone
    elif not phone.startswith('+'):
        phone = '+' + phone

    # Регистрация/вход
    user, created = await get_or_create_user(phone_number=phone)
    context.user_data['user_id'] = user.id

    # Привязываем telegram_id для будущих сессий (опционально, но очень полезно)
    if not user.telegram_id:
        user.telegram_id = str(update.effective_user.id)
        await sync_to_async(user.save)()

    reply = f"{'Рад знакомству' if created else 'С возвращением'}! ✨\n"
    if not user.name or not user.birth_date:
        reply += "Чтобы я мог глубже понимать твои сны, заполни профиль: /profile"
    else:
        reply += "Теперь ты можешь рассказать мне свой сон."

    await update.message.reply_text(reply)