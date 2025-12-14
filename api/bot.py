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

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(length))
            
            if 'message' not in body:
                self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
                return

            message = body['message']
            chat_id = message['chat']['id']
            text = message.get('text', '').lower()

            # 1. Ищем сумму
            amount = ''.join(filter(str.isdigit, text))
            if not amount:
                send_telegram(chat_id, "Где деньги? Напиши сумму, например: 'Зп 50000'")
            else:
                amount = int(amount)
                category = "Разное"
                record_type = "expense" # По умолчанию - расход

                # 2. Логика Доходов (Ключевые слова)
                income_words = ["зарплата", "зп", "аванс", "приход", "перевод", "кэшбэк", "доход"]
                if any(w in text for w in income_words):
                    record_type = "income"
                    category = "Доход"
                
                # 3. Логика Расходов (если это не доход)
                elif record_type == "expense":
                    if any(w in text for w in ["еда", "мак", "продукты", "обед"]): category = "Еда"
                    elif any(w in text for w in ["такси", "бензин", "метро"]): category = "Транспорт"
                    elif any(w in text for w in ["дом", "жкх", "аренда"]): category = "Дом"
                    elif any(w in text for w in ["аптека", "врач"]): category = "Здоровье"

                # 4. Пишем в базу
                supabase = create_client(SUPA_URL, SUPA_KEY)
                data = {
                    "user_id": chat_id,
                    "amount": amount,
                    "category": category,
                    "description": message.get('text', 'Запись'),
                    "type": record_type
                }
                supabase.table("expenses").insert(data).execute()

                # 5. Отвечаем красиво
                icon = "💰" if record_type == "income" else "💸"
                send_telegram(chat_id, f"{icon} {category}: {amount}₽")

        except Exception as e:
            print(f"Error: {e}")

        self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
