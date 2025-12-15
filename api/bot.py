from http.server import BaseHTTPRequestHandler
import json
import os
import requests
from supabase import create_client

# --- КОНФИГУРАЦИЯ ---
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
SUPA_URL = os.environ.get("SUPABASE_URL")
SUPA_KEY = os.environ.get("SUPABASE_KEY")

def send_telegram(chat_id, text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)

# Словарик валют
SYMBOLS = {"RUB": "₽", "USD": "$", "EUR": "€"}

# --- СЛОВАРЬ КАТЕГОРИЙ (EXPENSE MAP) ---
# Вынес отдельно, чтобы не захламлять основной цикл
EXPENSE_CATEGORIES = {
    "Алкоголь и Табак": [
        "красное и белое", "к&б", "бристоль", "vinlab", "винлаб", "winestyle", "simplewine", 
        "duty free", "heinemann", "dufry", "tabak", "tobacco", "smoke", "vape", "iqos", "glo", 
        "hookah", "shisha", "cigar", "wine", "spirits", "liquor", "beer", "brewery", "pub", 
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

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(length))
            
            if 'message' not in body:
                self.send_response(200); self.end_headers(); self.wfile.write(b'OK'); return

            message = body['message']
            chat_id = message['chat']['id']
            # Текст сразу в нижний регистр для удобства поиска
            text = message.get('text', '').lower()

            supabase = create_client(SUPA_URL, SUPA_KEY)

            # 1. Узнаем валюту юзера
            user_settings = supabase.table("user_settings").select("currency").eq("user_id", chat_id).execute()
            currency_code = "RUB"
            if user_settings.data:
                currency_code = user_settings.data[0]['currency']
            
            symbol = SYMBOLS.get(currency_code, "₽")

            # 2. Логика разбора
            amount = ''.join(filter(str.isdigit, text))
            
            if not amount:
                send_telegram(chat_id, f"Напиши сумму (Валюта: {currency_code})")
            else:
                amount = int(amount)
                category = "Разное" # Значение по умолчанию
                record_type = "expense"

                # Сначала проверяем на ДОХОД
                income_words = ["зарплата", "зп", "аванс", "приход", "перевод", "кэшбэк", "доход", "salary", "deposit"]
                
                if any(w in text for w in income_words):
                    record_type = "income"
                    category = "Доход"
                else:
                    # Если это РАСХОД, прогоняем через большой словарь
                    record_type = "expense"
                    found_category = False
                    
                    for cat_name, keywords in EXPENSE_CATEGORIES.items():
                        if any(k in text for k in keywords):
                            category = cat_name
                            found_category = True
                            break # Нашли категорию — останавливаем перебор
                    
                    if not found_category:
                        category = "Разное"

                # 3. Сохраняем в базу
                data = {
                    "user_id": chat_id, 
                    "amount": amount, 
                    "category": category, 
                    "description": message.get('text', 'Запись'), 
                    "type": record_type
                }
                supabase.table("expenses").insert(data).execute()

                icon = "💰" if record_type == "income" else "💸"
                
                # Отправляем ответ
                send_telegram(chat_id, f"{icon} {category}: {amount}{symbol}")

        except Exception as e:
            print(f"Error: {e}")

        self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
