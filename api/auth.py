# api/auth.py
# Telegram WebApp initData verification + helper to require authenticated user_id.
#
# Expected request header:
#   X-Tg-Init-Data: <initData string from Telegram.WebApp.initData>
#
# Env vars required:
#   TELEGRAM_TOKEN = bot token (e.g. 123456:ABC-DEF...)
#
# Security notes:
# - Never trust user_id from client body/query params.
# - Always extract user_id ONLY from verified initData.

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl

HEADER_INIT_DATA = "X-Tg-Init-Data"


def _json_error(handler, status: int, message: str) -> None:
    """Minimal JSON error responder to avoid circular imports with utils.py."""
    payload = {"ok": False, "error": message}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _get_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


def verify_telegram_init_data(init_data: str, *, max_age_seconds: int = 24 * 60 * 60) -> Dict[str, Any]:
    """
    Verify Telegram WebApp initData signature (HMAC SHA-256).
    Returns parsed payload dict with keys from initData (user is parsed to dict).
    Raises ValueError on invalid signature / missing fields / expired auth_date.
    """
    if not init_data or not isinstance(init_data, str):
        raise ValueError("Missing initData")

    # initData is querystring-like: "query_id=...&user=...&auth_date=...&hash=..."
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise ValueError("Missing hash")

    # Build the data-check-string: "key=value" lines sorted by key
    check_str = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))

    # secret_key = sha256(bot_token)
    bot_token = _get_env("TELEGRAM_TOKEN")
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()

    calc_hash = hmac.new(secret_key, check_str.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        raise ValueError("Bad initData signature")

    # Optional freshness check
    auth_date = data.get("auth_date")
    if auth_date:
        try:
            auth_ts = int(auth_date)
        except Exception as e:
            raise ValueError("Invalid auth_date") from e
        now = int(time.time())
        if auth_ts > now + 60:  # clock skew guard
            raise ValueError("auth_date is in the future")
        if max_age_seconds > 0 and (now - auth_ts) > max_age_seconds:
            raise ValueError("initData expired")

    # Parse user JSON if present
    if "user" in data:
        try:
            data["user"] = json.loads(data["user"])
        except Exception as e:
            raise ValueError("Invalid user JSON") from e

    return data


def get_user_id_from_init_data(init_data: str) -> int:
    """
    Returns Telegram user id extracted from verified initData.
    Raises ValueError if user_id is unavailable.
    """
    payload = verify_telegram_init_data(init_data)
    user = payload.get("user")
    if not isinstance(user, dict):
        raise ValueError("No user in initData")
    uid = user.get("id")
    if uid is None:
        raise ValueError("No user.id in initData")
    try:
        return int(uid)
    except Exception as e:
        raise ValueError("Invalid user.id") from e


def require_user_id(handler) -> Optional[int]:
    """
    For BaseHTTPRequestHandler endpoints.

    - Reads X-Tg-Init-Data header
    - Verifies signature
    - Returns user_id (int) on success
    - On failure: responds 401 JSON and returns None
    """
    init_data = handler.headers.get(HEADER_INIT_DATA)
    if not init_data:
        _json_error(handler, 401, f"Missing {HEADER_INIT_DATA}")
        return None

    try:
        user_id = get_user_id_from_init_data(init_data)
        return user_id
    except Exception:
        # Intentionally do not leak details
        _json_error(handler, 401, "Unauthorized")
        return None