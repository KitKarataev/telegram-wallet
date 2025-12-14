from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json
from supabase import create_client
import os

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        user_id = query.get('user_id', [None])[0]

        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        supabase = create_client(url, key)

        if not user_id:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({}).encode('utf-8'))
            return

        # 1. Получаем валюту пользователя
        settings_res = supabase.table("user_settings").select("currency").eq("user_id", user_id).execute()
        currency = "RUB" # По умолчанию
        if settings_res.data:
            currency = settings_res.data[0]['currency']

        # 2. Получаем список трат
        response = supabase.table("expenses").select("*").eq("user_id", user_id).order("id", desc=True).execute()
        data = response.data

        # 3. Считаем
        stats = {}
        total_income = 0
        total_expense = 0

        for item in data:
            amt = item['amount']
            if item.get('type') == 'income':
                total_income += amt
            else:
                total_expense += amt
                cat = item['category']
                stats[cat] = stats.get(cat, 0) + amt

        response_data = {
            "currency": currency, # <-- ОТПРАВЛЯЕМ ВАЛЮТУ НА ФРОНТ
            "chart": {
                "labels": list(stats.keys()),
                "data": list(stats.values())
            },
            "balance": {
                "income": total_income,
                "expense": total_expense,
                "total": total_income - total_expense
            },
            "history": data[:15]
        }

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response_data, default=str).encode('utf-8'))
