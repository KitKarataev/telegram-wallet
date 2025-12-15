# api/db.py
# Supabase client factory.
#
# Env vars required:
#   SUPABASE_URL
#   SUPABASE_KEY
#
# IMPORTANT:
# - SUPABASE_KEY is assumed to be a service_role key.
# - This means ALL access control must be enforced in backend code.
# - TODO: Enable RLS in Supabase and add policies per user_id.

from __future__ import annotations

import os
from supabase import create_client, Client

_supabase: Client | None = None


def _get_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_supabase() -> Client:
    """
    Returns a singleton Supabase client.
    """
    global _supabase
    if _supabase is None:
        url = _get_env("SUPABASE_URL")
        key = _get_env("SUPABASE_KEY")
        _supabase = create_client(url, key)
    return _supabase