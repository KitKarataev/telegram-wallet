# api/bot.py
from http.server import BaseHTTPRequestHandler
import os
import json
import requests
from datetime import datetime

from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, ContextTypes

# Конфигурация
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_BASE_URL = os.environ.get("API_BASE_URL", "")
WEBAPP_URL = f"{API_BASE_URL}/index.html"

# AI режим
AI_WAITING_USERS = {}

# Категории
EXPENSE_CATEGORIES = {
    "Продукты": ["пятерочка", "перекресток", "магнит", "ашан", "лента", "вкусвилл", "lidl", "aldi", "carrefour", "mercadona"],
    "Кафе и Рестораны": ["кофе", "cafe", "restaurant", "burger", "pizza", "sushi"],
    "Транспорт": ["uber", "bolt", "taxi", "metro"],
}

INCOME_CATEGORIES = {
    "Зарплата": ["зарплата", "salary", "зп"],
    "Фриланс": ["фриланс", "freelance"],
}


def parse_expense_text(text: str) -> dict | None:
    """Парсит текст вида: 500 Кофе"""
    text = text.strip()
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2:
        return None
    
    amount = None
    description = None
    
    try:
        amount = float(parts[0].replace(',', '.'))
        description = parts[1]
    except ValueError:
        try:
            amount = float(parts[1].replace(',', '.'))
            description = parts[0]
        except ValueError:
            return None
    
    if amount is None or description is None:
        return None
    
    category = "Разное"
    desc_lower = description.lower()
    
    for cat, keywords in EXPENSE_CATEGORIES.items():
        if any(kw in desc_lower for kw in keywords):
            category = cat
            break
    
    return {"amount": amount, "description": description, "category": category}


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех сообщений"""
    
    if not update.message:
        return
    
    text = update.message.text
    if not text:
        return
    
    user_id = update.effective_user.id
    
    # Команды
    if text == "/start":
        keyboard = [[KeyboardButton(text="💰 Открыть приложение", web_app=WebAppInfo(url=WEBAPP_URL))]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "👋 *Привет! Я твой финансовый помощник.*\n\n"
            "📱 Нажми кнопку ниже\n"
            "💬 Или используй команды:\n\n"
            "/help - помощь\n"
            "/ai - 🤖 AI ассистент\n"
            "/stats - статистика",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    if text == "/help":
        await update.message.reply_text(
            "🤖 *Команды:*\n\n"
            "/start - главное меню\n"
            "/stats - статистика\n"
            "/ai - AI помощник\n"
            "/cancel - выход из AI\n\n"
            "*Быстрое добавление:*\n"
            "500 Кофе - расход\n"
            "+ 50000 Зарплата - доход",
            parse_mode='Markdown'
        )
        return
    
    if text == "/stats":
        try:
            response = requests.get(
                f"{API_BASE_URL}/api/stats?period=month",
                headers={"X-Tg-Init-Data": f"user={user_id}"},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json().get('data', {})
                balance = data.get('total_balance', 0)
                income = data.get('period', {}).get('income', 0)
                expense = data.get('period', {}).get('expense', 0)
                
                await update.message.reply_text(
                    f"📊 *Статистика:*\n\n"
                    f"💰 Баланс: {balance} ₽\n"
                    f"📈 Доход: +{income} ₽\n"
                    f"📉 Расход: -{expense} ₽",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text("❌ Не удалось загрузить")
        except Exception as e:
            print(f"Stats error: {e}")
            await update.message.reply_text("❌ Ошибка")
        return
    
    if text == "/ai":
        AI_WAITING_USERS[user_id] = True
        await update.message.reply_text(
            "🤖 *AI Ассистент активирован!*\n\n"
            "Задай вопрос:\n"
            "• Где я больше всего трачу?\n"
            "• Как сэкономить?\n\n"
            "_Выход: /cancel_",
            parse_mode='Markdown'
        )
        return
    
    if text == "/cancel":
        if user_id in AI_WAITING_USERS:
            del AI_WAITING_USERS[user_id]
            await update.message.reply_text("✅ AI деактивирован")
        else:
            await update.message.reply_text("AI не был активен")
        return
    
    # AI режим
    if user_id in AI_WAITING_USERS:
        await update.message.chat.send_action(action="typing")
        
        try:
            response = requests.post(
                f"{API_BASE_URL}/api/ai-assistant",
                json={"message": text},
                headers={"X-Tg-Init-Data": f"user={user_id}"},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json().get('data', {})
                ai_message = data.get('message', 'Нет ответа')
                await update.message.reply_text(f"🤖 *AI:*\n\n{ai_message}", parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Ошибка AI")
        except Exception as e:
            print(f"AI error: {e}")
            await update.message.reply_text("❌ AI недоступен")
        return
    
    # Парсинг расходов/доходов
    is_income = text.startswith('+')
    if is_income:
        text = text[1:].strip()
    
    parsed = parse_expense_text(text)
    
    if not parsed:
        await update.message.reply_text(
            "❓ Не понял.\n\n"
            "Попробуй:\n"
            "500 Кофе - расход\n"
            "+ 50000 Зарплата - доход",
            parse_mode='Markdown'
        )
        return
    
    # Добавляем операцию
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/index",
            headers={"X-Tg-Init-Data": f"user={user_id}"},
            json={
                "text": f"{parsed['amount']} {parsed['description']}",
                "type": "income" if is_income else "expense",
                "date": datetime.now().strftime('%Y-%m-%d')
            },
            timeout=10
        )
        
        if response.status_code == 200:
            emoji = "📈" if is_income else "💸"
            sign = "+" if is_income else "-"
            
            await update.message.reply_text(
                f"✅ Добавлено:\n"
                f"{emoji} {sign}{parsed['amount']} ₽\n"
                f"📝 {parsed['description']}\n"
                f"📂 {parsed['category']}"
            )
        else:
            await update.message.reply_text("❌ Не удалось добавить")
    
    except Exception as e:
        print(f"Add error: {e}")
        await update.message.reply_text("❌ Ошибка")


class handler(BaseHTTPRequestHandler):
    """Webhook handler для Vercel"""
    
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            
            # Парсим JSON от Telegram
            data = json.loads(body.decode('utf-8'))
            
            # Создаём приложение
            application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
            
            # Создаём Update объект
            update = Update.de_json(data, application.bot)
            
            # Обрабатываем обновление
            import asyncio
            asyncio.run(handle_message(update, None))
            
            # Отвечаем Telegram что всё ОК
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
            
        except Exception as e:
            print(f"Webhook error: {e}")
            self.send_response(500)
            self.end_headers()
    
    def do_GET(self):
        """GET для проверки что webhook работает"""
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot webhook is running")
