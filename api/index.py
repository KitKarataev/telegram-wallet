from http.server import BaseHTTPRequestHandler
import json
from supabase import create_client
import os

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers['Content-Length'])
        body = json.loads(self.rfile.read(length))
        
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        supabase = create_client(url, key)

        text = body.get('text', '').lower()
        forced_type = body.get('type') # Получаем тип от кнопки (если есть)
        
        amount = ''.join(filter(str.isdigit, text))
        
        category = "Разное"
        record_type = "expense"

        # Если тип принудительно указан с фронта (нажали кнопку "Доход")
        if forced_type == "income":
            record_type = "income"
            category = "Доход"
        else:
            # Иначе пытаемся угадать по тексту
            if any(w in text for w in ["зарплата", "зп", "аванс"]): 
                record_type = "income"
                category = "Доход"
            elif "еда" in text: category = "Еда"
            elif "такси" in text: category = "Транспорт"

        if amount:
            data = {
                "user_id": body.get('user_id'),
                "amount": int(amount),
                "category": category,
                "description": text,
                "type": record_type
            }
            supabase.table("expenses").insert(data).execute()
            msg = "Сохранено!"
        else:
            msg = "Сумма не найдена"

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"message": msg}).encode('utf-8'))
