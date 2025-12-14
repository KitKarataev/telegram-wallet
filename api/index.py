from http.server import BaseHTTPRequestHandler
import json
from supabase import create_client
import os

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 1. Получаем данные от фронтенда
        length = int(self.headers['Content-Length'])
        body = json.loads(self.rfile.read(length))
        
        # 2. Подключаемся к базе (ключи возьмем из настроек Vercel)
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        supabase = create_client(url, key)

        # 3. Разбираем текст (простая логика)
        text = body.get('text', '').lower()
        amount = ''.join(filter(str.isdigit, text)) # вытаскиваем только цифры
        
        category = "Разное"
        if "еда" in text or "продукты" in text: category = "Еда"
        if "такси" in text: category = "Транспорт"
        
        # 4. Сохраняем
        if amount:
            data = {
                "user_id": body.get('user_id'),
                "amount": int(amount),
                "category": category,
                "description": text
            }
            supabase.table("expenses").insert(data).execute()
            msg = "Сохранено!"
        else:
            msg = "Не нашел сумму :("

        # 5. Отвечаем
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"message": msg}).encode('utf-8'))
