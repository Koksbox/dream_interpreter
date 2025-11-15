# dreambot/views.py
import json
import requests
import time
import hashlib
from datetime import date, datetime
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse, HttpResponse
from django.contrib.auth import login
from django.conf import settings
from django.db.models import Prefetch
from django.utils import timezone
from .models import User, DreamSession, Message

# Системный промпт — психологический уклон
SYSTEM_PROMPT = """
Ты — эмпатичный психолог-сонник. Твоя задача — помочь пользователю глубже понять свои сны как отражение его подсознания.

Следуй этим правилам:
1. Никогда не используй эзотерику, гадания, символизм вроде «птица — к удаче».
2. Не предсказывай будущее. Сны — не пророчества, а зеркало настоящего.
3. Сосредоточься на:
   - эмоциях, которые вызвал сон (страх, радость, смущение и т.д.)
   - внутренних конфликтах (желание vs обязанность, свобода vs безопасность)
   - недавних событиях или переживаниях в реальной жизни
   - скрытых потребностях или подавленных чувствах
4. Говори мягко, тепло, поддерживающе. Не осуждай и не интерпретируй агрессивно.
5. Обращайся по имени, если оно известно.
6. Отвечай одним связным абзацем (3–5 предложений). Не задавай уточняющих вопросов.
7. Избегай клише вроде «возможно, это связано с...». Говори уверенно, но деликатно.

Пример хорошего ответа:
«Анна, в твоём сне о падении я чувствую сильный страх потери контроля. Это может отражать текущую ситуацию на работе, где ты чувствуешь давление и неуверенность. Падение — не предупреждение, а признак того, что ты уже давно держишься из последних сил. Твоё подсознание напоминает: позволить себе остановиться — не слабость, а забота о себе».

Теперь проанализируй сон пользователя.
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
    session = DreamSession.objects.filter(user=request.user, is_active=True).order_by('-created_at').first()
    if not session:
        session = DreamSession.objects.create(user=request.user, is_active=True)
    if session.created_at.date() != timezone.now().date():
        DreamSession.objects.filter(user=request.user, is_active=True).update(is_active=False)
        session = DreamSession.objects.create(user=request.user, is_active=True)
    messages = Message.objects.filter(session=session).order_by('created_at')
    return render(request, 'dreambot/chat.html', {'messages': messages})


@csrf_exempt
def clear_chat(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Не авторизован'}, status=401)
    if request.method != "POST":
        return JsonResponse({'error': 'Только POST'}, status=400)
    DreamSession.objects.filter(user=request.user, is_active=True).update(is_active=False)
    DreamSession.objects.create(user=request.user, is_active=True)
    return JsonResponse({'status': 'ok'})


import logging
logger = logging.getLogger(__name__)


def get_llm_response(user, user_message):
    prompt = SYSTEM_PROMPT + f"\n\nИмя пользователя: {user.name}" if user.name else SYSTEM_PROMPT
    full_input = f"{prompt}\n\nСон:\n{user_message}"
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "qwen2:7b",
                "prompt": full_input,  # ← ИСПРАВЛЕНО: full_input, а не prompt
                "stream": False,
                "options": {"temperature": 0.7}
            },
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        return data["response"].strip()
    except Exception as e:
        logger.error(f"Ollama error: {e}")
        return "Извини, я сейчас устал… Расскажи ещё раз? 😊"


@csrf_exempt
def send_message(request):
    if not request.user.is_authenticated:
        return JsonResponse({'reply': 'Пожалуйста, войдите.'}, status=200)
    if request.method != "POST":
        return JsonResponse({'reply': 'Неверный метод.'}, status=200)

    user = request.user
    today = date.today()

    # ИСПРАВЛЕНО: проверка на None
    if user.last_message_date is None or user.last_message_date != today:
        user.last_message_date = today
        user.free_messages_today = 0
        user.save()

    if not user.is_premium and user.free_messages_today >= 5:
        return JsonResponse({
            'reply': (
                "💫 Ты достиг(ла) лимита — 5 снов в день.\n\n"
                "Хочешь неограниченный доступ к глубокой интерпретации, анализу повторяющихся символов и сохранению всей истории?\n\n"
                "Нажми кнопку ниже, чтобы разблокировать Премиум!"
            ),
            'show_premium_button': True
        }, status=200)

    try:
        data = json.loads(request.body)
        text = data.get('text', '').strip()
        if not text:
            return JsonResponse({'reply': 'Пожалуйста, опиши сон.'}, status=200)

        session = DreamSession.objects.filter(user=user, is_active=True).order_by('-created_at').first()
        if not session:
            session = DreamSession.objects.create(user=user, is_active=True)

        user_msg = Message.objects.create(session=session, is_user=True, content=text)

        if not user.is_premium:
            user.free_messages_today += 1
            user.save()

        bot_reply = get_llm_response(user, text)
        bot_msg = Message.objects.create(session=session, is_user=False, content=bot_reply)

        return JsonResponse({
            'reply': bot_reply,
            'bot_time': bot_msg.created_at.isoformat()
        })
    except Exception as e:
        logger.error(f"Ошибка в send_message: {e}")
        return JsonResponse({
            'reply': 'Извини, я сейчас устал… Расскажи ещё раз? 😊'
        }, status=200)


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
        messages = list(session.message_set.all())
        for i in range(0, len(messages) - 1, 2):
            if messages[i].is_user and not messages[i+1].is_user:
                history_by_date[messages[i].created_at.date()].append({
                    'dream': messages[i].content,
                    'interpretation': messages[i+1].content,
                    'time': messages[i].created_at.strftime('%H:%M')
                })
    sorted_history = sorted(history_by_date.items(), key=lambda x: x[0], reverse=True)
    return render(request, 'dreambot/history.html', {'history': sorted_history})


def guide_view(request):
    return render(request, 'dreambot/guide.html')


def premium_checkout(request):
    if not request.user.is_authenticated:
        return redirect('landing')
    user = request.user
    out_sum = 299.00
    inv_id = f"premium_{user.id}_{int(time.time())}"
    robokassa_login = settings.ROBOKASSA_LOGIN
    robokassa_pass1 = settings.ROBOKASSA_PASS1
    signature = f"{robokassa_login}:{out_sum}:{inv_id}:{robokassa_pass1}"
    signature = hashlib.md5(signature.encode('utf-8')).hexdigest().upper()
    redirect_url = (
        f"https://auth.robokassa.ru/Merchant/Index.aspx?"
        f"MerchantLogin={robokassa_login}&"
        f"OutSum={out_sum}&"
        f"InvId={inv_id}&"
        f"SignatureValue={signature}&"
        f"Description=Премиум-доступ к ИИ-соннику&"
        f"Culture=ru"
    )
    return redirect(redirect_url)


@csrf_exempt
def robokassa_result(request):
    if request.method != 'POST':
        return HttpResponse('fail')
    inv_id = request.POST.get('InvId')
    out_sum = request.POST.get('OutSum')
    signature = request.POST.get('SignatureValue')
    try:
        user_id = inv_id.split('_')[1]
    except:
        return HttpResponse('fail')
    robokassa_pass2 = settings.ROBOKASSA_PASS2
    my_signature = f"{out_sum}:{inv_id}:{robokassa_pass2}"
    my_signature = hashlib.md5(my_signature.encode('utf-8')).hexdigest().upper()
    if my_signature != signature:
        return HttpResponse('fail')
    try:
        user = User.objects.get(id=user_id)
        user.is_premium = True
        user.save()
    except User.DoesNotExist:
        return HttpResponse('fail')
    return HttpResponse('OK')