from http.server import BaseHTTPRequestHandler
import json
import os
import requests
from supabase import create_client

# Настройки
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
SUPA_URL = os.environ.get("SUPABASE_URL")
SUPA_KEY = os.environ.get("SUPABASE_KEY")

# Функция отправки сообщения в Телеграм
def send_telegram(chat_id, text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 1. Получаем сообщение от Телеграма
        try:
            length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(length))
            
            # Проверяем, что это сообщение, а не что-то другое
            if 'message' not in body:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'OK')
                return

            message = body['message']
            chat_id = message['chat']['id']
            text = message.get('text', '').lower()

            # 2. Логика распознавания (как раньше)
            amount = ''.join(filter(str.isdigit, text))
            
            if not amount:
                # Если цифр нет, просто игнорим или шлем помощь (но лучше молчать, чтобы не спамить)
                send_telegram(chat_id, "Не понял сумму. Напиши, например: 'Такси 500'")
            else:
                # Определяем категорию
                category = "Разное"
                if any(w in text for w in ["еда", "мак", "продукты", "обед", "ужин"]): category = "Еда"
                elif any(w in text for w in ["такси", "бензин", "метро", "авто"]): category = "Транспорт"
                elif any(w in text for w in ["дом", "жкх", "аренда"]): category = "Дом"
                elif any(w in text for w in ["кофе"]): category = "Кофе"

                # 3. Пишем в базу Supabase
                supabase = create_client(SUPA_URL, SUPA_KEY)
                data = {
                    "user_id": chat_id,
                    "amount": int(amount),
                    "category": category,
                    "description": message.get('text', 'Расход')
                }
                supabase.table("expenses").insert(data).execute()

                # 4. Отвечаем пользователю
                send_telegram(chat_id, f"✅ Записал: {category} {amount}₽")

        except Exception as e:
            print(f"Error: {e}")

        # Всегда отвечаем 200 OK, иначе Телеграм будет слать сообщение вечно
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')
