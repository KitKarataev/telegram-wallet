# api/db.py
# Supabase client factory with RLS support
#
# Env vars required:
#   SUPABASE_URL
#   SUPABASE_KEY (can be service_role or anon key)
#
# SECURITY:
# - RLS policies are ENABLED in Supabase
# - Each request sets app.current_user_id to scope queries
# - Service role key is used only for admin operations (cron, bot webhook)

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
    
    IMPORTANT: After getting the client, you MUST call set_user_context(user_id)
    before any database operations to properly scope RLS policies.
    """
    global _supabase
    if _supabase is None:
        url = _get_env("SUPABASE_URL")
        key = _get_env("SUPABASE_KEY")
        _supabase = create_client(url, key)
    return _supabase


def get_supabase_for_user(user_id: int) -> Client:
    """
    Returns a Supabase client with user context set for RLS.
    
    This is the RECOMMENDED way to get a client in API endpoints.
    
    Args:
        user_id: Telegram user ID (integer)
    
    Returns:
        Supabase client with RLS context configured
    
    Example:
        supabase = get_supabase_for_user(user_id)
        result = supabase.table("expenses").select("*").execute()
    """
    client = get_supabase()
    set_user_context(client, user_id)
    return client


def set_user_context(client: Client, user_id: int) -> None:
    """
    Sets the current user context for RLS policies.
    
    This configures the PostgreSQL session variable 'app.current_user_id'
    which is used by RLS policies to filter rows.
    
    Args:
        client: Supabase client instance
        user_id: Telegram user ID (integer)
    """
    # Execute a raw SQL command to set the session variable
    # This will be used by all RLS policies
    client.rpc('set_user_context', {'p_user_id': user_id}).execute()


def get_supabase_admin() -> Client:
    """
    Returns a Supabase client WITHOUT user context for admin operations.
    
    USE WITH EXTREME CAUTION. This bypasses RLS policies.
    Only use for:
    - Cron jobs that need to access all users' data
    - Bot webhook that writes data on behalf of users
    - Admin/analytics operations
    
    For regular API endpoints, use get_supabase_for_user() instead.
    """
    return get_supabase()


# ============================================
# SQL FUNCTION NEEDED IN SUPABASE
# ============================================
# Run this in Supabase SQL Editor:
#
# CREATE OR REPLACE FUNCTION set_user_context(p_user_id bigint)
# RETURNS void
# LANGUAGE plpgsql
# SECURITY DEFINER
# AS $$
# BEGIN
#   PERFORM set_config('app.current_user_id', p_user_id::text, false);
# END;
# $$;
#
# This function allows the service_role key to set the session variable
# that RLS policies will check.
# ============================================
