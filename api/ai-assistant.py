# api/ai-assistant.py
"""
AI Финансовый Ассистент
Использует OpenAI GPT-4 для анализа финансов пользователя
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
import os
from datetime import datetime, timedelta
import requests

from api.auth import require_user_id
from api.db import get_supabase_for_user
from api.utils import read_json, send_ok, send_error
from api.logger import log_event


def _get_user_financial_context(user_id: int) -> dict:
    """
    Собирает финансовый контекст пользователя для AI
    """
    supabase = get_supabase_for_user(user_id)
    
    # Получаем данные за последние 30 дней
    date_from = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    
    try:
        # Расходы и доходы
        result = supabase.table("expenses").select("*").gte("created_at", date_from).execute()
        transactions = result.data
        
        # Подписки
        subs_result = supabase.table("subscriptions").select("*").execute()
        subscriptions = subs_result.data
        
        # Считаем статистику
        total_income = 0
        total_expense = 0
        categories = {}
        
        for t in transactions:
            amount = float(t.get('amount', 0))
            if t['type'] == 'income':
                total_income += amount
            else:
                total_expense += amount
                cat = t.get('category', 'Разное')
                categories[cat] = categories.get(cat, 0) + amount
        
        balance = total_income - total_expense
        
        # Средние траты по категориям
        top_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]
        
        context = {
            "period": "30 дней",
            "balance": balance,
            "total_income": total_income,
            "total_expense": total_expense,
            "top_categories": [{"category": cat, "amount": amt} for cat, amt in top_categories],
            "subscriptions": [
                {
                    "name": s.get('name'),
                    "amount": s.get('amount'),
                    "period": s.get('period', 'monthly')
                }
                for s in subscriptions
            ],
            "transactions_count": len(transactions),
            "daily_average": round(total_expense / 30, 2)
        }
        
        return context
        
    except Exception as e:
        log_event("context_error", user_id, {"error": str(e)}, "error")
        return {}


def _create_system_prompt(context: dict) -> str:
    """
    Создаёт системный промпт для AI ассистента
    """
    
    top_cats = "\n".join([
        f"  - {c['category']}: {c['amount']} ₽"
        for c in context.get('top_categories', [])
    ])
    
    subs = "\n".join([
        f"  - {s['name']}: {s['amount']} ₽/{s['period']}"
        for s in context.get('subscriptions', [])
    ])
    
    prompt = f"""Ты — AI финансовый ассистент пользователя. Твоя задача — помогать ему управлять финансами.

📊 ФИНАНСОВАЯ СИТУАЦИЯ ПОЛЬЗОВАТЕЛЯ ({context.get('period', 'N/A')}):

Баланс: {context.get('balance', 0)} ₽
Доход: {context.get('total_income', 0)} ₽
Расход: {context.get('total_expense', 0)} ₽
Средние траты/день: {context.get('daily_average', 0)} ₽

Топ категории расходов:
{top_cats or '  (нет данных)'}

Активные подписки:
{subs or '  (нет подписок)'}

Всего операций: {context.get('transactions_count', 0)}

---

ТВОИ ВОЗМОЖНОСТИ:
✅ Анализировать траты и находить паттерны
✅ Давать конкретные советы по экономии
✅ Предупреждать о перерасходе
✅ Планировать бюджет
✅ Отвечать на финансовые вопросы
✅ Искать аномалии в тратах

СТИЛЬ ОБЩЕНИЯ:
- Дружелюбный, но профессиональный
- Конкретные советы с цифрами
- Никаких абстрактных фраз
- Используй эмодзи (умеренно)
- Короткие ответы (2-4 предложения)

ВАЖНО:
- Опирайся только на реальные данные пользователя
- Не придумывай цифры
- Если данных недостаточно — скажи об этом
- Всегда давай практичные советы

Отвечай на русском языке."""

    return prompt


def _chat_with_openai(user_message: str, system_prompt: str) -> str | None:
    """
    Отправляет запрос в OpenAI API
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    
    if not api_key:
        log_event("openai_no_key", 0, {}, "error")
        return None
    
    url = "https://api.openai.com/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "gpt-4o-mini",  # Быстрая и дешёвая модель
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.7,
        "max_tokens": 500
    }
    
    try:
        log_event("openai_request", 0, {"message_length": len(user_message)})
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code != 200:
            log_event("openai_error", 0, {
                "code": response.status_code,
                "body": response.text[:200]
            }, "error")
            return None
        
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        
        log_event("openai_success", 0, {"response_length": len(content)})
        
        return content.strip()
        
    except Exception as e:
        log_event("openai_exception", 0, {"error": str(e)}, "error")
        return None


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        """
        POST /api/ai-assistant
        Body: { "message": "Как мне сэкономить?" }
        """
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
        
        log_event("ai_chat_started", user_id, {"message": user_message[:100]})
        
        # Собираем контекст
        context = _get_user_financial_context(user_id)
        
        if not context:
            send_error(self, 500, "Не удалось загрузить финансовые данные")
            return
        
        # Создаём системный промпт
        system_prompt = _create_system_prompt(context)
        
        # Общаемся с OpenAI
        ai_response = _chat_with_openai(user_message, system_prompt)
        
        if not ai_response:
            send_error(self, 500, "AI временно недоступен. Попробуй позже.")
            return
        
        log_event("ai_chat_success", user_id, {
            "user_msg_len": len(user_message),
            "ai_msg_len": len(ai_response)
        })
        
        send_ok(self, {
            "message": ai_response,
            "context": {
                "balance": context.get("balance"),
                "daily_average": context.get("daily_average")
            }
        })
