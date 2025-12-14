from http.server import BaseHTTPRequestHandler
import json
from supabase import create_client
import os

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Добавление или Удаление
        length = int(self.headers['Content-Length'])
        body = json.loads(self.rfile.read(length))
        
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        supabase = create_client(url, key)

        action = body.get('action') # 'add' или 'delete'

        if action == 'delete':
            supabase.table("subscriptions").delete().eq("id", body.get('id')).execute()
            msg = "Удалено"
        
        elif action == 'add':
            data = {
                "user_id": body.get('user_id'),
                "name": body.get('name'),
                "amount": body.get('amount'),
                "currency": body.get('currency'),
                "next_date": body.get('date'),
                "period": body.get('period')
            }
            supabase.table("subscriptions").insert(data).execute()
            msg = "Подписка добавлена"

        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"message": msg}).encode('utf-8'))

    def do_GET(self):
        # Получение списка (через GET параметры сложно, сделаем простой список всех подписок юзера)
        # В Vercel Python функциях GET параметры парсить муторно, 
        # но для MVP мы просто используем POST для получения списка тоже, или хакнем через URL
        # Давай лучше сделаем POST для всего, чтобы не мучиться с парсингом URL в stats
        self.send_response(405) # Метод не разрешен, используйте POST для всего в этом файле
        self.end_headers()
