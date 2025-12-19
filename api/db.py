# api/db.py
from __future__ import annotations

import os
from supabase import create_client, Client
from typing import Optional

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


def get_supabase_for_user(user_id: int) -> Client:
    """
    Возвращает клиент Supabase с настройкой пользователя для RLS.
    Используй ЭТУ функцию в обычных API endpoints.
    """
    client = get_supabase()
    set_user_context(client, user_id)
    return client


def set_user_context(client: Client, user_id: int) -> None:
    """Устанавливает текущего пользователя для RLS"""
    try:
        client.rpc('set_user_context', {'p_user_id': user_id}).execute()
    except Exception as e:
        print(f"Failed to set user context: {e}")


def get_supabase_admin() -> Client:
    """
    Возвращает клиент БЕЗ RLS для админских операций.
    Используй ТОЛЬКО для bot.py и cron.py!
    """
    return get_supabase()
