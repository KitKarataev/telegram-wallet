from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import csv
import io
from supabase import create_client
import os

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 1. Получаем ID юзера
        query = parse_qs(urlparse(self.path).query)
        user_id = query.get('user_id', [None])[0]

        if not user_id:
            self.send_response(400)
            self.wfile.write(b'User ID required')
            return

        # 2. Подключаемся к базе
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        supabase = create_client(url, key)

        # 3. Забираем данные
        # Расходы/Доходы
        expenses = supabase.table("expenses").select("*").eq("user_id", user_id).order("created_at", desc=True).execute().data
        # Подписки
        subs = supabase.table("subscriptions").select("*").eq("user_id", user_id).execute().data
        # Настройки (для валюты)
        settings = supabase.table("user_settings").select("currency").eq("user_id", user_id).execute().data
        currency = settings[0]['currency'] if settings else "RUB"

        # 4. Считаем Итоги (Баланс)
        total_inc = sum(item['amount'] for item in expenses if item.get('type') == 'income')
        total_exp = sum(item['amount'] for item in expenses if item.get('type') != 'income')
        balance = total_inc - total_exp

        # 5. Генерируем CSV в памяти
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';') # Точка с запятой лучше для Excel в РФ/Европе

        # БЛОК 1: СВОДКА
        writer.writerow(['ОТЧЕТ О ФИНАНСАХ', f'Валюта: {currency}'])
        writer.writerow(['Общий Доход', total_inc])
        writer.writerow(['Общий Расход', total_exp])
        writer.writerow(['ТЕКУЩИЙ БАЛАНС', balance])
        writer.writerow([]) # Пустая строка для отступа

        # БЛОК 2: ПОДПИСКИ
        if subs:
            writer.writerow(['АКТИВНЫЕ ПОДПИСКИ'])
            writer.writerow(['Название', 'Сумма', 'Период', 'След. оплата'])
            for s in subs:
                period_name = "Месяц" if s['period'] == 'month' else "Год"
                writer.writerow([s['name'], s['amount'], period_name, s['next_date']])
            writer.writerow([])

        # БЛОК 3: ИСТОРИЯ ОПЕРАЦИЙ
        writer.writerow(['ИСТОРИЯ ОПЕРАЦИЙ'])
        writer.writerow(['Дата', 'Тип', 'Категория', 'Сумма', 'Описание'])
        
        for item in expenses:
            # Красивая дата
            date_str = item['created_at'].split('T')[0]
            t_type = "Доход" if item.get('type') == 'income' else "Расход"
            writer.writerow([
                date_str,
                t_type,
                item['category'],
                item['amount'],
                item['description']
            ])

        # 6. Отдаем файл
        # Важно: utf-8-sig чтобы Excel понимал кириллицу
        csv_data = output.getvalue().encode('utf-8-sig')

        self.send_response(200)
        # Говорим браузеру: "Это файл, скачай его как report.csv"
        self.send_header('Content-Type', 'text/csv; charset=utf-8')
        self.send_header('Content-Disposition', 'attachment; filename="finance_report.csv"')
        self.end_headers()
        self.wfile.write(csv_data)
