from http.server import BaseHTTPRequestHandler
import json
import os
import requests
from supabase import create_client

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
SUPA_URL = os.environ.get("SUPABASE_URL")
SUPA_KEY = os.environ.get("SUPABASE_KEY")

def send_telegram(chat_id, text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)

# Словарик символов
SYMBOLS = {"RUB": "₽", "USD": "$", "EUR": "€"}

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(length))
            
            if 'message' not in body:
                self.send_response(200); self.end_headers(); self.wfile.write(b'OK'); return

            message = body['message']
            chat_id = message['chat']['id']
            text = message.get('text', '').lower()

            supabase = create_client(SUPA_URL, SUPA_KEY)

            # 1. Узнаем валюту юзера
            user_settings = supabase.table("user_settings").select("currency").eq("user_id", chat_id).execute()
            currency_code = "RUB"
            if user_settings.data:
                currency_code = user_settings.data[0]['currency']
            
            symbol = SYMBOLS.get(currency_code, "₽")

            # 2. Логика разбора (как раньше)
            amount = ''.join(filter(str.isdigit, text))
            if not amount:
                send_telegram(chat_id, f"Напиши сумму (Валюта: {currency_code})")
            else:
                amount = int(amount)
                category = "Разное"
                record_type = "expense"

                income_words = ["зарплата", "зп", "аванс", "приход", "перевод", "кэшбэк", "доход"]
                if any(w in text for w in income_words):
                    record_type = "income"
                    category = "Доход"
                elif record_type == "expense":
                    if any(w in text for w in ["еда", "мак", "продукты", "обед"]): category = "Еда"
                    elif any(w in text for w in ["такси", "бензин", "метро"]): category = "Транспорт"
                    elif any(w in text for w in ["дом", "жкх", "аренда"]): category = "Дом"
                    elif any(w in text for w in ["аптека", "врач"]): category = "Здоровье"
                    elif any(w in text for w in ["кафе", "бар", "кино"]): category = "Развлечения"

                data = {
                    "user_id": chat_id, 
                    "amount": amount, 
                    "category": category, 
                    "description": message.get('text', 'Запись'), 
                    "type": record_type
                }
                supabase.table("expenses").insert(data).execute()

                icon = "💰" if record_type == "income" else "💸"
                # Используем правильный символ
                send_telegram(chat_id, f"{icon} {category}: {amount}{symbol}")

        except Exception as e:
            print(f"Error: {e}")

        self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
