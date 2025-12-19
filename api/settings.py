from http.server import BaseHTTPRequestHandler

from api.auth import require_user_id
from api.db import get_supabase_for_user
from api.utils import read_json, send_ok, send_error


ALLOWED_CURRENCIES = {"RUB", "USD", "EUR"}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 1) Auth: user_id ONLY from Telegram initData
        user_id = require_user_id(self)
        if user_id is None:
            return  # 401 already sent

        # 2) Read JSON safely
        body = read_json(self)
        if body is None:
            return  # error already sent

        currency = body.get("currency")
        if not isinstance(currency, str):
            send_error(self, 400, "currency must be a string")
            return

        currency = currency.upper().strip()
        if currency not in ALLOWED_CURRENCIES:
            send_error(self, 400, f"Invalid currency. Allowed: {sorted(ALLOWED_CURRENCIES)}")
            return

        supabase = get_supabase_for_user(user_id)

        # 3) Upsert setting (scoped by user_id)
        data = {
            "user_id": user_id,
            "currency": currency,
        }

        supabase.table("user_settings").upsert(data).execute()

        send_ok(self, {"currency": currency})
