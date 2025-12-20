# api/bot.py - отладочная версия
from http.server import BaseHTTPRequestHandler
import os
import json


class handler(BaseHTTPRequestHandler):
    """Debug handler"""
    
    def do_POST(self):
        try:
            # Проверяем переменные окружения
            bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "NOT_FOUND")
            api_url = os.environ.get("API_BASE_URL", "NOT_FOUND")
            
            # Читаем тело
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode('utf-8'))
            
            message = data.get('message', {})
            chat_id = message.get('chat', {}).get('id')
            
            # Логируем что видим
            print("=" * 60)
            print(f"BOT_TOKEN: {bot_token[:20]}... (length: {len(bot_token)})")
            print(f"API_BASE_URL: {api_url}")
            print(f"Chat ID: {chat_id}")
            print("=" * 60)
            
            if bot_token == "NOT_FOUND":
                print("ERROR: TELEGRAM_BOT_TOKEN not set!")
                
                # Отправляем простой текст без библиотеки
                if chat_id:
                    print(f"Can't send message - no token")
            else:
                # Токен есть - пробуем отправить сообщение
                import requests
                
                telegram_api = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                
                response = requests.post(
                    telegram_api,
                    json={
                        "chat_id": chat_id,
                        "text": "✅ Бот работает! Токен найден!"
                    },
                    timeout=10
                )
                
                print(f"Telegram API response: {response.status_code}")
                print(f"Response: {response.text[:200]}")
            
            # Всегда отвечаем 200
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
            
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
            
            self.send_response(200)
            self.end_headers()
    
    def do_GET(self):
        """GET - показываем статус переменных"""
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "NOT_FOUND")
        api_url = os.environ.get("API_BASE_URL", "NOT_FOUND")
        
        status = f"""Bot Status:
        
TELEGRAM_BOT_TOKEN: {"✅ Found" if bot_token != "NOT_FOUND" else "❌ NOT FOUND"}
Token length: {len(bot_token)}
Token preview: {bot_token[:20]}...

API_BASE_URL: {api_url}

If token is NOT_FOUND, add it in Vercel:
Settings → Environment Variables → Add New
Name: TELEGRAM_BOT_TOKEN
Value: your_token_from_botfather

Then REDEPLOY the project!
"""
        
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(status.encode())
