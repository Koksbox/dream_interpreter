import re
from datetime import datetime
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from asgiref.sync import sync_to_async
from dreambot.models import User, DreamSession, Message
from dreambot.views import get_llm_response

get_or_create_user = sync_to_async(User.objects.get_or_create)
get_user_by_id = sync_to_async(User.objects.get)
create_message = sync_to_async(Message.objects.create)
get_llm_response_async = sync_to_async(get_llm_response)

# Глобальные константы состояний
ASK_NAME, ASK_BIRTH_DATE = range(2)

def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Профиль", callback_data="profile"),
         InlineKeyboardButton("📜 История", callback_data="history")],
        [InlineKeyboardButton("❓ Инструкция", callback_data="guide"),
         InlineKeyboardButton("🧹 Очистить", callback_data="clear")],
        [InlineKeyboardButton("🔓 Премиум", callback_data="premium")]
    ])

async def get_or_create_active_session(user):
    from django.utils import timezone
    session = await sync_to_async(
        lambda: DreamSession.objects.filter(user=user, is_active=True).order_by('-created_at').first()
    )()
    if not session:
        session = await sync_to_async(DreamSession.objects.create)(user=user, is_active=True)
    else:
        if session.created_at.date() != timezone.now().date():
            await sync_to_async(DreamSession.objects.filter(user=user, is_active=True).update)(is_active=False)
            session = await sync_to_async(DreamSession.objects.create)(user=user, is_active=True)
    return session

# --- Основные команды ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact_button = KeyboardButton("📱 Отправить номер", request_contact=True)
    reply_markup = ReplyKeyboardMarkup([[contact_button]], resize_keyboard=True)
    welcome_text = (
        "🌙 <b>ИИ сонник</b>\n\n"
        "Я — твой психолог-сонник. Расскажи сон — поймёшь себя глубже.\n\n"
        "📱 Для начала отправь свой номер телефона, нажав кнопку ниже.\n\n"
        "💡 <i>Команды:</i>\n"
        "/start - начать заново\n"
        "/profile - редактировать профиль\n"
        "/help - помощь"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "❓ <b>Помощь</b>\n\n"
        "🌙 <b>Как пользоваться:</b>\n"
        "1. Отправь номер телефона\n"
        "2. Опиши свой сон подробно\n"
        "3. Получи глубокую интерпретацию\n\n"
        "📋 <b>Команды:</b>\n"
        "/start - начать заново\n"
        "/profile - редактировать профиль\n"
        "/help - эта справка\n\n"
        "💡 <b>Советы:</b>\n"
        "• Чем подробнее описание — тем глубже понимание\n"
        "• Укажи эмоции, которые ты чувствовал\n"
        "• Вспомни важные детали\n\n"
        "✨ Система запоминает твои предыдущие сны и находит связи между ними!"
    )
    await update.message.reply_text(help_text, parse_mode="HTML", reply_markup=get_main_menu())

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    if not contact:
        return
    phone = contact.phone_number
    if phone.startswith('8'):
        phone = '+7' + phone[1:]
    elif phone.startswith('7'):
        phone = '+' + phone
    elif not phone.startswith('+'):
        phone = '+' + phone
    user, created = await get_or_create_user(phone_number=phone)
    context.user_data['user_id'] = user.id
    if not user.telegram_id:
        user.telegram_id = str(update.effective_user.id)
        await sync_to_async(user.save)()

    if created:
        welcome_msg = (
            "✨ <b>Рад знакомству!</b>\n\n"
            "Теперь ты можешь рассказывать мне свои сны, и я помогу тебе их понять.\n\n"
            "💡 <i>Начни с описания своего сна — чем подробнее, тем лучше!</i>"
        )
    else:
        sessions_count = await sync_to_async(
            lambda: DreamSession.objects.filter(user=user).count()
        )()
        if sessions_count > 0:
            welcome_msg = (
                "✨ <b>С возвращением!</b>\n\n"
                f"Я помню тебя — у тебя уже {sessions_count} сессий.\n"
                "Расскажи новый сон, и я найду связи с предыдущими!"
            )
        else:
            welcome_msg = (
                "✨ <b>С возвращением!</b>\n\n"
                "Расскажи мне свой сон — я помогу его понять."
            )

    await update.message.reply_text(welcome_msg, parse_mode="HTML", reply_markup=get_main_menu())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text:
        await update.message.reply_text("📷 Я понимаю только текстовые описания снов. Опиши свой сон словами, пожалуйста.")
        return

    text = update.message.text.strip()
    if text.startswith('/'):
        return
    if 'user_id' not in context.user_data:
        await update.message.reply_text("📱 Нажми «Отправить номер».")
        return

    try:
        user = await get_user_by_id(id=context.user_data['user_id'])
    except Exception:
        await update.message.reply_text("Ошибка. Пришли номер снова.")
        return

    from django.utils import timezone
    today = timezone.now().date()
    if user.last_message_date != today:
        user.last_message_date = today
        user.free_messages_today = 0
        await sync_to_async(user.save)()

    if not user.is_premium and user.free_messages_today >= 5:
        await update.message.reply_text("💫 Лимит — 5 снов в день.\nНапиши /premium или нажми кнопку «Премиум».")
        return

    typing_message = await update.message.reply_text("🌙 Анализирую твой сон...")
    try:
        session = await get_or_create_active_session(user)
        await create_message(session=session, is_user=True, content=text)

        if not user.is_premium:
            user.free_messages_today += 1
            await sync_to_async(user.save)()

        bot_reply = await get_llm_response_async(user, text, session=session)
        await create_message(session=session, is_user=False, content=bot_reply)

        await typing_message.delete()
        await update.message.reply_text(bot_reply, reply_markup=get_main_menu())
    except Exception as e:
        await typing_message.delete()
        await update.message.reply_text(
            "Извини, произошла ошибка. Попробуй ещё раз. 😊",
            reply_markup=get_main_menu()
        )

# --- Обработчики кнопок и команд ---
async def profile_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query is not None:
        query = update.callback_query
        await query.answer()
        if 'user_id' not in context.user_data:
            await query.edit_message_text("📱 Сначала отправь номер телефона.", reply_markup=get_main_menu())
            return
        try:
            user = await get_user_by_id(id=context.user_data['user_id'])
            profile_text = "👤 Твой профиль:\n\n"
            profile_text += f"📱 Телефон: {user.phone_number}\n"
            profile_text += f"👤 Имя: {user.name or 'не указано'}\n"
            profile_text += f"🎂 Дата рождения: {(user.birth_date.strftime('%d.%m.%Y') if user.birth_date else 'не указана')}\n"
            profile_text += f"\n{'✨ Премиум активен' if user.is_premium else '🔓 Обычный аккаунт'}\n"
            profile_text += f"📊 Снов сегодня: {user.free_messages_today}/5\n"
            profile_text += "\n💡 Для редактирования используй команду /profile или веб-интерфейс."
            await query.edit_message_text(profile_text, reply_markup=get_main_menu())
        except Exception as e:
            await query.edit_message_text(f"Ошибка: {str(e)}", reply_markup=get_main_menu())
    else:
        if 'user_id' not in context.user_data:
            await update.message.reply_text("📱 Сначала отправь номер телефона.")
            return
        try:
            user = await get_user_by_id(id=context.user_data['user_id'])
            await update.message.reply_text(
                "👤 Для редактирования профиля используй команду /profile\n"
                "Или перейди на веб-интерфейс.",
                reply_markup=get_main_menu()
            )
        except Exception:
            await update.message.reply_text("Ошибка.", reply_markup=get_main_menu())

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query is not None:
        query = update.callback_query
        await query.answer()
        if 'user_id' not in context.user_data:
            await query.edit_message_text("📱 Сначала отправь номер телефона.", reply_markup=get_main_menu())
            return
        try:
            user = await get_user_by_id(id=context.user_data['user_id'])
            sessions = await sync_to_async(list)(DreamSession.objects.filter(user=user).order_by('-created_at')[:10])
            if not sessions:
                await query.edit_message_text("📜 История пока пуста.", reply_markup=get_main_menu())
            else:
                msg = "📜 История твоих снов:\n\n"
                for s in sessions:
                    first_dream = await sync_to_async(
                        lambda s=s: Message.objects.filter(session=s, is_user=True).order_by('created_at').first()
                    )()
                    if first_dream:
                        dream_preview = first_dream.content[:60] + "..." if len(first_dream.content) > 60 else first_dream.content
                        msg += f"📅 {s.created_at.strftime('%d.%m.%Y')}\n"
                        msg += f"   {dream_preview}\n\n"
                    else:
                        msg += f"📅 {s.created_at.strftime('%d.%m.%Y')}\n\n"
                msg += "💡 Полную историю можно посмотреть на веб-сайте."
                await query.edit_message_text(msg, reply_markup=get_main_menu())
        except Exception as e:
            await query.edit_message_text(f"Ошибка: {str(e)}", reply_markup=get_main_menu())

async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query is not None:
        query = update.callback_query
        await query.answer()
        text = """❓ Инструкция:

1. Опиши свой сон подробно
2. Укажи эмоции, которые ты чувствовал
3. Вспомни важные детали
4. Получи глубокую интерпретацию

Чем подробнее описание — тем глубже понимание! 🌙"""
        await query.edit_message_text(text, reply_markup=get_main_menu())

async def clear_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query is not None:
        query = update.callback_query
        await query.answer()
        if 'user_id' not in context.user_data:
            await query.edit_message_text("📱 Сначала отправь номер телефона.", reply_markup=get_main_menu())
            return
        try:
            user = await get_user_by_id(id=context.user_data['user_id'])
            await sync_to_async(DreamSession.objects.filter(user=user, is_active=True).update)(is_active=False)
            await sync_to_async(DreamSession.objects.create)(user=user, is_active=True)
            await query.edit_message_text(
                "🧹 Чат очищен.\n\n💡 История всех твоих снов сохранена и будет учитываться при новых интерпретациях.",
                reply_markup=get_main_menu()
            )
        except Exception as e:
            await query.edit_message_text(f"Ошибка: {str(e)}", reply_markup=get_main_menu())

async def activate_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query is not None:
        query = update.callback_query
        await query.answer()
        if 'user_id' not in context.user_data:
            await query.edit_message_text("📱 Сначала отправь номер телефона.", reply_markup=get_main_menu())
            return
        try:
            user = await get_user_by_id(id=context.user_data['user_id'])
            user.is_premium = True
            await sync_to_async(user.save)()
            await query.edit_message_text(
                "✨ Премиум активирован!\n\nТеперь у тебя неограниченный доступ к интерпретации снов! 🎉",
                reply_markup=get_main_menu()
            )
        except Exception as e:
            await query.edit_message_text(f"Ошибка: {str(e)}", reply_markup=get_main_menu())

# --- Командный обработчик для /profile (редактирование) ---
async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if 'user_id' in context.user_data:
        try:
            user = await get_user_by_id(id=context.user_data['user_id'])
            user.name = name
            await sync_to_async(user.save)()
            await update.message.reply_text(f"✅ Имя сохранено: {name}\nТеперь укажи дату рождения (ДД.ММ.ГГГГ):")
            return ASK_BIRTH_DATE
        except Exception:
            pass
    return ConversationHandler.END

async def handle_birth_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        date_str = update.message.text.strip()
        birth_date = datetime.strptime(date_str, '%d.%m.%Y').date()
        if 'user_id' in context.user_data:
            user = await get_user_by_id(id=context.user_data['user_id'])
            user.birth_date = birth_date
            await sync_to_async(user.save)()
            await update.message.reply_text("✅ Профиль сохранён!", reply_markup=get_main_menu())
            return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Неверный формат. Укажи дату в формате ДД.ММ.ГГГГ:")
        return ASK_BIRTH_DATE
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.", reply_markup=get_main_menu())
    return ConversationHandler.END

# --- Основной колбэк-роутер для inline-кнопок ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "profile":
        await profile_start(update, context)
    elif data == "history":
        await history_command(update, context)
    elif data == "guide":
        await guide_command(update, context)
    elif data == "clear":
        await clear_chat(update, context)
    elif data == "premium":
        await activate_premium(update, context)