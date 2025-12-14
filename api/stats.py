from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json
from supabase import create_client
import os
from datetime import datetime, timedelta

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        user_id = query.get('user_id', [None])[0]
        period = query.get('period', ['all'])[0]

        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        supabase = create_client(url, key)

        if not user_id:
            self.send_response(200); self.end_headers(); self.wfile.write(b'{}'); return

        # 1. Валюта
        settings_res = supabase.table("user_settings").select("currency").eq("user_id", user_id).execute()
        currency = settings_res.data[0]['currency'] if settings_res.data else "RUB"

        # 2. Траты
        all_data = supabase.table("expenses").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        records = all_data.data

        # 3. ПОДПИСКИ (Новое!)
        subs_res = supabase.table("subscriptions").select("*").eq("user_id", user_id).order("next_date").execute()
        subs_data = subs_res.data

        # Считаем баланс
        total_balance = 0
        for item in records:
            if item.get('type') == 'income': total_balance += item['amount']
            else: total_balance -= item['amount']

        # Фильтры периода
        filtered_records = []
        now = datetime.utcnow()
        start_date = None
        if period == 'day': start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'week': start_date = now - timedelta(days=7)
        elif period == 'month': start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        for item in records:
            rec_date_str = item['created_at'].split('.')[0].replace('Z', '') 
            try:
                rec_date = datetime.fromisoformat(rec_date_str)
                if start_date and rec_date < start_date: continue 
                filtered_records.append(item)
            except: filtered_records.append(item)

        stats = {}
        period_income = 0; period_expense = 0
        for item in filtered_records:
            amt = item['amount']
            if item.get('type') == 'income': period_income += amt
            else:
                period_expense += amt
                cat = item['category']
                stats[cat] = stats.get(cat, 0) + amt

        response_data = {
            "currency": currency,
            "total_balance": total_balance,
            "period": { "income": period_income, "expense": period_expense },
            "chart": { "labels": list(stats.keys()), "data": list(stats.values()) },
            "history": filtered_records[:20],
            "subscriptions": subs_data # <-- Отдаем подписки
        }

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response_data, default=str).encode('utf-8'))
