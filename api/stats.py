from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta

from api.auth import require_user_id
from api.db import get_supabase
from api.utils import send_ok, send_error


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 1) Auth: user_id ONLY from verified Telegram initData
        user_id = require_user_id(self)
        if user_id is None:
            return  # 401 already sent

        # 2) Query params (no user_id here!)
        query = parse_qs(urlparse(self.path).query)
        period = (query.get("period", ["all"])[0] or "all").lower()
        if period not in ("all", "day", "week", "month"):
            send_error(self, 400, "Invalid period")
            return

        supabase = get_supabase()

        # 3) Currency from settings
        settings_res = (
            supabase.table("user_settings")
            .select("currency")
            .eq("user_id", user_id)
            .execute()
        )
        currency = settings_res.data[0].get("currency") if settings_res.data else "RUB"

        # 4) Expenses history (scoped by user_id)
        all_data = (
            supabase.table("expenses")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        records = all_data.data or []

        # 5) Subscriptions (scoped by user_id)
        subs_res = (
            supabase.table("subscriptions")
            .select("*")
            .eq("user_id", user_id)
            .order("next_date")
            .execute()
        )
        subs_data = subs_res.data or []

        # Helpers
        def to_number(x):
            try:
                if isinstance(x, bool):
                    return 0
                if isinstance(x, (int, float)):
                    return x
                if x is None:
                    return 0
                s = str(x).strip().replace(",", ".")
                return float(s) if "." in s else int(s)
            except Exception:
                return 0

        # 6) Total balance
        total_balance = 0
        for item in records:
            amt = to_number(item.get("amount"))
            if item.get("type") == "income":
                total_balance += amt
            else:
                total_balance -= amt

        # 7) Period filter
        now = datetime.utcnow()
        start_date = None
        if period == "day":
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start_date = now - timedelta(days=7)
        elif period == "month":
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        filtered_records = []
        for item in records:
            if not start_date:
                filtered_records.append(item)
                continue

            created_at = item.get("created_at")
            if not created_at:
                filtered_records.append(item)
                continue

            # tolerate "2025-01-01T12:00:00.000Z"
            rec_date_str = str(created_at).split(".")[0].replace("Z", "")
            try:
                rec_date = datetime.fromisoformat(rec_date_str)
                if rec_date >= start_date:
                    filtered_records.append(item)
            except Exception:
                # If parsing fails, keep it (safer UX than dropping silently)
                filtered_records.append(item)

        # 8) Stats for chart + period totals
        stats = {}
        period_income = 0
        period_expense = 0

        for item in filtered_records:
            amt = to_number(item.get("amount"))
            if item.get("type") == "income":
                period_income += amt
            else:
                period_expense += amt
                cat = item.get("category") or "Other"
                stats[cat] = stats.get(cat, 0) + amt

        response_data = {
            "currency": currency,
            "total_balance": total_balance,
            "period": {"income": period_income, "expense": period_expense},
            "chart": {"labels": list(stats.keys()), "data": list(stats.values())},
            "history": filtered_records[:20],
            "subscriptions": subs_data,
        }

        send_ok(self, response_data)