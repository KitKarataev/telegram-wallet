from http.server import BaseHTTPRequestHandler

from api.auth import require_user_id
from api.db import get_supabase
from api.utils import read_json, send_ok, send_error


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 1) Auth
        user_id = require_user_id(self)
        if user_id is None:
            return  # 401 already sent

        # 2) Body
        body = read_json(self)
        if body is None:
            return  # error already sent

        record_id = body.get("id")
        if record_id is None:
            send_error(self, 400, "Missing id")
            return

        supabase = get_supabase()

        # 3) Delete with ownership check (fix IDOR)
        res = (
            supabase.table("expenses")
            .delete()
            .eq("id", record_id)
            .eq("user_id", user_id)
            .execute()
        )

        deleted = res.data or []
        if not deleted:
            # Either not found or not owned by this user
            send_error(self, 404, "Record not found")
            return

        send_ok(self, {"message": "Deleted"})