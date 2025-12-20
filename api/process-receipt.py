# api/process-receipt.py
from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
import os
import requests

from api.auth import require_user_id
from api.db import get_supabase_for_user
from api.utils import read_json, send_ok, send_error
from api.logger import log_event


# Категории расходов
EXPENSE_CATEGORIES = {
    "Алкоголь и Табак": ["к&б", "красное и белое", "пиво", "вино", "wine", "beer", "alcohol", "iqos", "glo", "vape"],
    "Продукты": ["пятерочка", "перекресток", "магнит", "ашан", "лента", "вкусвилл", "lidl", "aldi", "carrefour", "mercadona", "grocery", "supermarket"],
    "Кафе и Рестораны": ["кофе", "cafe", "coffee", "restaurant", "burger", "pizza", "sushi", "wolt", "glovo", "deliveroo"],
    "Транспорт": ["uber", "bolt", "taxi", "метро", "автобус", "train", "bus", "metro", "ticket"],
    "Авто и Бензин": ["shell", "bp", "repsol", "fuel", "gas", "petrol", "parking", "парковка", "заправка"],
    "Дом и Связь": ["ikea", "leroy", "internet", "mobile", "vodafone", "orange", "аренда", "жкх", "ремонт"],
    "Здоровье и Аптека": ["pharmacy", "apteka", "аптека", "doctor", "clinic", "hospital", "лекарства"],
    "Одежда и Шопинг": ["zara", "uniqlo", "mango", "amazon", "ozon", "wb", "wildberries", "asos", "одежда", "обувь"],
    "Развлечения": ["netflix", "spotify", "steam", "cinema", "кино", "театр", "youtube", "подписка"],
}


def _get_deepseek_config():
    """Получаем конфиг DeepSeek"""
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat").strip()
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    
    return api_key, model, base_url


def _build_deepseek_url(base_url: str) -> str:
    """Строим URL для DeepSeek API"""
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    return base + "/chat/completions"


def _extract_text_from_image_api(base64_image: str) -> str | None:
    """
    Извлекает текст из изображения используя OCR.space API (бесплатный).
    
    Returns:
        Распознанный текст или None
    """
    try:
        # OCR.space API (бесплатный, 25000 запросов/месяц)
        url = "https://api.ocr.space/parse/image"
        
        payload = {
            'base64Image': f'data:image/jpeg;base64,{base64_image}',
            'language': 'rus',  # Русский язык
            'isOverlayRequired': False,
            'detectOrientation': True,
            'scale': True,
            'OCREngine': 2,  # Engine 2 лучше для чеков
        }
        
        # API key (бесплатный, публичный)
        headers = {
            'apikey': 'K87899142388957',
        }
        
        print("Sending request to OCR.space API...")
        response = requests.post(url, data=payload, headers=headers, timeout=30)
        
        if response.status_code != 200:
            print(f"OCR API Error: {response.status_code}")
            return None
        
        result = response.json()
        
        if result.get('IsErroredOnProcessing'):
            print(f"OCR Error: {result.get('ErrorMessage')}")
            return None
        
        # Извлекаем текст
        parsed_results = result.get('ParsedResults', [])
        if not parsed_results:
            print("No parsed results from OCR")
            return None
        
        text = parsed_results[0].get('ParsedText', '').strip()
        
        if not text or len(text) < 10:
            print("OCR returned too little text")
            return None
        
        print(f"OCR extracted {len(text)} characters")
        print(f"First 200 chars: {text[:200]}")
        
        return text
        
    except requests.exceptions.Timeout:
        print("OCR API timeout")
        return None
    except Exception as e:
        print(f"OCR exception: {e}")
        return None


def _create_receipt_prompt(ocr_text: str) -> str:
    """Создаём промпт для DeepSeek"""
    return f"""Проанализируй текст чека и верни ТОЛЬКО JSON (без текста вокруг).

Текст с чека:
{ocr_text[:3000]}

Формат ответа:
{{
  "items": [
    {{"name": "Хлеб белый", "amount": 45.50}},
    {{"name": "Молоко 3.2%", "amount": 89.00}}
  ],
  "total": 134.50,
  "store": "Пятёрочка"
}}

Правила:
1. Если это НЕ чек, верни: {{"error": "not_a_receipt"}}
2. Если невозможно распознать товары, верни: {{"error": "unreadable"}}
3. items - только товары с ценами
4. amount - число (float), БЕЗ валюты
5. Игнорируй служебные строки (итого, оплачено, сдача)
6. total - общая сумма (ищи "итого", "сумма", "total")
7. store - название магазина (первые строки)

Будь точным. Лучше пропусти товар, чем добавь ошибочный."""


def _extract_json_from_response(content: str) -> dict | None:
    """Извлекает JSON из ответа DeepSeek"""
    if not content:
        return None
    
    content = content.strip()
    
    if content.startswith('{') and content.endswith('}'):
        try:
            return json.loads(content)
        except Exception:
            pass
    
    import re
    json_block = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', content)
    if json_block:
        try:
            return json.loads(json_block.group(1))
        except Exception:
            pass
    
    match = re.search(r'\{[\s\S]*\}', content)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    
    return None


def _validate_receipt_data(data: dict) -> tuple[bool, str]:
    """Проверяет корректность данных"""
    
    if data.get("error"):
        error_type = data["error"]
        if error_type == "not_a_receipt":
            return False, "Это не похоже на чек. Попробуй сфотографировать чек с покупками."
        elif error_type == "unreadable":
            return False, "Не удалось распознать товары. Попробуй сфотографировать ещё раз при хорошем освещении."
        else:
            return False, f"Ошибка распознавания: {error_type}"
    
    items = data.get("items")
    if not isinstance(items, list) or len(items) == 0:
        return False, "Не удалось распознать товары на чеке."
    
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            return False, f"Некорректный формат товара #{idx + 1}"
        
        name = item.get("name")
        amount = item.get("amount")
        
        if not name or not isinstance(name, str):
            return False, f"Товар #{idx + 1}: отсутствует название"
        
        if amount is None:
            return False, f"Товар '{name}': отсутствует сумма"
        
        try:
            amount_float = float(amount)
            if amount_float <= 0:
                return False, f"Товар '{name}': некорректная сумма {amount}"
            item["amount"] = amount_float
        except (ValueError, TypeError):
            return False, f"Товар '{name}': сумма должна быть числом"
    
    return True, ""


def _categorize_item(item_name: str, store_name: str = "") -> str:
    """Определяет категорию товара"""
    text_to_check = (item_name + " " + store_name).lower()
    
    for category, keywords in EXPENSE_CATEGORIES.items():
        if any(keyword in text_to_check for keyword in keywords):
            return category
    
    return "Продукты"


def _parse_receipt_with_deepseek(ocr_text: str) -> dict | None:
    """Парсит текст чека с DeepSeek"""
    
    api_key, model, base_url = _get_deepseek_config()
    
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY не установлен")
        return None
    
    url = _build_deepseek_url(base_url)
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    prompt = _create_receipt_prompt(ocr_text)
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Ты эксперт по распознаванию чеков. Отвечай только JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 2000,
    }
    
    try:
        print(f"Sending to DeepSeek: {url}")
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code != 200:
            print(f"DeepSeek Error: {response.status_code} - {response.text}")
            return None
        
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        
        print(f"DeepSeek response: {content[:200]}...")
        
        data = _extract_json_from_response(content)
        
        if not data:
            print(f"Failed to extract JSON")
            return None
        
        is_valid, error_msg = _validate_receipt_data(data)
        if not is_valid:
            print(f"Validation failed: {error_msg}")
            return {"error": "validation_failed", "message": error_msg}
        
        return data
        
    except Exception as e:
        print(f"DeepSeek exception: {e}")
        return None


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        user_id = require_user_id(self)
        if user_id is None:
            return
        
        body = read_json(self, max_bytes=10 * 1024 * 1024)
        if body is None:
            return
        
        image_base64 = body.get("image")
        if not image_base64 or not isinstance(image_base64, str):
            send_error(self, 400, "Missing image")
            return
        
        custom_date = body.get("date")
        
        if len(image_base64) > 7 * 1024 * 1024:
            send_error(self, 413, "Image too large")
            return
        
        log_event("receipt_processing_started", user_id, {"date": custom_date})
        
        # OCR
        print(f"Processing receipt for user {user_id}")
        print("Step 1: OCR...")
        
        ocr_text = _extract_text_from_image_api(image_base64)
        
        if not ocr_text:
            log_event("receipt_processing_failed", user_id, {"reason": "ocr_failed"}, "error")
            send_error(self, 500, "Не удалось распознать текст. Попробуй сфотографировать при лучшем освещении.")
            return
        
        # DeepSeek parsing
        print("Step 2: DeepSeek parsing...")
        
        receipt_data = _parse_receipt_with_deepseek(ocr_text)
        
        if not receipt_data:
            log_event("receipt_processing_failed", user_id, {"reason": "parsing_failed"}, "error")
            send_error(self, 500, "Не удалось обработать чек. Попробуй ещё раз.")
            return
        
        if receipt_data.get("error"):
            error_msg = receipt_data.get("message", "Ошибка")
            log_event("receipt_processing_failed", user_id, {"reason": receipt_data.get("error")}, "warning")
            send_error(self, 400, error_msg)
            return
        
        # Save items
        items = receipt_data.get("items", [])
        store_name = receipt_data.get("store", "")
        
        supabase = get_supabase_for_user(user_id)
        
        saved_items = []
        failed_items = []
        
        for item in items:
            name = item["name"]
            amount = item["amount"]
            
            category = _categorize_item(name, store_name)
            
            description = f"{name} ({store_name})" if store_name else name
            
            expense_data = {
                "user_id": user_id,
                "amount": amount,
                "category": category,
                "description": description,
                "type": "expense",
            }
            
            if custom_date and isinstance(custom_date, str):
                expense_data["created_at"] = custom_date
            
            try:
                supabase.table("expenses").insert(expense_data).execute()
                saved_items.append({"name": name, "amount": amount, "category": category})
            except Exception as e:
                print(f"Failed to save '{name}': {e}")
                failed_items.append(name)
        
        log_event("receipt_processed", user_id, {
            "items_total": len(items),
            "items_saved": len(saved_items),
            "items_failed": len(failed_items),
            "store": store_name
        })
        
        response_data = {
            "message": "Success",
            "items": saved_items,
            "total_saved": len(saved_items),
            "total_failed": len(failed_items),
            "store": store_name
        }
        
        if failed_items:
            response_data["failed_items"] = failed_items
        
        send_ok(self, response_data)
