from http.server import BaseHTTPRequestHandler

from api.auth import require_user_id
from api.db import get_supabase_for_user  # ИЗМЕНЕНО
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

        # ИЗМЕНЕНО: RLS автоматически проверит владельца
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
