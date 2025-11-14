# dreambot/views.py
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import login
from .models import User, DreamSession, Message
import json

def landing(request):
    if request.method == "POST":
        phone = request.POST.get("phone")
        if phone:
            user, created = User.objects.get_or_create(phone_number=phone)
            if user.name is None or user.birth_date is None:
                # Можно позже уточнить в чате
                pass
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('chat')
    return render(request, 'dreambot/landing.html')

def chat_view(request):
    if not request.user.is_authenticated:
        return redirect('landing')
    # Получаем или создаём сессию
    session, _ = DreamSession.objects.get_or_create(user=request.user)
    messages = Message.objects.filter(session=session).order_by('created_at')
    return render(request, 'dreambot/chat.html', {'messages': messages})

@csrf_exempt
def send_message(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Не авторизован'}, status=401)
    if request.method == "POST":
        data = json.loads(request.body)
        text = data.get('text', '').strip()
        if not text:
            return JsonResponse({'error': 'Пустое сообщение'}, status=400)

        session, _ = DreamSession.objects.get_or_create(user=request.user)
        # Сохраняем сообщение пользователя
        Message.objects.create(session=session, is_user=True, content=text)

        # ЗАГЛУШКА: ответ от "ИИ"
        bot_reply = "Спасибо за сон! Я чувствую, что в нём много эмоций. Расскажи, что ты почувствовал(а) в самом напряжённом моменте?"
        Message.objects.create(session=session, is_user=False, content=bot_reply)

        return JsonResponse({'reply': bot_reply})
    return JsonResponse({'error': 'Только POST'}, status=405)