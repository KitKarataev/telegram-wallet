from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import os
import json
import re
import requests

from api.db import get_supabase_admin
from api.utils import read_json


def _get_env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name)
    if v:
        return v
    if default is not None:
        return default
    raise RuntimeError(f"Missing required environment variable: {name}")


TG_TOKEN = _get_env("TELEGRAM_TOKEN")
WEBHOOK_SECRET = _get_env("TELEGRAM_WEBHOOK_SECRET")
WEBHOOK_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

DEEPSEEK_API_KEY = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
DEEPSEEK_MODEL = (os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat").strip()
DEEPSEEK_BASE_URL = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").strip()


SYMBOLS = {"RUB": "₽", "USD": "$", "EUR": "€"}

ALLOWED_CATEGORIES = [
    "Алкоголь и Табак", "Продукты", "Кафе и Рестораны", "Транспорт", "Авто и Бензин",
    "Дом и Связь", "Здоровье и Аптека", "Одежда и Шопинг", "Развлечения", "Разное", "Доход"
]

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


def send_telegram(chat_id, text: str, reply_markup=None) -> None:
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            raise RuntimeError(f"Telegram sendMessage failed: {r.status_code} {r.text}")
    except Exception as e:
        print("send_telegram ERROR:", e)


def get_quick_buttons_keyboard(user_id: int):
    """Получает быстрые кнопки пользователя и формирует клавиатуру"""
    try:
        supabase = get_supabase_admin()
        res = supabase.table("quick_buttons").select("buttons").eq("user_id", user_id).execute()
        
        if res.data and res.data[0].get("buttons"):
            buttons_data = res.data[0]["buttons"]
            
            # Формируем клавиатуру 2x3
            keyboard = []
            row = []
            for i, button in enumerate(buttons_data):
                if button.strip():
                    row.append({"text": button})
                    if len(row) == 2 or i == len(buttons_data) - 1:
                        keyboard.append(row)
                        row = []
            
            if keyboard:
                return {
                    "keyboard": keyboard,
                    "resize_keyboard": True,
                    "one_time_keyboard": False
                }
    except Exception as e:
        print(f"Error getting quick buttons: {e}")
    
    return None


def _extract_amount_simple(text: str) -> int | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        amt = int(digits)
        if amt <= 0 or amt > 10_000_000:
            return None
        return amt
    except Exception:
        return None


def parse_fallback(text_raw: str) -> dict | None:
    text = (text_raw or "").lower().strip()
    amount = _extract_amount_simple(text)
    if amount is None:
        return None

    record_type = "expense"
    category = "Разное"

    income_words = ["зарплата", "зп", "аванс", "приход", "перевод", "кэшбэк", "доход", "salary", "deposit"]
    if any(w in text for w in income_words):
        record_type = "income"
        category = "Доход"
    else:
        for cat_name, keywords in EXPENSE_CATEGORIES.items():
            if any(k in text for k in keywords):
                category = cat_name
                break

    desc = re.sub(r"\s+", " ", text_raw).strip() if text_raw else "Запись"
    return {"amount": amount, "type": record_type, "category": category, "description": desc}


def _deepseek_url() -> str:
    base = DEEPSEEK_BASE_URL.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    return base + "/chat/completions"


def _extract_json_object(s: str) -> dict | None:
    if not s:
        return None
    s = s.strip()

    if s.startswith('{') and s.endswith('}'):
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass

    json_block = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', s)
    if json_block:
        try:
            obj = json.loads(json_block.group(1))
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass

    m = re.search(r'\{[\s\S]*\}', s)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def parse_with_deepseek(text_raw: str) -> dict | None:
    if not DEEPSEEK_API_KEY:
        print("DeepSeek disabled: DEEPSEEK_API_KEY is empty")
        return None

    url = _deepseek_url()
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    prompt = f"""
Верни ТОЛЬКО JSON (без текста вокруг). Финансовая запись пользователя:

{text_raw}

Формат:
{{
  "amount": 123,
  "type": "expense" | "income",
  "category": {json.dumps(ALLOWED_CATEGORIES, ensure_ascii=False)},
  "description": "коротко без суммы"
}}

Если суммы нет, верни: {{"error":"no_amount"}}
"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "Ты парсер трат/доходов для финансового бота. Отвечай только JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 250,
        "stream": False,
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=25)
        if r.status_code != 200:
            print("DeepSeek HTTP ERROR:", r.status_code, r.text)
            return None

        j = r.json()
        content = j["choices"][0]["message"].get("content", "") or ""
        data = _extract_json_object(content)

        if not isinstance(data, dict):
            print("DeepSeek parse: not a JSON object. content=", content[:200])
            return None

        if data.get("error") == "no_amount":
            return None

        amount = data.get("amount")
        if not isinstance(amount, int) or amount <= 0:
            print("DeepSeek parse invalid amount:", data)
            return None

        rtype = data.get("type")
        if rtype not in ("income", "expense"):
            rtype = "expense"

        category = data.get("category") or ("Доход" if rtype == "income" else "Разное")
        if category not in ALLOWED_CATEGORIES:
            category = "Доход" if rtype == "income" else "Разное"

        desc = (data.get("description") or "").strip()
        desc = re.sub(r"\s+", " ", desc)
        if not desc:
            desc = re.sub(r"\s+", " ", text_raw).strip() if text_raw else "Запись"

        return {"amount": amount, "type": rtype, "category": category, "description": desc}

    except Exception as e:
        print("DeepSeek EXCEPTION:", e)
        return None


# Временное хранилище ожидания суммы для кнопок
waiting_for_amount = {}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        secret = self.headers.get(WEBHOOK_SECRET_HEADER, "")
        if secret != WEBHOOK_SECRET:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return

        body = read_json(self)
        if body is None:
            return

        message = body.get("message")
        if not isinstance(message, dict):
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return

        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return

        text_raw = message.get("text") or ""
        if not str(text_raw).strip():
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return

        supabase = get_supabase_admin()

        # Currency
        currency_code = "RUB"
        try:
            user_settings = (
                supabase.table("user_settings")
                .select("currency")
                .eq("user_id", chat_id)
                .execute()
            )
            if user_settings.data:
                currency_code = user_settings.data[0].get("currency") or "RUB"
        except Exception as e:
            print("Supabase settings ERROR:", e)

        symbol = SYMBOLS.get(currency_code, "₽")

        # ОБРАБОТКА БЫСТРЫХ КНОПОК
        # Проверяем, ждём ли мы сумму от пользователя
        if chat_id in waiting_for_amount:
            button_name = waiting_for_amount[chat_id]
            amount = _extract_amount_simple(text_raw)
            
            if amount:
                # Сохраняем трату
                try:
                    supabase.table("expenses").insert({
                        "user_id": chat_id,
                        "amount": amount,
                        "category": "Разное",
                        "description": button_name,
                        "type": "expense",
                    }).execute()
                    
                    send_telegram(chat_id, f"💸 {button_name}: {amount}{symbol}\n✅ Сохранено", 
                                get_quick_buttons_keyboard(chat_id))
                    del waiting_for_amount[chat_id]
                except Exception as e:
                    print("Supabase insert ERROR:", e)
                    send_telegram(chat_id, "Ошибка при сохранении. Попробуй ещё раз.",
                                get_quick_buttons_keyboard(chat_id))
                    del waiting_for_amount[chat_id]
            else:
                send_telegram(chat_id, "Введи сумму числом:",
                            get_quick_buttons_keyboard(chat_id))
            
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return

        # Проверяем, это быстрая кнопка?
        try:
            quick_buttons_res = supabase.table("quick_buttons").select("buttons").eq("user_id", chat_id).execute()
            if quick_buttons_res.data and quick_buttons_res.data[0].get("buttons"):
                user_buttons = quick_buttons_res.data[0]["buttons"]
                
                for button in user_buttons:
                    if not button.strip():
                        continue
                    
                    # Проверяем формат "Название Сумма"
                    parts = button.strip().split()
                    if len(parts) >= 2:
                        button_name = " ".join(parts[:-1])
                        button_amount_str = parts[-1]
                        
                        # Если последняя часть - число, то это кнопка с суммой
                        if button_amount_str.isdigit():
                            button_amount = int(button_amount_str)
                            
                            # Проверяем точное совпадение
                            if text_raw.strip() == button:
                                try:
                                    supabase.table("expenses").insert({
                                        "user_id": chat_id,
                                        "amount": button_amount,
                                        "category": "Разное",
                                        "description": button_name,
                                        "type": "expense",
                                    }).execute()
                                    
                                    send_telegram(chat_id, f"💸 {button_name}: {button_amount}{symbol}\n✅ Сохранено",
                                                get_quick_buttons_keyboard(chat_id))
                                except Exception as e:
                                    print("Supabase insert ERROR:", e)
                                    send_telegram(chat_id, "Ошибка при сохранении. Попробуй ещё раз.",
                                                get_quick_buttons_keyboard(chat_id))
                                
                                self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return
                    
                    # Кнопка без суммы - совпадение с текстом
                    if text_raw.strip() == button.strip():
                        waiting_for_amount[chat_id] = button.strip()
                        send_telegram(chat_id, f"💸 {button.strip()}\nВведи сумму:",
                                    get_quick_buttons_keyboard(chat_id))
                        self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return
        
        except Exception as e:
            print("Quick buttons check ERROR:", e)

        # Обычная обработка (не быстрая кнопка)
        parsed = parse_with_deepseek(text_raw)
        used_ai = parsed is not None

        if not parsed:
            parsed = parse_fallback(text_raw)
            used_ai = False

        if parsed is None:
            send_telegram(chat_id, f"Напиши сумму (Валюта: {currency_code}). Например: 450 кофе",
                        get_quick_buttons_keyboard(chat_id))
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return

        amount = parsed["amount"]
        record_type = parsed["type"]
        category = parsed["category"]
        description = parsed["description"]

        # Save
        try:
            supabase.table("expenses").insert({
                "user_id": chat_id,
                "amount": amount,
                "category": category,
                "description": description,
                "type": record_type,
            }).execute()
        except Exception as e:
            print("Supabase insert ERROR:", e)
            send_telegram(chat_id, "Ошибка при сохранении. Попробуй ещё раз.",
                        get_quick_buttons_keyboard(chat_id))
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return

        icon = "💰" if record_type == "income" else "💸"
        mode = "🤖 AI" if used_ai else "🧩 Fallback"
        send_telegram(chat_id, f"{icon} {category}: {amount}{symbol}\n{mode}",
                    get_quick_buttons_keyboard(chat_id))

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
