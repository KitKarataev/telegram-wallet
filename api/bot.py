from http.server import BaseHTTPRequestHandler
import os
import requests

from api.db import get_supabase
from api.utils import read_json


def _get_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# REQUIRED env vars
TG_TOKEN = _get_env("TELEGRAM_TOKEN")
WEBHOOK_SECRET = _get_env("TELEGRAM_WEBHOOK_SECRET")

# Telegram will send this header if you set secret_token when setting webhook
WEBHOOK_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

# Currency symbols
SYMBOLS = {"RUB": "₽", "USD": "$", "EUR": "€"}

# Category keywords map (unchanged)
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


def send_telegram(chat_id, text: str) -> None:
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    # timeout prevents hanging the serverless function
    requests.post(url, json=payload, timeout=10)


def _extract_amount(text: str):
    # Keep your MVP behavior: digits only
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        amt = int(digits)
        # basic sanity limit to reduce abuse
        if amt < 0 or amt > 10_000_000:
            return None
        return amt
    except Exception:
        return None


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 0) Webhook secret validation (critical)
        secret = self.headers.get(WEBHOOK_SECRET_HEADER, "")
        if secret != WEBHOOK_SECRET:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return

        # 1) Parse JSON safely (limits + errors handled)
        body = read_json(self)
        if body is None:
            return  # 400 already sent

        # Telegram updates may contain many fields; we only handle 'message'
        message = body.get("message")
        if not isinstance(message, dict):
            # Always ACK Telegram to avoid retries, but do nothing
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            return

        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            return

        text_raw = message.get("text") or ""
        text = str(text_raw).lower()

        supabase = get_supabase()

        # 2) Get user currency
        user_settings = (
            supabase.table("user_settings")
            .select("currency")
            .eq("user_id", chat_id)
            .execute()
        )
        currency_code = "RUB"
        if user_settings.data:
            currency_code = user_settings.data[0].get("currency") or "RUB"

        symbol = SYMBOLS.get(currency_code, "₽")

        # 3) Parse amount
        amount = _extract_amount(text)
        if amount is None:
            send_telegram(chat_id, f"Напиши сумму (Валюта: {currency_code})")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            return

        # 4) Determine category + type
        category = "Разное"
        record_type = "expense"

        income_words = ["зарплата", "зп", "аванс", "приход", "перевод", "кэшбэк", "доход", "salary", "deposit"]
        if any(w in text for w in income_words):
            record_type = "income"
            category = "Доход"
        else:
            for cat_name, keywords in EXPENSE_CATEGORIES.items():
                if any(k in text for k in keywords):
                    category = cat_name
                    break

        # 5) Save to DB
        data = {
            "user_id": chat_id,
            "amount": amount,
            "category": category,
            "description": str(text_raw) if text_raw else "Запись",
            "type": record_type,
        }
        supabase.table("expenses").insert(data).execute()

        icon = "💰" if record_type == "income" else "💸"
        send_telegram(chat_id, f"{icon} {category}: {amount}{symbol}")

        # 6) ACK Telegram
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")