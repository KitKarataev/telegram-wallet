from http.server import BaseHTTPRequestHandler
import json
from supabase import create_client
import os

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 1. Подключаемся к базе
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        supabase = create_client(url, key)

        # 2. Забираем ВСЕ расходы
        # (В реальном проекте тут нужен фильтр по user_id, но пока берем всё)
        response = supabase.table("expenses").select("*").execute()
        data = response.data

        # 3. Считаем сумму по категориям (Python магия)
        stats = {}
        for item in data:
            cat = item['category']
            amount = item['amount']
            if cat in stats:
                stats[cat] += amount
            else:
                stats[cat] = amount

        # 4. Готовим данные для графика
        labels = list(stats.keys())
        values = list(stats.values())

        # 5. Отправляем ответ
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"labels": labels, "data": values}).encode('utf-8'))
