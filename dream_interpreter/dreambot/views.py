# dreambot/views.py
import json
import requests
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import login
from django.conf import settings
from .models import User, DreamSession, Message

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
    session, _ = DreamSession.objects.get_or_create(user=request.user)
    messages = Message.objects.filter(session=session).order_by('created_at')
    return render(request, 'dreambot/chat.html', {'messages': messages})

def get_llm_response(user, user_message):
    # Получаем последние 10 сообщений (5 пар) для контекста
    past_messages = Message.objects.filter(
        session__user=user
    ).order_by('-created_at')[:10]

    # Формируем историю диалога (в обратном порядке)
    history = []
    for msg in reversed(past_messages):
        role = "user" if msg.is_user else "assistant"
        history.append({"role": role, "content": msg.content})

    # Добавляем новое сообщение
    full_context = history + [{"role": "user", "content": user_message}]

    # Формируем имя для персонализации
    user_name = user.name if user.name else None

    # Подготавливаем системный промпт с именем
    prompt_with_name = SYSTEM_PROMPT
    if user_name:
        prompt_with_name += f"\nИмя пользователя: {user_name}"

    messages_for_api = [{"role": "system", "content": prompt_with_name}] + full_context

    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "HTTP-Referer": "http://localhost:8000",  # для OpenRouter
                "X-Title": "ИИ Сонник",
            },
            json={
                "model": "meta-llama/llama-3.1-8b-instruct:free",
                "messages": messages_for_api,
                "temperature": 0.7,
                "max_tokens": 500,
            }
        )
        response.raise_for_status()
        data = response.json()
        return data['choices'][0]['message']['content'].strip()
    except Exception as e:
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
        Message.objects.create(session=session, is_user=True, content=text)

        # Получаем ответ от LLM
        bot_reply = get_llm_response(user, text)

        # Сохраняем ответ бота
        Message.objects.create(session=session, is_user=False, content=bot_reply)

        return JsonResponse({'reply': bot_reply})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)