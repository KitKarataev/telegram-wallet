from http.server import BaseHTTPRequestHandler
import json
from supabase import create_client
import os

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 1. Получаем ID записи, которую надо удалить
        length = int(self.headers['Content-Length'])
        body = json.loads(self.rfile.read(length))
        record_id = body.get('id')
        
        # 2. Подключаемся
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        supabase = create_client(url, key)

        # 3. Удаляем
        if record_id:
            supabase.table("expenses").delete().eq("id", record_id).execute()

        # 4. Ответ
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')
