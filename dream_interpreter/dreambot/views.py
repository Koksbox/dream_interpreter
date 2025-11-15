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
8. Будь эмпатичным: чувствуй эмоциональное состояние пользователя и отражай его в ответе.
9. Если видишь повторяющиеся темы или паттерны в нескольких снах — обязательно отметь это и помоги увидеть глубинные связи.

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
    return render(request, 'dreambot/chat.html', {'messages': messages, 'user': request.user})


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


def get_llm_response(user, user_message, session=None):
    # Формируем базовый промпт
    prompt = SYSTEM_PROMPT
    if user.name:
        prompt += f"\n\nИмя пользователя: {user.name}"
    if user.birth_date:
        from datetime import date
        today = date.today()
        age = today.year - user.birth_date.year - ((today.month, today.day) < (user.birth_date.month, user.birth_date.day))
        prompt += f"\nВозраст пользователя: {age} лет"
    
    # Собираем контекст из текущей сессии (последние сообщения)
    current_session_messages = []
    if session:
        # Получаем все сообщения, затем берем все кроме последнего
        all_messages = list(Message.objects.filter(session=session).order_by('created_at'))
        if len(all_messages) > 1:
            previous_messages = all_messages[:-1]  # Все кроме последнего
            # Берем последние 4 сообщения из текущей сессии (2 пары)
            for msg in previous_messages[-4:]:
                if msg.is_user:
                    current_session_messages.append(f"[Сегодня] Пользователь: {msg.content[:200]}")  # Ограничиваем длину
                else:
                    current_session_messages.append(f"[Сегодня] Сонник: {msg.content[:200]}")
    
    # Собираем контекст из предыдущих сессий (последние сны из разных дней)
    previous_sessions_dreams = []
    if session:
        # Берем последние 3-4 сессии (кроме текущей)
        previous_sessions = DreamSession.objects.filter(
            user=user
        ).exclude(id=session.id).order_by('-created_at')[:4]
        
        for prev_session in previous_sessions:
            # Берем первый сон из каждой предыдущей сессии (обычно это основной сон дня)
            first_user_message = Message.objects.filter(
                session=prev_session, is_user=True
            ).order_by('created_at').first()
            
            if first_user_message:
                session_date = prev_session.created_at.strftime('%d.%m')
                dream_preview = first_user_message.content[:150]  # Первые 150 символов
                previous_sessions_dreams.append(f"[{session_date}] Сон: {dream_preview}...")
    
    # Формируем полный контекст
    context_parts = []
    
    if current_session_messages:
        context_parts.append("Контекст текущего диалога:\n" + "\n".join(current_session_messages))
    
    if previous_sessions_dreams:
        context_parts.append("\nПредыдущие сны пользователя:\n" + "\n".join(previous_sessions_dreams))
        context_parts.append("\nВАЖНО: Учитывай предыдущие сны из разных дней при анализе нового сна. Ищи связи, закономерности и эмоциональные паттерны между снами. Если видишь повторяющиеся темы, символы или эмоции — обязательно отметь это и помоги увидеть глубинные связи. Анализируй динамику эмоционального состояния пользователя через несколько дней.")
    elif current_session_messages:
        context_parts.append("\nВАЖНО: Учитывай предыдущие сны и интерпретации при анализе нового сна. Ищи связи, закономерности и эмоциональные паттерны.")
    
    if context_parts:
        context_text = "\n\n" + "\n".join(context_parts)
    else:
        context_text = ""
    
    full_input = f"{prompt}{context_text}\n\nНовый сон:\n{user_message}"
    
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "qwen2:7b",
                "prompt": full_input,
                "stream": False,
                "options": {"temperature": 0.7}
            },
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        if "response" not in data:
            logger.error(f"Ollama response missing 'response' field: {data}")
            return "Извини, произошла ошибка при обработке. Попробуй ещё раз? 😊"
        return data["response"].strip()
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Ollama connection error: {e}")
        return "Извини, сервис временно недоступен. Убедись, что Ollama запущен. Попробуй ещё раз через минуту. 😊"
    except requests.exceptions.Timeout as e:
        logger.error(f"Ollama timeout error: {e}")
        return "Извини, ответ занимает слишком много времени. Попробуй ещё раз. 😊"
    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama request error: {e}")
        return "Извини, произошла ошибка при запросе. Попробуй ещё раз? 😊"
    except Exception as e:
        logger.error(f"Ollama unexpected error: {e}", exc_info=True)
        return "Извини, я сейчас устал… Расскажи ещё раз? 😊"


@csrf_exempt
def send_message(request):
    if not request.user.is_authenticated:
        logger.warning("Unauthenticated request to send_message")
        return JsonResponse({'reply': 'Пожалуйста, войдите.'}, status=200)
    if request.method != "POST":
        logger.warning(f"Invalid method {request.method} to send_message")
        return JsonResponse({'reply': 'Неверный метод.'}, status=200)

    user = request.user
    today = date.today()

    # ИСПРАВЛЕНО: проверка на None
    if user.last_message_date is None or user.last_message_date != today:
        user.last_message_date = today
        user.free_messages_today = 0
        user.save()

    # Проверка лимита
    if not user.is_premium and user.free_messages_today >= 5:
        return JsonResponse({
            'reply': (
                "💫 Ты достиг(ла) лимита — 5 снов в день.\n\n"
                "Хочешь неограниченный доступ к глубокой интерпретации и сохранению всей истории?\n\n"
                "👉 Нажми кнопку ниже, чтобы разблокировать Премиум!"
            ),
            'show_premium_button': True
        }, status=200)

    try:
        data = json.loads(request.body)
        text = data.get('text', '').strip()
        if not text:
            return JsonResponse({'reply': 'Пожалуйста, опиши сон.'}, status=200)

        logger.info(f"Processing message from user {user.id}: {text[:50]}...")

        try:
            session = DreamSession.objects.filter(user=user, is_active=True).order_by('-created_at').first()
            if not session:
                session = DreamSession.objects.create(user=user, is_active=True)
        except Exception as e:
            logger.error(f"Error creating/getting session: {e}", exc_info=True)
            return JsonResponse({
                'reply': 'Ошибка при создании сессии. Попробуй обновить страницу.'
            }, status=200)

        try:
            user_msg = Message.objects.create(session=session, is_user=True, content=text)
        except Exception as e:
            logger.error(f"Error creating user message: {e}", exc_info=True)
            return JsonResponse({
                'reply': 'Ошибка при сохранении сообщения. Попробуй ещё раз.'
            }, status=200)

        if not user.is_premium:
            try:
                user.free_messages_today += 1
                user.save()
            except Exception as e:
                logger.error(f"Error updating user message count: {e}", exc_info=True)
                # Продолжаем выполнение, это не критично

        logger.info(f"Calling get_llm_response for user {user.id}")
        try:
            bot_reply = get_llm_response(user, text, session=session)
            if not bot_reply:
                logger.error("get_llm_response returned empty reply")
                bot_reply = "Извини, произошла ошибка при генерации ответа. Попробуй ещё раз? 😊"
        except Exception as e:
            logger.error(f"Error in get_llm_response: {e}", exc_info=True)
            bot_reply = "Извини, произошла ошибка при обработке. Попробуй ещё раз? 😊"
        
        logger.info(f"Received reply from LLM: {bot_reply[:50] if bot_reply else 'None'}...")
        
        try:
            bot_msg = Message.objects.create(session=session, is_user=False, content=bot_reply)
        except Exception as e:
            logger.error(f"Error creating bot message: {e}", exc_info=True)
            # Продолжаем выполнение, но без сохранения времени
            bot_time = datetime.now().isoformat()
        else:
            bot_time = bot_msg.created_at.isoformat()

        return JsonResponse({
            'reply': bot_reply,
            'bot_time': bot_time
        })
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in send_message: {e}")
        return JsonResponse({
            'reply': 'Неверный формат данных. Попробуй ещё раз.'
        }, status=200)
    except Exception as e:
        logger.error(f"Unhandled error in send_message: {e}", exc_info=True)
        # Возвращаем 200 с сообщением об ошибке, чтобы не было 500 в браузере
        return JsonResponse({
            'reply': 'Извини, произошла неожиданная ошибка. Попробуй ещё раз? 😊'
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


from django.shortcuts import redirect
from django.urls import reverse

@csrf_exempt
def mock_premium_activate(request):
    if request.user.is_authenticated:
        user = request.user
        user.is_premium = True
        user.save()
    return redirect(reverse('chat') + '?premium=activated')