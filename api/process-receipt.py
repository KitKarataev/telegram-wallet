# api/process-receipt.py
from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
import os
import requests
import base64
import re
from io import BytesIO

from api.auth import require_user_id
from api.db import get_supabase_for_user
from api.utils import read_json, send_ok, send_error
from api.logger import log_event


# Категории
EXPENSE_CATEGORIES = {
    "Продукты": ["пятерочка", "перекресток", "магнит", "ашан", "лента", "вкусвилл", "lidl", "aldi"],
    "Кафе и Рестораны": ["кофе", "cafe", "restaurant", "burger", "pizza"],
    "Транспорт": ["uber", "bolt", "taxi", "metro"],
}


def _extract_text_ocr(base64_image: str) -> str | None:
    """OCR используя pytesseract"""
    try:
        import pytesseract
        from PIL import Image
        
        # Декодируем base64
        img_data = base64.b64decode(base64_image)
        img = Image.open(BytesIO(img_data))
        
        # Распознаём текст (русский + английский)
        text = pytesseract.image_to_string(img, lang='rus+eng')
        
        if not text or len(text) < 10:
            return None
        
        return text.strip()
        
    except ImportError:
        # Tesseract не установлен - возвращаем None
        return None
    except Exception as e:
        log_event("ocr_error", 0, {"error": str(e)}, "error")
        return None


def _parse_with_deepseek(text: str) -> dict | None:
    """Парсит текст чека с DeepSeek"""
    
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return None
    
    prompt = f"""Текст с чека:

{text[:2000]}

Верни JSON:
{{
  "items": [{{"name": "Хлеб", "amount": 45.50}}],
  "store": "Магазин"
}}

Только товары с ценами. Если не чек: {{"error": "not_receipt"}}"""
    
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Парсер чеков. Только JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0
        }
        
        resp = requests.post(url, headers=headers, json=payload, timeout=25)
        
        if resp.status_code != 200:
            return None
        
        content = resp.json()["choices"][0]["message"]["content"]
        
        # Извлекаем JSON
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            data = json.loads(match.group(0))
            return data
        
        return None
        
    except:
        return None


def _categorize(name: str, store: str = "") -> str:
    text = (name + " " + store).lower()
    for cat, kws in EXPENSE_CATEGORIES.items():
        if any(k in text for k in kws):
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
        text = _extract_text_ocr(img_b64)
        
        if not text:
            log_event("receipt_ocr_fail", user_id, {}, "error")
            send_error(self, 500, "Не удалось распознать. Функция в разработке - введи товары вручную 😊")
            return
        
        # Parse
        data = _parse_with_deepseek(text)
        
        if not data or data.get("error"):
            log_event("receipt_parse_fail", user_id, {}, "error")
            send_error(self, 500, "Не удалось распознать товары")
            return
        
        # Save
        items = data.get("items", [])
        store = data.get("store", "")
        
        supabase = get_supabase_for_user(user_id)
        saved = []
        
        for item in items:
            name = item.get("name", "")
            amount = float(item.get("amount", 0))
            
            if amount <= 0:
                continue
            
            cat = _categorize(name, store)
            desc = f"{name} ({store})" if store else name
            
            try:
                supabase.table("expenses").insert({
                    "user_id": user_id,
                    "amount": amount,
                    "category": cat,
                    "description": desc,
                    "type": "expense",
                    "created_at": date if date else None
                }).execute()
                saved.append({"name": name, "amount": amount})
            except:
                pass
        
        log_event("receipt_success", user_id, {"count": len(saved)})
        
        send_ok(self, {
            "items": saved,
            "total_saved": len(saved),
            "store": store
        })
