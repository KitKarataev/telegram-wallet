# api/ai-chat.py - Эндпоинт для AI чата в приложении
from http.server import BaseHTTPRequestHandler
import json
import os
from datetime import datetime, timedelta
import requests

from api.auth import require_user_id
from api.db import get_supabase_for_user
from api.utils import read_json, send_ok, send_error
from api.logger import log_event


def get_chat_history(user_id: int, limit: int = 10) -> list:
    """Получает историю чата из БД"""
    supabase = get_supabase_for_user(user_id)
    
    try:
        result = supabase.table("ai_chat_history") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        
        # Разворачиваем чтобы старые сообщения были сверху
        return list(reversed(result.data)) if result.data else []
    except:
        return []


def save_chat_message(user_id: int, role: str, content: str):
    """Сохраняет сообщение в БД"""
    supabase = get_supabase_for_user(user_id)
    
    try:
        supabase.table("ai_chat_history").insert({
            "user_id": user_id,
            "role": role,
            "content": content,
            "created_at": datetime.now().isoformat()
        }).execute()
    except Exception as e:
        print(f"Save chat error: {e}")


def get_financial_context(user_id: int) -> dict:
    """Собирает финансовый контекст"""
    supabase = get_supabase_for_user(user_id)
    date_from = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    
    try:
        # Транзакции
        result = supabase.table("expenses").select("*").gte("created_at", date_from).execute()
        transactions = result.data
        
        # Подписки
        subs_result = supabase.table("subscriptions").select("*").execute()
        subscriptions = subs_result.data
        
        # Статистика
        total_income = sum(float(t['amount']) for t in transactions if t['type'] == 'income')
        total_expense = sum(float(t['amount']) for t in transactions if t['type'] == 'expense')
        
        categories = {}
        for t in transactions:
            if t['type'] == 'expense':
                cat = t.get('category', 'Разное')
                categories[cat] = categories.get(cat, 0) + float(t['amount'])
        
        top_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            "balance": total_income - total_expense,
            "total_income": total_income,
            "total_expense": total_expense,
            "daily_average": round(total_expense / 30, 2),
            "top_categories": [{"category": c, "amount": a} for c, a in top_categories],
            "subscriptions": [{"name": s['name'], "amount": s['amount']} for s in subscriptions],
            "transactions_count": len(transactions)
        }
    except:
        return {}


def create_system_prompt(context: dict, user_name: str = "User") -> str:
    """Создаёт системный промпт"""
    
    top_cats = "\n".join([f"  - {c['category']}: {c['amount']:.2f} ₽" for c in context.get('top_categories', [])])
    subs = "\n".join([f"  - {s['name']}: {s['amount']} ₽" for s in context.get('subscriptions', [])])
    
    return f"""Ты — персональный AI финансовый ассистент пользователя {user_name}.

📊 ФИНАНСОВАЯ СИТУАЦИЯ (30 дней):

Баланс: {context.get('balance', 0):.2f} ₽
Доход: {context.get('total_income', 0):.2f} ₽
Расход: {context.get('total_expense', 0):.2f} ₽
Средние траты/день: {context.get('daily_average', 0):.2f} ₽

Топ категории расходов:
{top_cats or '  (нет данных)'}

Подписки:
{subs or '  (нет)'}

Транзакций: {context.get('transactions_count', 0)}

---

🎯 ТВОИ СУПЕРСПОСОБНОСТИ:

1. **Расчёт стоимости часа работы**
   - Формула: месячный доход / (рабочие дни × 8 часов)
   - Помогает оценить покупки в часах работы

2. **Советник по покупкам**
   - Анализируешь стоит ли покупать
   - Учитываешь доходы, расходы, приоритеты
   - Предлагаешь альтернативы

3. **Бюджетный планировщик**
   - Составляешь реалистичные бюджеты
   - Находишь способы экономии
   - Предлагаешь финансовые цели

4. **Детектор аномалий**
   - Находишь необычные траты
   - Предупреждаешь о перерасходе
   - Замечаешь паттерны

5. **Калькулятор финансовых решений**
   - Кредит или накопить?
   - Вклад или инвестиции?
   - Сравниваешь варианты с цифрами

💬 СТИЛЬ ОБЩЕНИЯ:
- Дружелюбный и мотивирующий
- Конкретные цифры и примеры
- Никакой воды - только суть
- Эмодзи для наглядности (умеренно)
- Короткие ответы (2-4 предложения), длинные только если нужно

🎓 ПРИНЦИПЫ:
- Опирайся ТОЛЬКО на реальные данные
- Не придумывай цифры
- Если данных мало - скажи об этом
- Всегда давай практичные советы
- Помогай принимать осознанные решения

Отвечай на русском языке."""


def chat_with_ai(user_message: str, context: dict, history: list = None) -> str:
    """Общается с OpenAI"""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return "❌ OpenAI API key не настроен"
    
    # Формируем сообщения с историей
    messages = [{"role": "system", "content": create_system_prompt(context)}]
    
    # Добавляем последние 5 сообщений из истории
    if history:
        for msg in history[-10:]:  # Последние 10 сообщений
            messages.append({
                "role": msg.get("role"),
                "content": msg.get("content")
            })
    
    messages.append({"role": "user", "content": user_message})
    
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 1000
            },
            timeout=30
        )
        
        if response.status_code != 200:
            return f"❌ Ошибка AI: {response.status_code}"
        
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()
        
    except Exception as e:
        print(f"AI error: {e}")
        return "❌ Не удалось связаться с AI"


class handler(BaseHTTPRequestHandler):
    """
    POST /api/ai-chat
    Body: { "message": "Сколько стоит час моей работы?" }
    
    GET /api/ai-chat?history=true
    Возвращает историю чата
    """
    
    def do_GET(self):
        """Получение истории чата"""
        user_id = require_user_id(self)
        if user_id is None:
            return
        
        history = get_chat_history(user_id, limit=50)
        
        send_ok(self, {
            "history": history,
            "count": len(history)
        })
    
    def do_POST(self):
        """Отправка сообщения в чат"""
        user_id = require_user_id(self)
        if user_id is None:
            return
        
        body = read_json(self)
        if not body:
            return
        
        user_message = body.get("message", "").strip()
        if not user_message:
            send_error(self, 400, "Message is required")
            return
        
        log_event("ai_chat_message", user_id, {"message": user_message[:100]})
        
        # Получаем контекст и историю
        context = get_financial_context(user_id)
        history = get_chat_history(user_id, limit=10)
        
        # Сохраняем сообщение пользователя
        save_chat_message(user_id, "user", user_message)
        
        # Получаем ответ AI
        ai_response = chat_with_ai(user_message, context, history)
        
        # Сохраняем ответ AI
        save_chat_message(user_id, "assistant", ai_response)
        
        log_event("ai_chat_response", user_id, {"response_len": len(ai_response)})
        
        send_ok(self, {
            "message": ai_response,
            "context": {
                "balance": context.get("balance"),
                "daily_average": context.get("daily_average")
            }
        })
