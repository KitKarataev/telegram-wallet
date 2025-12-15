from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import os
import json
import re
import requests
import hmac
import hashlib
from urllib.parse import parse_qsl

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

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


# ========= CONSTANTS =========
SYMBOLS = {"RUB": "₽", "USD": "$", "EUR": "€"}

EXPENSE_CATEGORIES = {
    "Алкоголь и Табак": [
        "красное и белое", "к&б", "пиво", "винчик", "винлаб", "winestyle", "simplewine",
        "duty free", "сижки", "dufry", "вино", "tobacco", "smoke", "vape", "iqos", "glo",
        "сиги", "сигареты", "cigar", "wine", "spirits", "liquor", "beer", "brewery", "pub",
        "alcohol", "drink", "alko", "off license", "bodega"
    ],
    "Продукты": [
        "пятерочка", "перекресток", "магнит", "ашан", "лента", "окей", "spar", "вкусвилл",
        "самокат", "lidl", "aldi", "carrefour", "tesco", "auchan", "kaufland", "rewe",
        "edeka", "biedronka", "zabka", "mercadona", "dia", "albert", "coop", "migros",
        "billa", "intermarche", "waitrose", "sainsbury", "jumbo", "grocery", "market",
        "supermarket", "baker", "bakery", "продукты", "овощи", "фрукты"
    ],
    "Кафе и Рестораны": [
        "шоколадница", "додо", "теремок", "якитория", "mcdonalds", "mac", "мак", "kfc",
        "burger", "subway", "starbucks", "costa", "pret", "dominos", "pizza", "sushi",
        "vapiano", "restaurant", "cafe", "coffee", "bistro", "bar", "uber eats", "wolt",
        "glovo", "bolt food", "deliveroo", "еда", "обед", "ужин", "ланч"
    ],
    "Транспорт": [
        "uber", "bolt", "freenow", "cabify", "gett", "yandex", "taxi", "lyft", "db", "bahn",
        "sncf", "renfe", "trenitalia", "metro", "bus", "tram", "train", "ticket", "billet",
        "flixbus", "ryanair", "wizz", "easyjet", "lufthansa", "aeroflot", "метро", "автобус",
        "проезд", "поезд"
    ],
    "Авто и Бензин": [
        "shell", "bp", "total", "esso", "eni", "repsol", "lukoil", "gazprom", "rosneft",
        "circle k", "fuel", "gas", "petrol", "tankstelle", "parking", "park", "garage",
        "toll", "vignette", "car wash", "sixt", "hertz", "avis", "бензин", "заправка", "парковка"
    ],
    "Дом и Связь": [
        "ikea", "jysk", "leroy", "obi", "castorama", "action", "home", "decor", "vodafone",
        "orange", "t-mobile", "telekom", "o2", "movistar", "tim", "mts", "beeline", "megafon",
        "internet", "mobile", "жкх", "аренда", "свет", "вода", "интернет", "связь", "ремонт"
    ],
    "Здоровье и Аптека": [
        "dm", "rossmann", "müller", "boots", "douglas", "sephora", "apotheke", "pharmacy",
        "farmacia", "apteka", "doctor", "clinic", "dental", "hospital", "аптека", "врач",
        "лекарства", "анализы"
    ],
    "Одежда и Шопинг": [
        "zara", "h&m", "uniqlo", "mango", "primark", "asos", "zalando", "wildberries", "wb",
        "ozon", "amazon", "ebay", "lamoda", "одежда", "обувь", "платье", "джинсы", "кроссовки"
    ],
    "Развлечения": [
        "cinema", "movie", "film", "kino", "theatre", "museum", "netflix", "spotify",
        "youtube", "apple", "steam", "playstation", "xbox", "кино", "театр", "подписка"
    ]
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


# ========= SIMPLE (FALLBACK) PARSER =========
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

    # description: original text without excessive spaces
    desc = re.sub(r"\s+", " ", text_raw).strip() if text_raw else "Запись"
    return {
        "amount": amount,
        "type": record_type,
        "category": category,
        "description": desc
    }


# ========= DEEPSEEK PARSER =========
def parse_with_deepseek(text_raw: str) -> dict | None:
    """
    Returns dict: {amount:int, type:'income'|'expense', category:str, description:str}
    or None if cannot parse.
    """
    if not DEEPSEEK_API_KEY:
        return None

    prompt = f"""
Твоя задача: распарсить финансовую запись пользователя и вернуть ТОЛЬКО JSON.

Вход (текст пользователя):
{text_raw}

Правила:
- amount: целое число > 0 (сумма в сообщении)
- type: "income" если это доход, иначе "expense"
- category: одна из категорий:
  ["Алкоголь и Табак","Продукты","Кафе и Рестораны","Транспорт","Авто и Бензин","Дом и Связь","Здоровье и Аптека","Одежда и Шопинг","Развлечения","Разное","Доход"]
- description: краткое описание (можно исходный текст, но без суммы)

Если сумму найти нельзя — верни JSON: {{"error":"no_amount"}}.
"""

    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "Ты парсер трат/доходов для финансового бота. Возвращай только JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        # DeepSeek поддерживает JSON output через response_format
        "response_format": {"type": "json_object"},
        "stream": False,
        "max_tokens": 300,
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code != 200:
            print("DeepSeek ERROR:", r.status_code, r.text)
            return None

        j = r.json()
        content = j["choices"][0]["message"].get("content", "") or ""
        data = json.loads(content)

        if isinstance(data, dict) and data.get("error") == "no_amount":
            return None

        # Validate
        amount = data.get("amount")
        if not isinstance(amount, int) or amount <= 0:
            return None

        rtype = data.get("type")
        if rtype not in ("income", "expense"):
            rtype = "expense"

        category = data.get("category") or ("Доход" if rtype == "income" else "Разное")
        allowed = {
            "Алкоголь и Табак","Продукты","Кафе и Рестораны","Транспорт","Авто и Бензин",
            "Дом и Связь","Здоровье и Аптека","Одежда и Шопинг","Развлечения","Разное","Доход"
        }
        if category not in allowed:
            category = "Доход" if rtype == "income" else "Разное"

        desc = data.get("description") or ""
        desc = re.sub(r"\s+", " ", str(desc)).strip()
        if not desc:
            desc = re.sub(r"\s+", " ", text_raw).strip() if text_raw else "Запись"

        return {"amount": amount, "type": rtype, "category": category, "description": desc}

    except Exception as e:
        print("DeepSeek parse exception:", e)
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

        # 1) Parse Telegram update JSON
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
        text_lc = str(text_raw).strip()
        if not text_lc:
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return

        supabase = get_supabase()

        # 2) User currency
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

        # 3) Parse message: DeepSeek -> fallback
        parsed = parse_with_deepseek(text_raw) or parse_fallback(text_raw)
        if parsed is None:
            send_telegram(chat_id, f"Напиши сумму (Валюта: {currency_code}). Например: 450 кофе")
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return

        amount = parsed["amount"]
        record_type = parsed["type"]
        category = parsed["category"]
        description = parsed["description"]

        # 4) Save
        try:
            data = {
                "user_id": chat_id,
                "amount": amount,
                "category": category,
                "description": description,
                "type": record_type,
            }
            supabase.table("expenses").insert(data).execute()
        except Exception as e:
            print("Supabase insert ERROR:", e)
            send_telegram(chat_id, "Ошибка при сохранении. Попробуй ещё раз.")
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return

        # 5) Reply
        icon = "💰" if record_type == "income" else "💸"
        send_telegram(chat_id, f"{icon} {category}: {amount}{symbol}")

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")