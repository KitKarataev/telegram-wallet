from http.server import BaseHTTPRequestHandler
import json
from supabase import create_client
import os

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 1. Читаем, какую валюту хочет юзер
        length = int(self.headers['Content-Length'])
        body = json.loads(self.rfile.read(length))
        user_id = body.get('user_id')
        currency = body.get('currency') # "RUB", "USD" или "EUR"

        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        supabase = create_client(url, key)

        # 2. Сохраняем настройку (Upsert - обновить или создать)
        if user_id and currency:
            data = {"user_id": user_id, "currency": currency}
            supabase.table("user_settings").upsert(data).execute()

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')
