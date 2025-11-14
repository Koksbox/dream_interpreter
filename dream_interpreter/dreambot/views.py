# dreambot/views.py
import json
import requests
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import login
from django.conf import settings
from .models import User, DreamSession, Message
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Prefetch
from django.utils import timezone


# Системный промпт — психологический уклон
SYSTEM_PROMPT = """
Ты — эмпатичный психолог-сонник. Твоя задача — помочь пользователю понять символы его сна через призму подсознания.
Не используй эзотерику, гадания, предсказания будущего.
Сосредоточься на эмоциях, внутренних конфликтах, личностном росте.
Обращайся по имени, если оно известно.
Задавай уточняющие вопросы, если сон описан скудно.
Говори мягко, поддерживай, не осуждай.
"""


def landing(request):
    if request.method == "POST":
        phone = request.POST.get("phone")
        name = request.POST.get("name") or None
        birth_date = request.POST.get("birth_date") or None
        if phone:
            user, created = User.objects.get_or_create(
                phone_number=phone,
                defaults={'name': name, 'birth_date': birth_date}
            )
            # Если пользователь уже есть — обновим данные, если они новые
            if not created:
                if name and not user.name:
                    user.name = name
                if birth_date and not user.birth_date:
                    user.birth_date = birth_date
                user.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('chat')
    return render(request, 'dreambot/landing.html')


def chat_view(request):
    if not request.user.is_authenticated:
        return redirect('landing')

    # Получаем или создаём активную сессию
    session, created = DreamSession.objects.get_or_create(
        user=request.user,
        is_active=True,
        defaults={'created_at': timezone.now()}
    )

    # Если сегодня не дата создания сессии → начать новую (полночь)
    if session.created_date != timezone.now().date():
        session.is_active = False
        session.save()
        session = DreamSession.objects.create(user=request.user, is_active=True)

    messages = Message.objects.filter(session=session).order_by('created_at')
    return render(request, 'dreambot/chat.html', {'messages': messages})


@csrf_exempt
def clear_chat(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Не авторизован'}, status=401)
    if request.method != "POST":
        return JsonResponse({'error': 'Только POST'}, status=400)

    # Деактивировать текущую сессию
    DreamSession.objects.filter(user=request.user, is_active=True).update(is_active=False)
    # Создать новую
    DreamSession.objects.create(user=request.user, is_active=True)

    return JsonResponse({'status': 'ok'})



import re
import logging

logger = logging.getLogger(__name__)


def get_llm_response(user, user_message):
    # Очистка API-ключа от всех возможных мусорных символов
    raw_key = settings.OPENROUTER_API_KEY
    # Оставляем только допустимые символы: буквы, цифры, дефис, подчёркивание
    clean_key = re.sub(r'[^a-zA-Z0-9\-_]', '', raw_key.strip())

    if not clean_key.startswith('sk-or-v1-'):
        logger.error(f"Некорректный OPENROUTER_API_KEY: начало='{raw_key[:20]}...', очищено='{clean_key[:20]}'")
        return "Сервис временно недоступен. Попробуй позже."

    # --- остальной код без изменений до headers ---
    past_messages = Message.objects.filter(
        session__user=user
    ).order_by('-created_at')[:10]

    history = []
    for msg in reversed(past_messages):
        role = "user" if msg.is_user else "assistant"
        history.append({"role": role, "content": msg.content})

    full_context = history + [{"role": "user", "content": user_message}]

    prompt_with_name = SYSTEM_PROMPT
    if user.name:
        prompt_with_name += f"\nИмя пользователя: {user.name}"

    messages_for_api = [{"role": "system", "content": prompt_with_name}] + full_context

    try:
        logger.info(f"Отправка запроса к LLM для {user.phone_number}")

        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers = {
                "Authorization": f"Bearer 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",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8077",
                "X-Title": "DreamInterpreter",
            },
                json={
                    "model": "qwen/qwen3-coder:free",
                    "messages": messages_for_api,
                    "temperature": 0.7,
                    "max_tokens": 500,
                }
            )

        response.raise_for_status()
        data = response.json()
        reply = data['choices'][0]['message']['content'].strip()
        logger.info(f"Получен ответ от LLM (длина: {len(reply)})")
        return reply

    except Exception as e:
        logger.error(f"Ошибка при запросе к LLM: {e}", exc_info=True)
        return "Извини, я сейчас устал… Расскажи ещё раз? 😊"



@csrf_exempt
def send_message(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Не авторизован'}, status=401)
    if request.method != "POST":
        return JsonResponse({'error': 'Только POST'}, status=405)

    try:
        data = json.loads(request.body)
        text = data.get('text', '').strip()
        if not text:
            return JsonResponse({'error': 'Пустое сообщение'}, status=400)

        user = request.user
        session, _ = DreamSession.objects.get_or_create(user=user)

        # Сохраняем сообщение пользователя
        user_msg = Message.objects.create(session=session, is_user=True, content=text)

        # Получаем ответ от LLM
        bot_reply = get_llm_response(user, text)

        # Сохраняем ответ бота
        bot_msg = Message.objects.create(session=session, is_user=False, content=bot_reply)

        # Возвращаем данные с временем
        return JsonResponse({
            'reply': bot_reply,
            'user_time': user_msg.created_at.isoformat(),   # ← время пользователя
            'bot_time': bot_msg.created_at.isoformat()      # ← время бота
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)





def profile_view(request):
    if not request.user.is_authenticated:
        return redirect('landing')
    return render(request, 'dreambot/profile.html', {'user': request.user})


@csrf_exempt
@require_http_methods(["POST"])
def update_profile(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Не авторизован'}, status=401)

    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip() or None
        birth_date_str = data.get('birth_date', '').strip() or None

        # Валидация даты
        birth_date = None
        if birth_date_str:
            try:
                birth_date = datetime.strptime(birth_date_str, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({'error': 'Неверный формат даты'}, status=400)

        user = request.user
        user.name = name
        user.birth_date = birth_date
        user.save()

        return JsonResponse({'status': 'ok'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def history_view(request):
    if not request.user.is_authenticated:
        return redirect('landing')

    sessions = DreamSession.objects.filter(user=request.user).prefetch_related(
        Prefetch('message_set', queryset=Message.objects.order_by('created_at'))
    ).order_by('-created_at')

    from collections import defaultdict
    history_by_date = defaultdict(list)
    for session in sessions:
        messages = list(session.message_set.all())  # ← здесь message_set
        for i in range(0, len(messages), 2):
            user_msg = messages[i] if i < len(messages) and messages[i].is_user else None
            bot_msg = messages[i + 1] if i + 1 < len(messages) and not messages[i + 1].is_user else None
            if user_msg and bot_msg:
                history_by_date[user_msg.created_at.date()].append({
                    'dream': user_msg.content,
                    'interpretation': bot_msg.content,
                    'time': user_msg.created_at.strftime('%H:%M')
                })

    sorted_history = sorted(history_by_date.items(), key=lambda x: x[0], reverse=True)
    return render(request, 'dreambot/history.html', {'history': sorted_history})

    return render(request, 'dreambot/history.html', {'history': sorted_history})


def guide_view(request):
    return render(request, 'dreambot/guide.html')