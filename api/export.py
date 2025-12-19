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
        # 1) Auth (NO user_id from query params)
        user_id = require_user_id(self)
        if user_id is None:
            return  # 401 already sent by auth.py

        supabase = get_supabase_for_user(user_id)

        # 2) Fetch data (scoped by user_id)
        expenses_res = (
            supabase.table("expenses")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        expenses = expenses_res.data or []

        subs_res = (
            supabase.table("subscriptions")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        subs = subs_res.data or []

        settings_res = (
            supabase.table("user_settings")
            .select("currency")
            .eq("user_id", user_id)
            .execute()
        )
        settings = settings_res.data or []
        currency = settings[0].get("currency") if settings else "RUB"

        # 3) Totals
        total_inc = sum(_to_number(item.get("amount")) for item in expenses if item.get("type") == "income")
        total_exp = sum(_to_number(item.get("amount")) for item in expenses if item.get("type") != "income")
        balance = total_inc - total_exp

        # 4) Build CSV in memory
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")

        # SUMMARY
        writer.writerow(["ОТЧЕТ О ФИНАНСАХ", f"Валюта: {currency}"])
        writer.writerow(["Общий Доход", total_inc])
        writer.writerow(["Общий Расход", total_exp])
        writer.writerow(["ТЕКУЩИЙ БАЛАНС", balance])
        writer.writerow([])

        # SUBSCRIPTIONS
        if subs:
            writer.writerow(["АКТИВНЫЕ ПОДПИСКИ"])
            writer.writerow(["Название", "Сумма", "Период", "След. оплата"])
            for s in subs:
                period = (s.get("period") or "").lower()
                # Support both old and new values gracefully
                if period in ("month", "monthly"):
                    period_name = "Месяц"
                elif period in ("year", "yearly"):
                    period_name = "Год"
                elif period in ("week", "weekly"):
                    period_name = "Неделя"
                elif period in ("day", "daily"):
                    period_name = "День"
                else:
                    period_name = s.get("period") or ""

                writer.writerow([
                    s.get("name") or "",
                    _to_number(s.get("amount")),
                    period_name,
                    s.get("next_date") or "",
                ])
            writer.writerow([])

        # OPERATIONS HISTORY
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

        # 5) Send CSV
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="finance_report.csv"')
        self.send_header("Content-Length", str(len(csv_data)))
        self.end_headers()
        self.wfile.write(csv_data)
