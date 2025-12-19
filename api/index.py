from http.server import BaseHTTPRequestHandler
from datetime import datetime

from api.auth import require_user_id
from api.db import get_supabase_for_user  # ИЗМЕНЕНО
from api.utils import read_json, send_ok, send_error


def _extract_amount(text: str):
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        amt = int(digits)
        if amt < 0 or amt > 10_000_000:
            return None
        return amt
    except Exception:
        return None


def _is_iso_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except Exception:
        return False


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        user_id = require_user_id(self)
        if user_id is None:
            return

        body = read_json(self)
        if body is None:
            return

        text_raw = body.get("text", "")
        if not isinstance(text_raw, str):
            send_error(self, 400, "text must be a string")
            return

        text_lc = text_raw.lower()
        forced_type = body.get("type")
        custom_date = body.get("date")

        amount = _extract_amount(text_lc)
        if amount is None:
            send_error(self, 400, "Amount not found")
            return

        category = "Разное"
        record_type = "expense"

        if forced_type == "income":
            record_type = "income"
            category = "Доход"
        else:
            if any(w in text_lc for w in ["зарплата", "зп", "аванс"]):
                record_type = "income"
                category = "Доход"
            elif "еда" in text_lc:
                category = "Еда"
            elif "такси" in text_lc:
                category = "Транспорт"

        data = {
            "user_id": user_id,
            "amount": amount,
            "category": category,
            "description": text_raw.strip() if text_raw else "Запись",
            "type": record_type,
        }

        if custom_date is not None:
            if not isinstance(custom_date, str) or not _is_iso_date(custom_date.strip()):
                send_error(self, 400, "date must be in YYYY-MM-DD format")
                return
            data["created_at"] = custom_date.strip()

        # ИЗМЕНЕНО: используем RLS-клиент
        supabase = get_supabase_for_user(user_id)
        supabase.table("expenses").insert(data).execute()

        send_ok(self, {"message": "Saved", "category": category, "type": record_type, "amount": amount})
