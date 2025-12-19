# ============================================
# api/cron.py (с RLS - admin mode)
# ============================================
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timedelta, date
import calendar
import os
import requests
import logging

from api.db import get_supabase_admin  # CHANGED: Cron needs access to all users
from api.utils import send_ok, send_error


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _get_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


CRON_SECRET = _get_env("CRON_SECRET")
TG_TOKEN = _get_env("TELEGRAM_TOKEN")


def send_telegram(chat_id, text: str) -> None:
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Failed to send telegram to {chat_id}: {e}")


def _add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last_day = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last_day))


def _normalize_period(period: str) -> str:
    """Convert legacy period values to new format."""
    mapping = {
        "month": "monthly",
        "year": "yearly",
        "week": "weekly",
        "day": "daily"
    }
    p = (period or "").lower()
    return mapping.get(p, p)


def _next_date(old_date: date, period: str) -> date:
    p = _normalize_period(period)
    
    if p == "monthly":
        return _add_months(old_date, 1)
    if p == "yearly":
        return date(old_date.year + 1, old_date.month, min(old_date.day, calendar.monthrange(old_date.year + 1, old_date.month)[1]))
    if p == "weekly":
        return old_date + timedelta(days=7)
    if p == "daily":
        return old_date + timedelta(days=1)
    
    # Unknown period - keep same date
    logger.warning(f"Unknown period: {period}, keeping date unchanged")
    return old_date


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        auth_header = self.headers.get("Authorization", "")
        expected = f"Bearer {CRON_SECRET}"
        if auth_header != expected:
            send_error(self, 401, "Unauthorized")
            return

        # CHANGED: Use admin client
        supabase = get_supabase_admin()

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
                    logger.info(f"Notification sent to user {user_id} for subscription '{name}'")
                    notified += 1

                old = datetime.strptime(sub["next_date"], "%Y-%m-%d").date()
                new_d = _next_date(old, sub.get("period"))

                supabase.table("subscriptions").update(
                    {"next_date": new_d.strftime("%Y-%m-%d")}
                ).eq("id", sub["id"]).execute()

            except Exception as e:
                logger.error(f"Error processing subscription {sub.get('id')}: {e}")
                errors += 1

        logger.info(f"Cron completed: processed={processed}, notified={notified}, errors={errors}")

        send_ok(self, {
            "target_date": target_date,
            "processed": processed,
            "notified": notified,
            "errors": errors,
        })
