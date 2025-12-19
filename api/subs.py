from http.server import BaseHTTPRequestHandler
from datetime import datetime

from api.auth import require_user_id
from api.db import get_supabase_for_user
from api.utils import read_json, send_ok, send_error


ALLOWED_PERIODS = {"daily", "weekly", "monthly", "yearly"}
ALLOWED_CURRENCIES = {"RUB", "USD", "EUR"}


def _to_number(x):
    try:
        if isinstance(x, bool):
            return None
        if isinstance(x, (int, float)):
            return float(x)
        if x is None:
            return None
        s = str(x).strip().replace(",", ".")
        return float(s)
    except Exception:
        return None


def _is_iso_date(value: str) -> bool:
    # Accept "YYYY-MM-DD" (recommended for next_date)
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except Exception:
        return False


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 1) Auth
        user_id = require_user_id(self)
        if user_id is None:
            return  # 401 already sent

        # 2) Body
        body = read_json(self)
        if body is None:
            return  # error already sent

        action = body.get("action")
        if action not in ("add", "delete", "list"):
            send_error(self, 400, "Invalid action. Use: add | delete | list")
            return

        supabase = get_supabase_for_user(user_id)

        # 3) Actions
        if action == "list":
            res = (
                supabase.table("subscriptions")
                .select("*")
                .eq("user_id", user_id)
                .order("next_date")
                .execute()
            )
            send_ok(self, {"subscriptions": res.data or []})
            return

        if action == "delete":
            sub_id = body.get("id")
            if sub_id is None:
                send_error(self, 400, "Missing id")
                return

            # Enforce ownership (fix IDOR)
            res = (
                supabase.table("subscriptions")
                .delete()
                .eq("id", sub_id)
                .eq("user_id", user_id)
                .execute()
            )

            # If nothing deleted, treat as not found (or not owned)
            deleted = res.data or []
            if not deleted:
                send_error(self, 404, "Subscription not found")
                return

            send_ok(self, {"message": "Deleted"})
            return

        # action == "add"
        name = body.get("name")
        if not isinstance(name, str) or not name.strip():
            send_error(self, 400, "name must be a non-empty string")
            return
        name = name.strip()

        amount = _to_number(body.get("amount"))
        if amount is None:
            send_error(self, 400, "amount must be numeric")
            return
        if amount < 0:
            send_error(self, 400, "amount must be >= 0")
            return

        currency = body.get("currency")
        if currency is None:
            currency = "RUB"
        if not isinstance(currency, str):
            send_error(self, 400, "currency must be a string")
            return
        currency = currency.upper().strip()
        if currency not in ALLOWED_CURRENCIES:
            send_error(self, 400, f"Invalid currency. Allowed: {sorted(ALLOWED_CURRENCIES)}")
            return

        next_date = body.get("date") or body.get("next_date")
        if not isinstance(next_date, str) or not _is_iso_date(next_date.strip()):
            send_error(self, 400, "date must be in YYYY-MM-DD format")
            return
        next_date = next_date.strip()

        period = body.get("period")
        if not isinstance(period, str):
            send_error(self, 400, "period must be a string")
            return
        period = period.lower().strip()
        if period not in ALLOWED_PERIODS:
            send_error(self, 400, f"Invalid period. Allowed: {sorted(ALLOWED_PERIODS)}")
            return

        data = {
            "user_id": user_id,          # NEVER from client
            "name": name,
            "amount": amount,
            "currency": currency,
            "next_date": next_date,
            "period": period,
        }

        supabase.table("subscriptions").insert(data).execute()
        send_ok(self, {"message": "Subscription added"})
        return

    def do_GET(self):
        # Keep current behavior: force POST for this endpoint
        send_error(self, 405, "Method not allowed. Use POST with action=list/add/delete.")
