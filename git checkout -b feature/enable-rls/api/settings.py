# ============================================
# api/settings.py (с RLS)
# ============================================
from http.server import BaseHTTPRequestHandler

from api.auth import require_user_id
from api.db import get_supabase_for_user
from api.utils import read_json, send_ok, send_error


ALLOWED_CURRENCIES = {"RUB", "USD", "EUR"}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        user_id = require_user_id(self)
        if user_id is None:
            return

        body = read_json(self)
        if body is None:
            return

        currency = body.get("currency")
        if not isinstance(currency, str):
            send_error(self, 400, "currency must be a string")
            return

        currency = currency.upper().strip()
        if currency not in ALLOWED_CURRENCIES:
            send_error(self, 400, f"Invalid currency. Allowed: {sorted(ALLOWED_CURRENCIES)}")
            return

        # CHANGED: Use RLS-aware client
        supabase = get_supabase_for_user(user_id)

        data = {
            "user_id": user_id,  # Still needed for upsert
            "currency": currency,
        }

        supabase.table("user_settings").upsert(data).execute()

        send_ok(self, {"currency": currency})


