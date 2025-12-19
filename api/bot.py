from http.server import BaseHTTPRequestHandler

from api.auth import require_user_id
from api.db import get_supabase_for_user
from api.utils import read_json, send_ok, send_error


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Получить быстрые кнопки пользователя"""
        user_id = require_user_id(self)
        if user_id is None:
            return

        supabase = get_supabase_for_user(user_id)

        try:
            res = supabase.table("quick_buttons").select("*").eq("user_id", user_id).execute()
            
            if res.data and len(res.data) > 0:
                buttons = res.data[0].get("buttons", [])
            else:
                buttons = []
            
            send_ok(self, {"buttons": buttons})
        except Exception as e:
            print(f"Error loading quick buttons: {e}")
            send_error(self, 500, "Failed to load buttons")

    def do_POST(self):
        """Сохранить быстрые кнопки пользователя"""
        user_id = require_user_id(self)
        if user_id is None:
            return

        body = read_json(self)
        if body is None:
            return

        buttons = body.get("buttons")
        if not isinstance(buttons, list):
            send_error(self, 400, "buttons must be an array")
            return

        # Максимум 6 кнопок
        if len(buttons) > 6:
            send_error(self, 400, "Maximum 6 buttons allowed")
            return

        # Валидация каждой кнопки
        for button in buttons:
            if not isinstance(button, str):
                send_error(self, 400, "Each button must be a string")
                return
            if len(button) > 50:
                send_error(self, 400, "Button text too long (max 50 chars)")
                return

        supabase = get_supabase_for_user(user_id)

        try:
            # Upsert (insert or update)
            data = {
                "user_id": user_id,
                "buttons": buttons
            }
            
            supabase.table("quick_buttons").upsert(data).execute()
            
            send_ok(self, {"message": "Buttons saved", "buttons": buttons})
        except Exception as e:
            print(f"Error saving quick buttons: {e}")
            send_error(self, 500, "Failed to save buttons")
