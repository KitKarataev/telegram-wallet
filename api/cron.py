from http.server import BaseHTTPRequestHandler
from datetime import datetime, timedelta, date
import calendar
import os
import requests

from api.db import get_supabase
from api.utils import send_ok, send_error


def _get_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# REQUIRED env vars (no defaults!)
CRON_SECRET = _get_env("CRON_SECRET")
TG_TOKEN = _get_env("TELEGRAM_TOKEN")


def send_telegram(chat_id, text: str) -> None:
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    # Add timeout to prevent hanging
    requests.post(url, json=payload, timeout=10)


def _add_months(d: date, months: int) -> date:
    """Add months preserving day when possible; clamp to last day of target month."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last_day = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last_day))


def _next_date(old_date: date, period: str) -> date:
    p = (period or "").lower()
    # Support legacy + new values
    if p in ("month", "monthly"):
        return _add_months(old_date, 1)
    if p in ("year", "yearly"):
        return date(old_date.year + 1, old_date.month, min(old_date.day, calendar.monthrange(old_date.year + 1, old_date.month)[1]))
    if p in ("week", "weekly"):
        return old_date + timedelta(days=7)
    if p in ("day", "daily"):
        return old_date + timedelta(days=1)
    # Unknown period -> keep same date (safe fallback)
    return old_date


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Strict auth: "Authorization: Bearer <CRON_SECRET>"
        auth_header = self.headers.get("Authorization", "")
        expected = f"Bearer {CRON_SECRET}"
        if auth_header != expected:
            send_error(self, 401, "Unauthorized")
            return

        supabase = get_supabase()

        # Find subscriptions with next_date = today + 3 days (UTC)
        target_date = (datetime.utcnow().date() + timedelta(days=3)).strftime("%Y-%m-%d")

        res = (
            supabase.table("subscriptions")
            .select("*")
            .eq("next_date", target_date)
            .execute()
        )
        subs = res.data or []

        processed = 0
        notified = 0
        errors = 0

        for sub in subs:
            processed += 1
            try:
                # 1) Notify
                name = sub.get("name") or ""
                amount = sub.get("amount")
                currency = sub.get("currency") or ""
                user_id = sub.get("user_id")

                if user_id is not None:
                    msg = (
                        "🔔 Напоминание!\n"
                        f"Через 3 дня оплата подписки: {name}\n"
                        f"Сумма: {amount} {currency}"
                    )
                    send_telegram(user_id, msg)
                    notified += 1

                # 2) Move next_date forward
                old = datetime.strptime(sub["next_date"], "%Y-%m-%d").date()
                new_d = _next_date(old, sub.get("period"))

                supabase.table("subscriptions").update(
                    {"next_date": new_d.strftime("%Y-%m-%d")}
                ).eq("id", sub["id"]).execute()

            except Exception:
                errors += 1
                # keep going, do not fail whole cron

        send_ok(self, {
            "target_date": target_date,
            "processed": processed,
            "notified": notified,
            "errors": errors,
        })