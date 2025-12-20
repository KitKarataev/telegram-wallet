# api/scheduler.py - Планировщик напоминаний
from http.server import BaseHTTPRequestHandler
import os
import requests
from datetime import datetime

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_BASE_URL = os.environ.get("API_BASE_URL", "")


def send_proactive_message(chat_id: int, message: str):
    """Отправляет проактивное сообщение пользователю"""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        print(f"Send error: {e}")


def get_all_active_users():
    """Получает список всех активных пользователей"""
    # TODO: Реализовать получение из БД
    # Пока возвращаем хардкод для примера
    return [669864604]  # Твой user_id


class handler(BaseHTTPRequestHandler):
    """
    Вызывается по cron расписанию через Vercel Cron
    Настраивается в vercel.json
    """
    
    def do_GET(self):
        try:
            # Проверяем авторизацию (секретный ключ)
            auth_header = self.headers.get('Authorization', '')
            expected_secret = os.environ.get('CRON_SECRET', 'your-secret-key')
            
            if auth_header != f'Bearer {expected_secret}':
                self.send_response(401)
                self.end_headers()
                return
            
            # Получаем текущее время
            now = datetime.now()
            hour = now.hour
            
            print(f"[CRON] Running at {now.strftime('%Y-%m-%d %H:%M')}")
            
            # Напоминание в 19:00
            if hour == 19:
                message = (
                    "⏰ *Напоминание!*\n\n"
                    "Не забыл внести траты за день?\n\n"
                    "Напиши мне расходы или используй приложение 💰"
                )
                
                users = get_all_active_users()
                for user_id in users:
                    send_proactive_message(user_id, message)
                    print(f"[CRON] Sent reminder to user {user_id}")
            
            # Еженедельный анализ (Воскресенье в 20:00)
            if now.weekday() == 6 and hour == 20:
                message = (
                    "📊 *Еженедельный анализ*\n\n"
                    "Хочешь узнать как прошла неделя?\n\n"
                    "Напиши: _Проанализируй мою неделю_"
                )
                
                users = get_all_active_users()
                for user_id in users:
                    send_proactive_message(user_id, message)
                    print(f"[CRON] Sent weekly analysis to user {user_id}")
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
            
        except Exception as e:
            print(f"Cron error: {e}")
            self.send_response(500)
            self.end_headers()
