from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta

from api.auth import require_user_id
from api.db import get_supabase_for_user
from api.utils import send_ok, send_error


MAX_RECORDS_FOR_CALC = 500  # safety cap


def to_number(x) -> float:
    try:
        if isinstance(x, bool) or x is None:
            return 0.0
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip().replace(",", ".")
        return float(s)
    except Exception:
        return 0.0


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        user_id = require_user_id(self)
        if user_id is None:
            return

        query = parse_qs(urlparse(self.path).query)
        period = (query.get("period", ["all"])[0] or "all").lower()
        if period not in ("all", "day", "week", "month"):
            send_error(self, 400, "Invalid period")
            return

        supabase = get_supabase_for_user(user_id)

        settings_res = (
            supabase.table("user_settings")
            .select("currency")
            .eq("user_id", user_id)
            .execute()
        )
        currency = settings_res.data[0].get("currency") if settings_res.data else "RUB"

        # Pull limited recent records (better than fetching everything)
        all_data = (
            supabase.table("expenses")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(MAX_RECORDS_FOR_CALC)
            .execute()
        )
        records = all_data.data or []

        subs_res = (
            supabase.table("subscriptions")
            .select("*")
            .eq("user_id", user_id)
            .order("next_date")
            .execute()
        )
        subs_data = subs_res.data or []

        # Total balance (over fetched window; for full balance use DB aggregate)
        total_balance = 0.0
        for item in records:
            amt = to_number(item.get("amount"))
            if item.get("type") == "income":
                total_balance += amt
            else:
                total_balance -= amt

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

            rec_date_str = str(created_at).split(".")[0].replace("Z", "")
            try:
                rec_date = datetime.fromisoformat(rec_date_str)
                if rec_date >= start_date:
                    filtered_records.append(item)
            except Exception:
                filtered_records.append(item)

        stats = {}
        period_income = 0.0
        period_expense = 0.0

        for item in filtered_records:
            amt = to_number(item.get("amount"))
            if item.get("type") == "income":
                period_income += amt
            else:
                period_expense += amt
                cat = item.get("category") or "Other"
                stats[cat] = stats.get(cat, 0.0) + amt

        # Optional: sort chart categories by spend desc
        sorted_items = sorted(stats.items(), key=lambda kv: kv[1], reverse=True)
        labels = [k for k, _ in sorted_items]
        values = [v for _, v in sorted_items]

        response_data = {
            "currency": currency,
            "total_balance": total_balance,
            "period": {"income": period_income, "expense": period_expense},
            "chart": {"labels": labels, "data": values},
            "history": filtered_records[:20],
            "subscriptions": subs_data,
        }

        send_ok(self, response_data)
