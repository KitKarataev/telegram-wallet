# api/process-receipt.py
from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
import os
import requests
import re
import base64

from api.auth import require_user_id
from api.db import get_supabase_for_user
from api.utils import read_json, send_ok, send_error
from api.logger import log_event


EXPENSE_CATEGORIES = {
    "Продукты": ["пятерочка", "перекресток", "магнит", "ашан", "лента", "вкусвилл", "lidl", "aldi", "carrefour", "mercadona"],
    "Кафе и Рестораны": ["кофе", "cafe", "restaurant", "burger", "pizza", "sushi"],
    "Транспорт": ["uber", "bolt", "taxi", "metro"],
}


def _ocr_with_ocr_space(base64_image: str) -> str | None:
    """
    OCR.space API - проверенный рабочий вариант
    """
    try:
        url = "https://api.ocr.space/parse/image"
        
        # Формируем данные как form-data (не JSON!)
        payload = {
            'base64Image': f'data:image/jpeg;base64,{base64_image}',
            'language': 'rus',
            'isOverlayRequired': 'false',
            'detectOrientation': 'true',
            'scale': 'true',
            'OCREngine': '2',
        }
        
        # Используем бесплатный API key
        headers = {
            'apikey': 'K87899142388957',
        }
        
        log_event("ocr_request", 0, {"service": "ocr.space"})
        
        # ВАЖНО: используем data (form-data), а не json!
        response = requests.post(url, data=payload, headers=headers, timeout=30)
        
        if response.status_code != 200:
            log_event("ocr_http_error", 0, {
                "code": response.status_code,
                "body": response.text[:200]
            }, "error")
            return None
        
        result = response.json()
        
        # Проверяем на ошибки обработки
        if result.get('IsErroredOnProcessing'):
            error_msg = result.get('ErrorMessage', ['Unknown'])[0]
            log_event("ocr_processing_error", 0, {"error": error_msg}, "error")
            return None
        
        # Извлекаем текст
        parsed_results = result.get('ParsedResults', [])
        if not parsed_results:
            log_event("ocr_no_results", 0, {}, "warning")
            return None
        
        text = parsed_results[0].get('ParsedText', '').strip()
        
        if len(text) < 10:
            log_event("ocr_text_too_short", 0, {"length": len(text)}, "warning")
            return None
        
        log_event("ocr_success", 0, {"length": len(text)})
        return text
        
    except Exception as e:
        log_event("ocr_exception", 0, {"error": str(e)}, "error")
        return None


def _parse_with_deepseek(ocr_text: str) -> dict | None:
    """Парсит текст чека через DeepSeek"""
    
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        log_event("deepseek_no_key", 0, {}, "error")
        return None
    
    prompt = f"""Текст распознан с чека:

{ocr_text[:2500]}

Извлеки товары и цены. Верни JSON:

{{
  "items": [
    {{"name": "Хлеб", "amount": 45.50}},
    {{"name": "Молоко", "amount": 89.00}}
  ],
  "store": "Магазин"
}}

Правила:
- items: только товары с ценами
- amount: число без валюты
- Игнорируй ИТОГО/СДАЧА/СКИДКА
- Если нет товаров: {{"error": "no_items"}}

Только JSON!"""

    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Парсер чеков. Только JSON в ответе."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "max_tokens": 2000
        }
        
        log_event("deepseek_request", 0, {})
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code != 200:
            log_event("deepseek_error", 0, {
                "code": response.status_code,
                "body": response.text[:200]
            }, "error")
            return None
        
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        
        # Извлекаем JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if not json_match:
            log_event("deepseek_no_json", 0, {"content": content[:200]}, "error")
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
        
        # OCR
        ocr_text = _ocr_with_ocr_space(img_b64)
        
        if not ocr_text:
            log_event("receipt_ocr_fail", user_id, {}, "error")
            send_error(
                self, 
                500, 
                "Не удалось распознать чек.\n\nПопробуй:\n• Лучше освещение\n• Чёткое фото\n• Или введи вручную 😊"
            )
            return
        
        # Парсинг
        data = _parse_with_deepseek(ocr_text)
        
        if not data or data.get("error"):
            log_event("receipt_parse_fail", user_id, {}, "error")
            send_error(
                self,
                500,
                "Не удалось распознать товары.\n\nПопробуй сфотографировать ещё раз или введи вручную."
            )
            return
        
        # Сохранение
        items = data.get("items", [])
        store = data.get("store", "")
        
        if len(items) == 0:
            send_error(self, 400, "Товары не найдены на чеке")
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
                log_event("save_error", user_id, {"error": str(e)}, "error")
        
        if len(saved) == 0:
            send_error(self, 500, "Не удалось сохранить товары")
            return
        
        log_event("receipt_success", user_id, {"saved": len(saved), "total": len(items)})
        
        send_ok(self, {
            "items": saved,
            "total_saved": len(saved),
            "store": store
        })
