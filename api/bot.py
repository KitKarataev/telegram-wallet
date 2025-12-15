from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import os
import json
import re
import requests

from api.db import get_supabase
from api.utils import read_json


# ========= ENV =========
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


# ========= CONSTANTS =========
SYMBOLS = {"RUB": "₽", "USD": "$", "EUR": "€"}

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


# ========= TELEGRAM SEND =========
def send_telegram(chat_id, text: str) -> None:
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            raise RuntimeError(f"Telegram sendMessage failed: {r.status_code} {r.text}")
    except Exception as e:
        print("send_telegram ERROR:", e)


# ========= FALLBACK PARSER =========
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


# ========= DEEPSEEK PARSER =========
def parse_with_deepseek(text_raw: str) -> dict | None:
    if not DEEPSEEK_API_KEY:
        print("DeepSeek disabled: DEEPSEEK_API_KEY is empty in this deployment")
        return None

    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    prompt = f"""
Распарси финансовую запись и верни ТОЛЬКО JSON.

Текст:
{text_raw}

Формат ответа (строго):
{{
  "amount": 123,
  "type": "expense" | "income",
  "category": "Алкоголь и Табак" | "Продукты" | "Кафе и Рестораны" | "Транспорт" | "Авто и Бензин" | "Дом и Связь" | "Здоровье и Аптека" | "Одежда и Шопинг" | "Развлечения" | "Разное" | "Доход",
  "description": "коротко без суммы"
}}

Если суммы нет: {{"error":"no_amount"}}
"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "Ты парсер трат/доходов. Возвращай только JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 300,
        "stream": False,
        # Если DeepSeek не поддержит это поле — он вернёт ошибку, мы увидим в логах и уйдём в fallback.
        "response_format": {"type": "json_object"},
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        if r.status_code != 200:
            print("DeepSeek HTTP ERROR:", r.status_code, r.text)
            return None

        j = r.json()
        content = j["choices"][0]["message"].get("content", "") or ""
        data = json.loads(content)

        if isinstance(data, dict) and data.get("error") == "no_amount":
            return None

        amount = data.get("amount")
        if not isinstance(amount, int) or amount <= 0:
            print("DeepSeek parse invalid amount:", data)
            return None

        rtype = data.get("type")
        if rtype not in ("income", "expense"):
            rtype = "expense"

        allowed = {
            "Алкоголь и Табак","Продукты","Кафе и Рестораны","Транспорт","Авто и Бензин",
            "Дом и Связь","Здоровье и Аптека","Одежда и Шопинг","Развлечения","Разное","Доход"
        }
        category = data.get("category") or ("Доход" if rtype == "income" else "Разное")
        if category not in allowed:
            category = "Доход" if rtype == "income" else "Разное"

        desc = (data.get("description") or "").strip()
        desc = re.sub(r"\s+", " ", desc)
        if not desc:
            desc = re.sub(r"\s+", " ", text_raw).strip() if text_raw else "Запись"

        return {"amount": amount, "type": rtype, "category": category, "description": desc}

    except Exception as e:
        print("DeepSeek EXCEPTION:", e)
        return None


# ========= MAIN HANDLER =========
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 0) Webhook secret validation
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

        supabase = get_supabase()

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

        # Parse: DeepSeek -> fallback
        parsed = parse_with_deepseek(text_raw)
        used_ai = parsed is not None
        if not parsed:
            parsed = parse_fallback(text_raw)
            used_ai = False

        if parsed is None:
            send_telegram(chat_id, f"Напиши сумму (Валюта: {currency_code}). Например: 450 кофе")
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
            send_telegram(chat_id, "Ошибка при сохранении. Попробуй ещё раз.")
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return

        # Reply with indicator
        icon = "💰" if record_type == "income" else "💸"
        mode = "🤖 AI" if used_ai else "🧩 Fallback"
        send_telegram(chat_id, f"{icon} {category}: {amount}{symbol}\n{mode}")

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")