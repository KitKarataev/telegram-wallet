# ============================================
# api/index.py (с RLS)
# ============================================
from http.server import BaseHTTPRequestHandler
from datetime import datetime

from api.auth import require_user_id
from api.db import get_supabase_for_user
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
            "user_id": user_id,  # Still needed for insert
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

        # CHANGED: Use RLS-aware client
        supabase = get_supabase_for_user(user_id)
        supabase.table("expenses").insert(data).execute()

        send_ok(self, {"message": "Saved", "category": category, "type": record_type, "amount": amount})


# ============================================
# api/delete.py (с RLS)
# ============================================
from http.server import BaseHTTPRequestHandler

from api.auth import require_user_id
from api.db import get_supabase_for_user
from api.utils import read_json, send_ok, send_error


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        user_id = require_user_id(self)
        if user_id is None:
            return

        body = read_json(self)
        if body is None:
            return

        record_id = body.get("id")
        if record_id is None:
            send_error(self, 400, "Missing id")
            return

        # CHANGED: Use RLS-aware client
        # RLS policy automatically ensures user can only delete their own records
        supabase = get_supabase_for_user(user_id)

        res = (
            supabase.table("expenses")
            .delete()
            .eq("id", record_id)
            .execute()
        )

        deleted = res.data or []
        if not deleted:
            send_error(self, 404, "Record not found")
            return

        send_ok(self, {"message": "Deleted"})


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


# ============================================
# api/subs.py (с RLS)
# ============================================
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

        action = body.get("action")
        if action not in ("add", "delete", "list"):
            send_error(self, 400, "Invalid action. Use: add | delete | list")
            return

        # CHANGED: Use RLS-aware client
        supabase = get_supabase_for_user(user_id)

        if action == "list":
            res = (
                supabase.table("subscriptions")
                .select("*")
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

            # RLS automatically enforces ownership
            res = (
                supabase.table("subscriptions")
                .delete()
                .eq("id", sub_id)
                .execute()
            )

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
            "user_id": user_id,
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
        send_error(self, 405, "Method not allowed. Use POST with action=list/add/delete.")


# ============================================
# api/export.py (с RLS)
# ============================================
from http.server import BaseHTTPRequestHandler
import csv
import io

from api.auth import require_user_id
from api.db import get_supabase_for_user


def _to_number(x):
    try:
        if isinstance(x, bool):
            return 0
        if isinstance(x, (int, float)):
            return float(x)
        if x is None:
            return 0
        s = str(x).strip().replace(",", ".")
        return float(s)
    except Exception:
        return 0


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        user_id = require_user_id(self)
        if user_id is None:
            return

        # CHANGED: Use RLS-aware client
        supabase = get_supabase_for_user(user_id)

        # All queries automatically filtered by RLS
        expenses_res = (
            supabase.table("expenses")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
        expenses = expenses_res.data or []

        subs_res = (
            supabase.table("subscriptions")
            .select("*")
            .execute()
        )
        subs = subs_res.data or []

        settings_res = (
            supabase.table("user_settings")
            .select("currency")
            .execute()
        )
        settings = settings_res.data or []
        currency = settings[0].get("currency") if settings else "RUB"

        # Calculate totals
        total_inc = sum(_to_number(item.get("amount")) for item in expenses if item.get("type") == "income")
        total_exp = sum(_to_number(item.get("amount")) for item in expenses if item.get("type") != "income")
        balance = total_inc - total_exp

        # Build CSV
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")

        writer.writerow(["ОТЧЕТ О ФИНАНСАХ", f"Валюта: {currency}"])
        writer.writerow(["Общий Доход", total_inc])
        writer.writerow(["Общий Расход", total_exp])
        writer.writerow(["ТЕКУЩИЙ БАЛАНС", balance])
        writer.writerow([])

        if subs:
            writer.writerow(["АКТИВНЫЕ ПОДПИСКИ"])
            writer.writerow(["Название", "Сумма", "Период", "След. оплата"])
            for s in subs:
                period = (s.get("period") or "").lower()
                period_map = {
                    "monthly": "Месяц", "month": "Месяц",
                    "yearly": "Год", "year": "Год",
                    "weekly": "Неделя", "week": "Неделя",
                    "daily": "День", "day": "День"
                }
                period_name = period_map.get(period, period)

                writer.writerow([
                    s.get("name") or "",
                    _to_number(s.get("amount")),
                    period_name,
                    s.get("next_date") or "",
                ])
            writer.writerow([])

        writer.writerow(["ИСТОРИЯ ОПЕРАЦИЙ"])
        writer.writerow(["Дата", "Тип", "Категория", "Сумма", "Описание"])

        for item in expenses:
            created_at = str(item.get("created_at") or "")
            date_str = created_at.split("T")[0] if "T" in created_at else created_at[:10]

            t_type = "Доход" if item.get("type") == "income" else "Расход"
            writer.writerow([
                date_str,
                t_type,
                item.get("category") or "",
                _to_number(item.get("amount")),
                item.get("description") or "",
            ])

        csv_data = output.getvalue().encode("utf-8-sig")

        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="finance_report.csv"')
        self.send_header("Content-Length", str(len(csv_data)))
        self.end_headers()
        self.wfile.write(csv_data)
