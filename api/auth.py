# api/auth.py
from __future__ import annotations

import os
import hmac
import hashlib
import json
from urllib.parse import parse_qsl

from api.utils import send_error


def _get_bot_token() -> str:
    # IMPORTANT: после ротации токена в BotFather
    # обязательно чтобы тут был новый токен.
    # Поддерживаем несколько имён переменных, чтобы не было рассинхрона.
    token = (
        os.environ.get("TELEGRAM_TOKEN")
        or os.environ.get("BOT_TOKEN")
        or os.environ.get("TG_TOKEN")
    )
    return token or ""


def _verify_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    """
    Verify Telegram WebApp initData according to official docs.
    Returns parsed dict of fields if valid, else None.
    """
    if not init_data or not bot_token:
        return None

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    # Data check string: sorted by key
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs.keys()))

    # secret_key = HMAC_SHA256("WebAppData", bot_token)
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        return None

    # Parse "user" JSON if present
    if "user" in pairs:
        try:
            pairs["user"] = json.loads(pairs["user"])
        except Exception:
            pass

    return pairs


def require_user_id(handler):
    """
    Reads Telegram initData from header X-Tg-Init-Data and returns user_id (int).
    On failure, sends 401 and returns None.
    """
    init_data = handler.headers.get("X-Tg-Init-Data", "") or ""
    bot_token = _get_bot_token()

    verified = _verify_telegram_init_data(init_data, bot_token)
    if not verified:
        send_error(handler, 401, "Unauthorized")
        return None

    user = verified.get("user")
    if isinstance(user, dict) and "id" in user:
        return user["id"]

    # fallback: if user JSON didn’t parse for some reason
    # try to parse it again
    try:
        if isinstance(user, str):
            u = json.loads(user)
            return u.get("id")
    except Exception:
        pass

    send_error(handler, 401, "Unauthorized")
    return None