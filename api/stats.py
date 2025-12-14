from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json
from supabase import create_client
import os

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 1. Читаем user_id из ссылки (адреса)
        query = parse_qs(urlparse(self.path).query)
        user_id = query.get('user_id', [None])[0]

        # 2. Подключаемся к базе
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        supabase = create_client(url, key)

        if not user_id:
            data = []
        else:
            # 3. Забираем данные ТОЛЬКО этого юзера
            # Сортируем: новые сверху (desc)
            response = supabase.table("expenses").select("*").eq("user_id", user_id).order("id", desc=True).execute()
            data = response.data

        # 4. Считаем сумму для Графика
        stats = {}
        for item in data:
            cat = item['category']
            stats[cat] = stats.get(cat, 0) + item['amount']

        # 5. Готовим Историю (последние 5 штук)
        last_transactions = data[:5] 

        # 6. Отправляем всё вместе
        response_data = {
            "chart": {
                "labels": list(stats.keys()),
                "data": list(stats.values())
            },
            "history": last_transactions
        }

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response_data, default=str).encode('utf-8'))
