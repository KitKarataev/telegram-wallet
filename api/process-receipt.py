# api/process-receipt.py
from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
import os
import requests
import re
import time

from api.auth import require_user_id
from api.db import get_supabase_for_user
from api.utils import read_json, send_ok, send_error
from api.logger import log_event


EXPENSE_CATEGORIES = {
    "Продукты": ["пятерочка", "перекресток", "магнит", "ашан", "лента", "вкусвилл", "lidl", "aldi", "carrefour", "mercadona"],
    "Кафе и Рестораны": ["кофе", "cafe", "restaurant", "burger", "pizza", "sushi"],
    "Транспорт": ["uber", "bolt", "taxi", "metro"],
    "Развлечения": ["netflix", "spotify", "steam", "cinema"],
}


def _ocr_with_api(base64_image: str) -> str | None:
    """
    OCR через api.api-ninjas.com (бесплатный, надёжный)
    """
    try:
        url = "https://api.api-ninjas.com/v1/imagetotext"
        
        # Бесплатный API key от API Ninjas
        api_key = os.environ.get("API_NINJAS_KEY", "").strip()
        
        # Если нет ключа, используем публичный (ограниченный)
        if not api_key:
            api_key = "YOUR_API_KEY_HERE"  # Нужен реальный ключ
        
        headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json"
        }
        
        # API Ninjas принимает base64 напрямую
        payload = {
            "image": base64_image
        }
        
        log_event("ocr_api_request", 0, {"service": "api-ninjas"})
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 401:
            log_event("ocr_api_unauthorized", 0, {}, "error")
            return None
        
        if response.status_code != 200:
            log_event("ocr_api_error", 0, {"code": response.status_code}, "error")
            return None
        
        result = response.json()
        
        # API Ninjas возвращает массив распознанных текстовых блоков
        if not isinstance(result, list) or len(result) == 0:
            log_event("ocr_no_text", 0, {}, "warning")
            return None
        
        # Собираем весь текст
        text = " ".join([item.get("text", "") for item in result])
        
        if len(text) < 10:
            return None
        
        log_event("ocr_success", 0, {"length": len(text)})
        return text.strip()
        
    except Exception as e:
        log_event("ocr_exception", 0, {"error": str(e)}, "error")
        return None


def _parse_with_deepseek(ocr_text: str) -> dict | None:
    """Парсит текст чека через DeepSeek"""
    
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return None
    
    prompt = f"""Текст с чека (распознан OCR):

{ocr_text[:2500]}

Твоя задача: извлечь товары и цены.

Верни JSON:
{{
  "items": [
    {{"name": "Хлеб белый", "amount": 45.50}},
    {{"name": "Молоко 3.2%", "amount": 89.00}}
  ],
  "store": "Пятёрочка",
  "total": 134.50
}}

Правила:
1. items - только товары с ценами (не итоги, не скидки)
2. amount - число без валюты
3. Если не можешь распознать товары: {{"error": "no_items"}}
4. store - название магазина из первых строк
5. Игнорируй "ИТОГО", "СДАЧА", "ОПЛАЧЕНО"

Будь точным. Только JSON в ответе."""

    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Ты эксперт по парсингу чеков. Отвечай только JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "max_tokens": 2000
        }
        
        log_event("deepseek_request", 0, {})
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code != 200:
            log_event("deepseek_error", 0, {"code": response.status_code}, "error")
            return None
        
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        
        # Извлекаем JSON из ответа
        json_match = re.search(r'\{[\s\S]*\}', content)
        if not json_match:
            return None
        
        data = json.loads(json_match.group(0))
        
        log_event("deepseek_success", 0, {"items": len(data.get("items", []))})
        
        return data
        
    except Exception as e:
        log_event("deepseek_exception", 0, {"error": str(e)}, "error")
        return None


def _categorize(name: str, store: str = "") -> str:
    """Определяет категорию товара"""
    text = (name + " " + store).lower()
    
    for cat, keywords in EXPENSE_CATEGORIES.items():
        if any(kw in text for kw in keywords):
            return cat
    
    return "Продукты"


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        user_id = require_user_id(self)
        if user_id is None:
            return
        
        body = read_json(self, max_bytes=10 * 1024 * 1024)
        if not body:
            return
        
        img_b64 = body.get("image")
        if not img_b64:
            send_error(self, 400, "No image")
            return
        
        date = body.get("date")
        
        log_event("receipt_start", user_id, {})
        
        # Шаг 1: OCR
        ocr_text = _ocr_with_api(img_b64)
        
        if not ocr_text:
            log_event("receipt_ocr_fail", user_id, {}, "error")
            send_error(
                self, 
                500, 
                "Не удалось распознать текст на чеке.\n\n" + 
                "Попробуй:\n" +
                "• Лучше освещение\n" +
                "• Ближе к чеку\n" +
                "• Или введи товары вручную 😊"
            )
            return
        
        # Шаг 2: Парсинг с DeepSeek
        data = _parse_with_deepseek(ocr_text)
        
        if not data or data.get("error"):
            log_event("receipt_parse_fail", user_id, {}, "error")
            send_error(
                self,
                500,
                "Не удалось распознать товары на чеке.\n\nПопробуй ещё раз или введи вручную."
            )
            return
        
        # Шаг 3: Сохранение
        items = data.get("items", [])
        store = data.get("store", "")
        
        if len(items) == 0:
            send_error(self, 400, "На чеке не найдено товаров")
            return
        
        supabase = get_supabase_for_user(user_id)
        saved = []
        
        for item in items:
            name = item.get("name", "")
            try:
                amount = float(item.get("amount", 0))
            except:
                continue
            
            if amount <= 0 or not name:
                continue
            
            cat = _categorize(name, store)
            desc = f"{name} ({store})" if store else name
            
            try:
                expense_data = {
                    "user_id": user_id,
                    "amount": amount,
                    "category": cat,
                    "description": desc,
                    "type": "expense"
                }
                
                if date:
                    expense_data["created_at"] = date
                
                supabase.table("expenses").insert(expense_data).execute()
                saved.append({"name": name, "amount": amount, "category": cat})
                
            except Exception as e:
                log_event("save_item_error", user_id, {"error": str(e)}, "error")
        
        if len(saved) == 0:
            send_error(self, 500, "Не удалось сохранить товары")
            return
        
        log_event("receipt_success", user_id, {"saved": len(saved), "total": len(items)})
        
        send_ok(self, {
            "items": saved,
            "total_saved": len(saved),
            "store": store
        })
