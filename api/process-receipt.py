# api/process-receipt.py
from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
import os
import requests
import re
import base64
from io import BytesIO

from api.auth import require_user_id
from api.db import get_supabase_for_user
from api.utils import read_json, send_ok, send_error
from api.logger import log_event


EXPENSE_CATEGORIES = {
    "Продукты": ["пятерочка", "перекресток", "магнит", "ашан", "лента", "вкусвилл", "lidl", "aldi", "carrefour", "mercadona"],
    "Кафе и Рестораны": ["кофе", "cafe", "restaurant", "burger", "pizza", "sushi"],
    "Транспорт": ["uber", "bolt", "taxi", "metro"],
}


def _compress_image_for_ocr(base64_image: str, max_size_kb: int = 900) -> str | None:
    """
    Сжимает изображение до нужного размера для OCR
    """
    try:
        from PIL import Image
        
        # Декодируем base64
        img_data = base64.b64decode(base64_image)
        img = Image.open(BytesIO(img_data))
        
        # Конвертируем в RGB если нужно
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        
        # Уменьшаем разрешение (для OCR достаточно 1024px)
        max_dimension = 1024
        if max(img.size) > max_dimension:
            ratio = max_dimension / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Сжимаем с разным качеством пока не влезем в лимит
        for quality in [85, 75, 65, 55, 45]:
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=quality, optimize=True)
            
            size_kb = len(buffer.getvalue()) / 1024
            
            if size_kb <= max_size_kb:
                compressed_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                log_event("image_compressed", 0, {
                    "original_kb": len(base64_image) * 3 / 4 / 1024,
                    "compressed_kb": size_kb,
                    "quality": quality
                })
                return compressed_b64
        
        # Если даже с качеством 45 не влезли - возвращаем как есть
        log_event("compression_failed", 0, {"size_kb": size_kb}, "warning")
        return base64_image
        
    except ImportError:
        log_event("pil_not_available", 0, {}, "warning")
        return base64_image
    except Exception as e:
        log_event("compression_error", 0, {"error": str(e)}, "error")
        return base64_image


def _ocr_with_ocr_space(base64_image: str) -> str | None:
    """
    OCR.space API
    """
    try:
        # Сжимаем изображение для OCR
        compressed_image = _compress_image_for_ocr(base64_image, max_size_kb=900)
        
        url = "https://api.ocr.space/parse/image"
        
        payload = {
            'base64Image': f'data:image/jpeg;base64,{compressed_image}',
            'language': 'rus',
            'isOverlayRequired': 'false',
            'detectOrientation': 'true',
            'scale': 'true',
            'OCREngine': '2',
        }
        
        headers = {
            'apikey': 'K87899142388957',
        }
        
        log_event("ocr_request", 0, {"service": "ocr.space"})
        
        response = requests.post(url, data=payload, headers=headers, timeout=30)
        
        if response.status_code != 200:
            log_event("ocr_http_error", 0, {
                "code": response.status_code,
                "body": response.text[:200]
            }, "error")
            return None
        
        result = response.json()
        
        if result.get('IsErroredOnProcessing'):
            error_msg = result.get('ErrorMessage', ['Unknown'])[0]
            log_event("ocr_processing_error", 0, {"error": error_msg}, "error")
            return None
        
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
    
    prompt = f"""Текст с чека:

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
- Игнорируй ИТОГО/СДАЧА
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
                {"role": "system", "content": "Парсер чеков. Только JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "max_tokens": 2000
        }
        
        log_event("deepseek_request", 0, {})
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code != 200:
            log_event("deepseek_error", 0, {
                "code": response.status_code
            }, "error")
            return None
        
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        
        json_match = re.search(r'\{[\s\S]*\}', content)
        if not json_match:
            log_event("deepseek_no_json", 0, {}, "error")
            return None
        
        data = json.loads(json_match.group(0))
        
        log_event("deepseek_success", 0, {"items": len(data.get("items", []))})
        
        return data
        
    except Exception as e:
        log_event("deepseek_exception", 0, {"error": str(e)}, "error")
        return None


def _categorize(name: str, store: str = "") -> str:
    """Определяет категорию"""
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
                "Не удалось распознать товары.\n\nПопробуй ещё раз или введи вручную."
            )
            return
        
        # Сохранение
        items = data.get("items", [])
        store = data.get("store", "")
        
        if len(items) == 0:
            send_error(self, 400, "Товары не найдены")
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
            send_error(self, 500, "Не удалось сохранить")
            return
        
        log_event("receipt_success", user_id, {"saved": len(saved)})
        
        send_ok(self, {
            "items": saved,
            "total_saved": len(saved),
            "store": store
        })
