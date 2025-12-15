# api/utils.py
# Shared helpers for API endpoints:
# - standardized JSON responses
# - safe JSON body reading with size limits
#
# Response format:
#   Success: { "ok": true, "data": ... }
#   Error:   { "ok": false, "error": "message" }

from __future__ import annotations

import json
from typing import Any, Dict, Optional

DEFAULT_MAX_BODY_BYTES = 32 * 1024  # 32 KB


def send_json(handler, status: int, payload: Dict[str, Any]) -> None:
    """
    Send a JSON response with correct headers.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def send_ok(handler, data: Any, status: int = 200) -> None:
    send_json(handler, status, {"ok": True, "data": data})


def send_error(handler, status: int, message: str) -> None:
    send_json(handler, status, {"ok": False, "error": message})


def read_json(handler, *, max_bytes: int = DEFAULT_MAX_BODY_BYTES) -> Optional[Dict[str, Any]]:
    """
    Safely read and parse JSON request body.

    - Enforces Content-Length
    - Limits body size to max_bytes
    - Returns dict on success
    - On error: sends JSON response and returns None
    """
    content_length = handler.headers.get("Content-Length")
    if content_length is None:
        send_error(handler, 400, "Missing Content-Length")
        return None

    try:
        length = int(content_length)
    except ValueError:
        send_error(handler, 400, "Invalid Content-Length")
        return None

    if length <= 0:
        send_error(handler, 400, "Empty request body")
        return None

    if length > max_bytes:
        send_error(handler, 413, "Request body too large")
        return None

    try:
        raw = handler.rfile.read(length)
    except Exception:
        send_error(handler, 400, "Failed to read request body")
        return None

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        send_error(handler, 400, "Invalid JSON")
        return None

    if not isinstance(data, dict):
        send_error(handler, 400, "JSON body must be an object")
        return None

    return data