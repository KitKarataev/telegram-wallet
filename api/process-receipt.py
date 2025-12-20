# api/process-receipt.py
from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
import os
import requests
import base64

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


def _extract_text_with_ocr_space(base64_image: str, api_key: str = "K87899142388957") -> str | None:
    """
    OCR.space API (бесплатный)
    """
    try:
        url = "https://api.ocr.space/parse/image"
        
        payload = {
            'base64Image': f'data:image/jpeg;base64,{base64_image}',
            'language': 'rus',
            'isOverlayRequired': False,
            'detectOrientation': True,
            'scale': True,
            'OCREngine': 2,
        }
        
        headers = {'apikey': api_key}
        
        print(f"[OCR.space] Sending request...")
        response = requests.post(url, data=payload, headers=headers, timeout=30)
        
        print(f"[OCR.space] Status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"[OCR.space] Error: {response.text[:200]}")
            return None
        
        result = response.json()
        print(f"[OCR.space] Response: {json.dumps(result)[:300]}")
        
        if result.get('IsErroredOnProcessing'):
            print(f"[OCR.space] Processing error: {result.get('ErrorMessage')}")
            return None
        
        parsed_results = result.get('ParsedResults', [])
        if not parsed_results:
            print("[OCR.space] No parsed results")
            return None
        
        text = parsed_results[0].get('ParsedText', '').strip()
        
        if not text:
            print("[OCR.space] Empty text")
            return None
        
        print(f"[OCR.space] SUCCESS! Extracted {len(text)} chars")
        print(f"[OCR.space] First 200 chars: {text[:200]}")
        
        return text
        
    except Exception as e:
        print(f"[OCR.space] Exception: {e}")
        return None


def _extract_text_with_simple_ocr(base64_image: str) -> str | None:
    """
    Простой OCR используя PIL и распознавание текста вручную
    (на случай если внешние API не работают)
    """
    try:
        # Декодируем base64
        image_data = base64.b64decode(base64_image)
        
        # Используем простой метод - отправляем в Google Cloud Vision API
        # (у них есть бесплатный tier - 1000 запросов/месяц)
        
        url = "https://vision.googleapis.com/v1/images:annotate"
        
        # Используем публичный API key (ограниченный)
        api_key = os.environ.get("GOOGLE_VISION_API_KEY", "").strip()
        
        if not api_key:
            print("[Google Vision] No API key, skipping")
            return None
        
        payload = {
            "requests": [{
                "image": {"content": base64_image},
                "features": [{"type": "TEXT_DETECTION"}]
            }]
        }
        
        print(f"[Google Vision] Sending request...")
        response = requests.post(f"{url}?key={api_key}", json=payload, timeout=30)
        
        if response.status_code != 200:
            print(f"[Google Vision] Error: {response.status_code}")
            return None
        
        result = response.json()
        
        responses = result.get('responses', [])
        if not responses:
            return None
        
        text_annotations = responses[0].get('textAnnotations', [])
        if not text_annotations:
            return None
        
        # Первая аннотация содержит весь текст
        text = text_annotations[0].get('description', '').strip()
        
        print(f"[Google Vision] SUCCESS! Extracted {len(text)} chars")
        
        return text
        
    except Exception as e:
        print(f"[Google Vision] Exception: {e}")
        return None


def _extract_text_from_image(base64_image: str) -> str | None:
    """
    Пробует несколько OCR методов
    """
    print("\n=== OCR START ===")
    
    # Метод 1: OCR.space (основной)
    text = _extract_text_with_ocr_space(base64_image)
    if text and len(text) > 10:
        print("=== OCR SUCCESS (OCR.space) ===\n")
        return text
    
    print("[OCR] OCR.space failed, trying alternatives...")
    
    # Метод 2: Google Vision (если настроен)
    text = _extract_text_with_simple_ocr(base64_image)
    if text and len(text) > 10:
        print("=== OCR SUCCESS (Google Vision) ===\n")
        return text
    
    print("=== OCR FAILED (all methods) ===\n")
    return None


def _create_receipt_prompt(ocr_text: str) -> str:
    """Создаём промпт для DeepSeek"""
    return f"""Проанализируй текст чека и верни ТОЛЬКО JSON.

Текст с чека:
{ocr_text[:3000]}

Формат:
{{
  "items": [
    {{"name": "Хлеб", "amount": 45.50}},
    {{"name": "Молоко", "amount": 89.00}}
  ],
  "total": 134.50,
  "store": "Пятёрочка"
}}

Правила:
1. Если это НЕ чек → {{"error": "not_a_receipt"}}
2. Если нет товаров → {{"error": "unreadable"}}
3. items - только товары с ценами
4. amount - число без валюты
5. Игнорируй итого/сдачу/оплачено
6. store - название магазина

Точность важнее полноты."""


def _extract_json_from_response(content: str) -> dict | None:
    """Извлекает JSON из ответа"""
    if not content:
        return None
    
    content = content.strip()
    
    if content.startswith('{') and content.endswith('}'):
        try:
            return json.loads(content)
        except:
            pass
    
    import re
    match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', content)
    if match:
        try:
            return json.loads(match.group(1))
        except:
            pass
    
    match = re.search(r'\{[\s\S]*\}', content)
    if match:
        try:
            return json.loads(match.group(0))
        except:
            pass
    
    return None


def _validate_receipt_data(data: dict) -> tuple[bool, str]:
    """Проверяет данные"""
    
    if data.get("error"):
        error_type = data["error"]
        if error_type == "not_a_receipt":
            return False, "Это не похоже на чек."
        elif error_type == "unreadable":
            return False, "Не удалось распознать товары."
        else:
            return False, f"Ошибка: {error_type}"
    
    items = data.get("items")
    if not isinstance(items, list) or len(items) == 0:
        return False, "Не удалось распознать товары."
    
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            return False, f"Ошибка товара #{idx + 1}"
        
        name = item.get("name")
        amount = item.get("amount")
        
        if not name:
            return False, f"Товар #{idx + 1}: нет названия"
        
        if amount is None:
            return False, f"Товар '{name}': нет суммы"
        
        try:
            amount_float = float(amount)
            if amount_float <= 0:
                return False, f"Товар '{name}': некорректная сумма"
            item["amount"] = amount_float
        except:
            return False, f"Товар '{name}': сумма не число"
    
    return True, ""


def _categorize_item(item_name: str, store_name: str = "") -> str:
    """Определяет категорию"""
    text = (item_name + " " + store_name).lower()
    
    for category, keywords in EXPENSE_CATEGORIES.items():
        if any(kw in text for kw in keywords):
            return category
    
    return "Продукты"


def _parse_receipt_with_deepseek(ocr_text: str) -> dict | None:
    """Парсит текст с DeepSeek"""
    
    api_key, model, base_url = _get_deepseek_config()
    
    if not api_key:
        print("[DeepSeek] No API key")
        return None
    
    url = _build_deepseek_url(base_url)
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Ты парсер чеков. Только JSON."},
            {"role": "user", "content": _create_receipt_prompt(ocr_text)}
        ],
        "temperature": 0.0,
        "max_tokens": 2000,
    }
    
    try:
        print(f"[DeepSeek] Sending request...")
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code != 200:
            print(f"[DeepSeek] Error {response.status_code}: {response.text[:200]}")
            return None
        
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        
        print(f"[DeepSeek] Response: {content[:200]}...")
        
        data = _extract_json_from_response(content)
        
        if not data:
            print("[DeepSeek] Failed to extract JSON")
            return None
        
        is_valid, error_msg = _validate_receipt_data(data)
        if not is_valid:
            print(f"[DeepSeek] Validation failed: {error_msg}")
            return {"error": "validation_failed", "message": error_msg}
        
        print(f"[DeepSeek] SUCCESS! Parsed {len(data.get('items', []))} items")
        return data
        
    except Exception as e:
        print(f"[DeepSeek] Exception: {e}")
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
        if not image_base64:
            send_error(self, 400, "Missing image")
            return
        
        custom_date = body.get("date")
        
        log_event("receipt_processing_started", user_id, {"date": custom_date})
        
        print(f"\n{'='*60}")
        print(f"Processing receipt for user {user_id}")
        print(f"Image size: {len(image_base64)} chars")
        print(f"{'='*60}\n")
        
        # OCR
        ocr_text = _extract_text_from_image(image_base64)
        
        if not ocr_text:
            log_event("receipt_processing_failed", user_id, {"reason": "ocr_failed"}, "error")
            send_error(self, 500, "Не удалось распознать текст. Попробуй:\n1. Лучше освещение\n2. Ближе к чеку\n3. Ровнее держи телефон")
            return
        
        # DeepSeek
        receipt_data = _parse_receipt_with_deepseek(ocr_text)
        
        if not receipt_data:
            log_event("receipt_processing_failed", user_id, {"reason": "parsing_failed"}, "error")
            send_error(self, 500, "Не удалось распознать товары. Попробуй ещё раз.")
            return
        
        if receipt_data.get("error"):
            error_msg = receipt_data.get("message", "Ошибка")
            log_event("receipt_processing_failed", user_id, {"reason": receipt_data.get("error")}, "warning")
            send_error(self, 400, error_msg)
            return
        
        # Save
        items = receipt_data.get("items", [])
        store_name = receipt_data.get("store", "")
        
        supabase = get_supabase_for_user(user_id)
        
        saved_items = []
        
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
            
            if custom_date:
                expense_data["created_at"] = custom_date
            
            try:
                supabase.table("expenses").insert(expense_data).execute()
                saved_items.append({"name": name, "amount": amount, "category": category})
            except Exception as e:
                print(f"[Save] Failed '{name}': {e}")
        
        log_event("receipt_processed", user_id, {
            "items_total": len(items),
            "items_saved": len(saved_items),
            "store": store_name
        })
        
        print(f"\n{'='*60}")
        print(f"SUCCESS! Saved {len(saved_items)}/{len(items)} items")
        print(f"{'='*60}\n")
        
        send_ok(self, {
            "message": "Success",
            "items": saved_items,
            "total_saved": len(saved_items),
            "store": store_name
        })
