from http.server import BaseHTTPRequestHandler
from datetime import datetime

from api.auth import require_user_id
from api.db import get_supabase
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
    # Accept "YYYY-MM-DD"
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except Exception:
        return False


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 1) Auth (NO user_id from body)
        user_id = require_user_id(self)
        if user_id is None:
            return  # 401 already sent

        # 2) Body safely
        body = read_json(self)
        if body is None:
            return  # error already sent

        text_raw = body.get("text", "")
        if not isinstance(text_raw, str):
            send_error(self, 400, "text must be a string")
            return

        text_lc = text_raw.lower()
        forced_type = body.get("type")
        custom_date = body.get("date")

        # 3) Amount
        amount = _extract_amount(text_lc)
        if amount is None:
            send_error(self, 400, "Amount not found")
            return

        # 4) Type + category (keep your MVP logic)
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

        # 5) Build record (description should keep original text)
        data = {
            "user_id": user_id,
            "amount": amount,
            "category": category,
            "description": text_raw.strip() if text_raw else "Запись",
            "type": record_type,
        }

        # Optional date (strict validation)
        if custom_date is not None:
            if not isinstance(custom_date, str) or not _is_iso_date(custom_date.strip()):
                send_error(self, 400, "date must be in YYYY-MM-DD format")
                return
            # NOTE: writing into created_at may be schema-dependent in Supabase.
            # If created_at is a timestamp, Supabase can accept "YYYY-MM-DD" but
            # it is safer to send full ISO. We keep existing behavior but validated.
            data["created_at"] = custom_date.strip()

        supabase = get_supabase()
        supabase.table("expenses").insert(data).execute()

        send_ok(self, {"message": "Saved", "category": category, "type": record_type, "amount": amount})