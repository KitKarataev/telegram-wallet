from http.server import BaseHTTPRequestHandler
import os
import requests
from supabase import create_client
from datetime import datetime, timedelta

# Секретный ключ, чтобы кто попало не дергал наш крон
CRON_SECRET = os.environ.get("CRON_SECRET", "my_secret_123")
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
SUPA_URL = os.environ.get("SUPABASE_URL")
SUPA_KEY = os.environ.get("SUPABASE_KEY")

def send_telegram(chat_id, text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Проверка защиты (Authorization: Bearer my_secret_123)
        auth_header = self.headers.get('Authorization', '')
        if f"Bearer {CRON_SECRET}" not in auth_header:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'Unauthorized')
            return

        supabase = create_client(SUPA_URL, SUPA_KEY)

        # 1. Ищем подписки, где дата списания = Сегодня + 3 дня
        target_date = (datetime.utcnow() + timedelta(days=3)).strftime('%Y-%m-%d')
        
        # Получаем список
        res = supabase.table("subscriptions").select("*").eq("next_date", target_date).execute()
        subs = res.data

        log = []

        for sub in subs:
            # 2. Шлем уведомление
            msg = f"🔔 Напоминание!\nЧерез 3 дня оплата подписки: {sub['name']}\nСумма: {sub['amount']} {sub['currency']}"
            send_telegram(sub['user_id'], msg)
            log.append(f"Notified {sub['user_id']} for {sub['name']}")

            # 3. Переносим дату на следующий период
            old_date = datetime.strptime(sub['next_date'], '%Y-%m-%d')
            new_date = old_date
            
            if sub['period'] == 'month':
                # Хитрый способ добавить месяц
                new_month = old_date.month % 12 + 1
                new_year = old_date.year + (old_date.month // 12)
                # Пытаемся сохранить день (например 30-е число), если нет - берем последнее число месяца
                try:
                    new_date = old_date.replace(year=new_year, month=new_month)
                except ValueError:
                    # Если было 31 января, а сл. месяц февраль
                    if new_month == 2:
                        new_date = old_date.replace(year=new_year, month=new_month, day=28)
                    else:
                        new_date = old_date.replace(year=new_year, month=new_month, day=30)
            
            elif sub['period'] == 'year':
                new_date = old_date.replace(year=old_date.year + 1)

            # Обновляем в базе
            supabase.table("subscriptions").update({"next_date": new_date.strftime('%Y-%m-%d')}).eq("id", sub['id']).execute()

        self.send_response(200)
        self.end_headers()
        self.wfile.write(f"Processed {len(subs)} subscriptions".encode('utf-8'))
