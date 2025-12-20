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


# Категории расходов (дубликат из bot.py для избежания циклических импортов)
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
    """Получаем конфиг DeepSeek из переменных окружения"""
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat").strip()
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    
    return api_key, model, base_url


def _build_deepseek_url(base_url: str) -> str:
    """Строим правильный URL для DeepSeek API"""
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    return base + "/chat/completions"


def _create_receipt_prompt() -> str:
    """Создаём промпт для распознавания чека"""
    return """Проанализируй этот чек и верни ТОЛЬКО JSON (без текста вокруг).

Формат ответа:
{
  "items": [
    {"name": "Хлеб белый", "amount": 45.50},
    {"name": "Молоко 3.2%", "amount": 89.00}
  ],
  "total": 134.50,
  "date": "2024-12-19",
  "store": "Пятёрочка"
}

Правила:
1. Если это НЕ чек, верни: {"error": "not_a_receipt"}
2. Если чек нечитаемый, верни: {"error": "unreadable"}
3. items - только то, что ТОЧНО видно на чеке
4. amount - всегда число (float), БЕЗ валюты
5. total - общая сумма чека
6. date - формат YYYY-MM-DD (если не видно - сегодняшнюю дату)
7. store - название магазина (если видно)

Будь точным. Лучше пропусти товар, чем добавь ошибочный."""


def _extract_json_from_response(content: str) -> dict | None:
    """Извлекает JSON из ответа DeepSeek (он может быть обёрнут в ```json)"""
    if not content:
        return None
    
    content = content.strip()
    
    # Вариант 1: чистый JSON
    if content.startswith('{') and content.endswith('}'):
        try:
            return json.loads(content)
        except Exception:
            pass
    
    # Вариант 2: обёрнут в ```json ... ```
    import re
    json_block = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', content)
    if json_block:
        try:
            return json.loads(json_block.group(1))
        except Exception:
            pass
    
    # Вариант 3: ищем любой JSON объект
    match = re.search(r'\{[\s\S]*\}', content)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    
    return None


def _validate_receipt_data(data: dict) -> tuple[bool, str]:
    """Проверяет корректность распознанных данных"""
    
    # Проверка на ошибки
    if data.get("error"):
        error_type = data["error"]
        if error_type == "not_a_receipt":
            return False, "Это не похоже на чек. Попробуй сфотографировать чек с покупками."
        elif error_type == "unreadable":
            return False, "Чек нечитаемый. Попробуй сфотографировать ещё раз при хорошем освещении."
        else:
            return False, f"Ошибка распознавания: {error_type}"
    
    # Проверка items
    items = data.get("items")
    if not isinstance(items, list) or len(items) == 0:
        return False, "Не удалось распознать товары на чеке."
    
    # Проверка каждого item
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            return False, f"Некорректный формат товара #{idx + 1}"
        
        name = item.get("name")
        amount = item.get("amount")
        
        if not name or not isinstance(name, str):
            return False, f"Товар #{idx + 1}: отсутствует название"
        
        if amount is None:
            return False, f"Товар '{name}': отсутствует сумма"
        
        # Конвертируем amount в число
        try:
            amount_float = float(amount)
            if amount_float <= 0:
                return False, f"Товар '{name}': некорректная сумма {amount}"
            # Обновляем на случай если было int
            item["amount"] = amount_float
        except (ValueError, TypeError):
            return False, f"Товар '{name}': сумма должна быть числом, получено {amount}"
    
    return True, ""


def _categorize_item(item_name: str, store_name: str = "") -> str:
    """Определяет категорию товара по его названию и магазину"""
    text_to_check = (item_name + " " + store_name).lower()
    
    # Проходим по всем категориям
    for category, keywords in EXPENSE_CATEGORIES.items():
        if any(keyword in text_to_check for keyword in keywords):
            return category
    
    # Дефолтная категория для чеков
    return "Продукты"


def _process_receipt_with_deepseek(base64_image: str) -> dict | None:
    """Отправляет изображение в DeepSeek Vision API и получает распознанные данные"""
    
    api_key, model, base_url = _get_deepseek_config()
    
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY не установлен")
        return None
    
    url = _build_deepseek_url(base_url)
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    # Формируем запрос с изображением
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Ты эксперт по распознаванию чеков. Отвечай только JSON."
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": _create_receipt_prompt()
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "temperature": 0.0,
        "max_tokens": 2000,
    }
    
    try:
        print(f"Sending request to DeepSeek Vision API: {url}")
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code != 200:
            print(f"DeepSeek API Error: {response.status_code}")
            print(f"Response: {response.text}")
            return None
        
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        
        print(f"DeepSeek response (first 200 chars): {content[:200]}")
        
        # Извлекаем JSON
        data = _extract_json_from_response(content)
        
        if not data:
            print(f"Failed to extract JSON from: {content[:500]}")
            return None
        
        # Валидируем данные
        is_valid, error_msg = _validate_receipt_data(data)
        if not is_valid:
            print(f"Validation failed: {error_msg}")
            return {"error": "validation_failed", "message": error_msg}
        
        return data
        
    except requests.exceptions.Timeout:
        print("DeepSeek API timeout")
        return {"error": "timeout", "message": "Превышено время ожидания. Попробуй ещё раз."}
    except Exception as e:
        print(f"DeepSeek API exception: {e}")
        return None


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 1. Аутентификация
        user_id = require_user_id(self)
        if user_id is None:
            return  # 401 уже отправлен
        
        # 2. Читаем тело запроса
        body = read_json(self, max_bytes=10 * 1024 * 1024)  # 10MB для изображений
        if body is None:
            return
        
        # 3. Получаем base64 изображение
        image_base64 = body.get("image")
        if not image_base64 or not isinstance(image_base64, str):
            send_error(self, 400, "Missing or invalid 'image' field (base64 string required)")
            return
        
        # 4. Получаем опциональную дату
        custom_date = body.get("date")
        
        # 5. Проверяем размер base64 (примерно 5MB после декодирования)
        if len(image_base64) > 7 * 1024 * 1024:  # ~7MB base64 = ~5MB файл
            send_error(self, 413, "Image too large. Maximum 5MB.")
            return
        
        # 6. Логируем попытку
        log_event("receipt_processing_started", user_id, {"date": custom_date})
        
        # 7. Отправляем в DeepSeek
        print(f"Processing receipt for user {user_id}")
        receipt_data = _process_receipt_with_deepseek(image_base64)
        
        if not receipt_data:
            log_event("receipt_processing_failed", user_id, {"reason": "deepseek_error"}, "error")
            send_error(self, 500, "Не удалось обработать чек. Попробуй ещё раз или введи данные вручную.")
            return
        
        # 8. Проверяем на ошибки распознавания
        if receipt_data.get("error"):
            error_msg = receipt_data.get("message", "Не удалось распознать чек")
            log_event("receipt_processing_failed", user_id, {"reason": receipt_data.get("error")}, "warning")
            send_error(self, 400, error_msg)
            return
        
        # 9. Получаем данные чека
        items = receipt_data.get("items", [])
        store_name = receipt_data.get("store", "")
        receipt_date = receipt_data.get("date")
        
        # 10. Получаем клиент Supabase
        supabase = get_supabase_for_user(user_id)
        
        # 11. Сохраняем каждый товар как отдельную запись
        saved_items = []
        failed_items = []
        
        for item in items:
            name = item["name"]
            amount = item["amount"]
            
            # Определяем категорию
            category = _categorize_item(name, store_name)
            
            # Формируем description
            if store_name:
                description = f"{name} ({store_name})"
            else:
                description = name
            
            # Данные для вставки
            expense_data = {
                "user_id": user_id,
                "amount": amount,
                "category": category,
                "description": description,
                "type": "expense",
            }
            
            # Если указана дата, используем её
            if custom_date and isinstance(custom_date, str):
                expense_data["created_at"] = custom_date
            elif receipt_date:
                expense_data["created_at"] = receipt_date
            
            # Сохраняем
            try:
                supabase.table("expenses").insert(expense_data).execute()
                saved_items.append({
                    "name": name,
                    "amount": amount,
                    "category": category
                })
            except Exception as e:
                print(f"Failed to save item '{name}': {e}")
                failed_items.append(name)
        
        # 12. Логируем результат
        log_event("receipt_processed", user_id, {
            "items_total": len(items),
            "items_saved": len(saved_items),
            "items_failed": len(failed_items),
            "store": store_name
        })
        
        # 13. Формируем ответ
        response_data = {
            "message": "Receipt processed successfully",
            "items": saved_items,
            "total_saved": len(saved_items),
            "total_failed": len(failed_items),
            "store": store_name
        }
        
        if failed_items:
            response_data["failed_items"] = failed_items
            response_data["warning"] = f"Не удалось сохранить {len(failed_items)} товаров"
        
        send_ok(self, response_data)
