# api/bot.py - исправленная аутентификация
from http.server import BaseHTTPRequestHandler
import os
import json
import requests
from datetime import datetime

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


def create_init_data(user_id: int) -> str:
    """Создаёт правильный initData для API"""
    # Минимальный формат который API сможет распарсить
    import json
    user_data = json.dumps({"id": user_id, "first_name": "User", "is_bot": False})
    return f"user={user_data}"


def send_message(chat_id: int, text: str, reply_markup=None):
    """Отправляет сообщение"""
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        
        if reply_markup:
            payload["reply_markup"] = reply_markup
        
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        print(f"Send error: {e}")
        return False


def send_chat_action(chat_id: int, action: str = "typing"):
    """Показывает индикатор печати"""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendChatAction",
            json={"chat_id": chat_id, "action": action},
            timeout=5
        )
    except:
        pass


def parse_expense_text(text: str) -> dict | None:
    """Парсит: 500 Кофе"""
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


def handle_start(chat_id: int):
    """Команда /start"""
    keyboard = {
        "keyboard": [[{
            "text": "💰 Открыть приложение",
            "web_app": {"url": WEBAPP_URL}
        }]],
        "resize_keyboard": True
    }
    
    send_message(
        chat_id,
        "👋 *Привет! Я твой финансовый помощник.*\n\n"
        "📱 Нажми кнопку ниже\n"
        "💬 Или используй команды:\n\n"
        "/help - помощь\n"
        "/ai - 🤖 AI ассистент\n"
        "/stats - статистика",
        keyboard
    )


def handle_help(chat_id: int):
    """Команда /help"""
    send_message(
        chat_id,
        "🤖 *Доступные команды:*\n\n"
        "📊 *Основные:*\n"
        "/start - главное меню\n"
        "/stats - статистика\n"
        "/ai - AI помощник\n"
        "/cancel - выход из AI\n\n"
        "💬 *Быстрое добавление:*\n"
        "`500 Кофе` - расход\n"
        "`+ 50000 Зарплата` - доход\n\n"
        "🤖 *Примеры для AI:*\n"
        "• Где я больше всего трачу?\n"
        "• Как сэкономить 5000₽?\n"
        "• Составь бюджет на месяц"
    )


def handle_stats(chat_id: int, user_id: int):
    """Команда /stats"""
    try:
        init_data = create_init_data(user_id)
        
        response = requests.get(
            f"{API_BASE_URL}/api/stats?period=month",
            headers={"X-Tg-Init-Data": init_data},
            timeout=10
        )
        
        print(f"Stats response: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json().get('data', {})
            balance = data.get('total_balance', 0)
            income = data.get('period', {}).get('income', 0)
            expense = data.get('period', {}).get('expense', 0)
            
            send_message(
                chat_id,
                f"📊 *Статистика за месяц:*\n\n"
                f"💰 Баланс: `{balance} ₽`\n"
                f"📈 Доход: `+{income} ₽`\n"
                f"📉 Расход: `-{expense} ₽`"
            )
        else:
            send_message(chat_id, f"❌ Ошибка {response.status_code}: не удалось загрузить статистику")
    except Exception as e:
        print(f"Stats error: {e}")
        send_message(chat_id, "❌ Ошибка загрузки")


def handle_ai_start(chat_id: int, user_id: int):
    """Команда /ai"""
    AI_WAITING_USERS[user_id] = True
    send_message(
        chat_id,
        "🤖 *AI Финансовый Ассистент активирован!*\n\n"
        "Задай вопрос о финансах:\n\n"
        "💡 Примеры:\n"
        "• Где я больше всего трачу?\n"
        "• Как сэкономить 5000 рублей?\n"
        "• Составь бюджет на месяц\n"
        "• Хватит ли денег до конца месяца?\n\n"
        "_Выход: /cancel_"
    )


def handle_ai_cancel(chat_id: int, user_id: int):
    """Команда /cancel"""
    if user_id in AI_WAITING_USERS:
        del AI_WAITING_USERS[user_id]
        send_message(chat_id, "✅ AI ассистент деактивирован")
    else:
        send_message(chat_id, "AI не был активен. Используй /ai для запуска")


def handle_ai_message(chat_id: int, user_id: int, text: str):
    """Обработка сообщения в AI режиме"""
    send_chat_action(chat_id, "typing")
    
    try:
        init_data = create_init_data(user_id)
        
        response = requests.post(
            f"{API_BASE_URL}/api/ai-assistant",
            json={"message": text},
            headers={"X-Tg-Init-Data": init_data},
            timeout=30
        )
        
        print(f"AI response: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json().get('data', {})
            ai_message = data.get('message', 'Не удалось получить ответ')
            send_message(chat_id, f"🤖 *AI Ассистент:*\n\n{ai_message}")
        else:
            send_message(chat_id, f"❌ AI ошибка {response.status_code}. Попробуй позже или /cancel")
    except Exception as e:
        print(f"AI error: {e}")
        send_message(chat_id, "❌ Не удалось связаться с AI")


def handle_expense_text(chat_id: int, user_id: int, text: str):
    """Обработка обычного текста (расход/доход)"""
    is_income = text.startswith('+')
    if is_income:
        text = text[1:].strip()
    
    parsed = parse_expense_text(text)
    
    if not parsed:
        send_message(
            chat_id,
            "❓ Не понял команду.\n\n"
            "Попробуй так:\n"
            "• `500 Кофе` - расход\n"
            "• `+ 50000 Зарплата` - доход\n\n"
            "Или используй:\n"
            "/help - помощь\n"
            "/ai - AI ассистент"
        )
        return
    
    # Добавляем операцию
    try:
        init_data = create_init_data(user_id)
        
        response = requests.post(
            f"{API_BASE_URL}/api/index",
            headers={"X-Tg-Init-Data": init_data},
            json={
                "text": f"{parsed['amount']} {parsed['description']}",
                "type": "income" if is_income else "expense",
                "date": datetime.now().strftime('%Y-%m-%d')
            },
            timeout=10
        )
        
        print(f"Add expense response: {response.status_code}")
        
        if response.status_code == 200:
            emoji = "📈" if is_income else "💸"
            sign = "+" if is_income else "-"
            
            send_message(
                chat_id,
                f"✅ Добавлено:\n"
                f"{emoji} {sign}{parsed['amount']} ₽\n"
                f"📝 {parsed['description']}\n"
                f"📂 {parsed['category']}"
            )
        else:
            send_message(chat_id, f"❌ Ошибка {response.status_code}: не удалось добавить")
    except Exception as e:
        print(f"Add error: {e}")
        send_message(chat_id, "❌ Ошибка при добавлении")


class handler(BaseHTTPRequestHandler):
    """Webhook handler"""
    
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode('utf-8'))
            
            message = data.get('message', {})
            chat_id = message.get('chat', {}).get('id')
            user_id = message.get('from', {}).get('id')
            text = message.get('text', '')
            
            if not chat_id or not text:
                self.send_response(200)
                self.end_headers()
                return
            
            print(f"User {user_id}: {text}")
            
            # Команды
            if text == '/start':
                handle_start(chat_id)
            elif text == '/help':
                handle_help(chat_id)
            elif text == '/stats':
                handle_stats(chat_id, user_id)
            elif text == '/ai':
                handle_ai_start(chat_id, user_id)
            elif text == '/cancel':
                handle_ai_cancel(chat_id, user_id)
            
            # AI режим
            elif user_id in AI_WAITING_USERS:
                handle_ai_message(chat_id, user_id, text)
            
            # Обычный режим
            else:
                handle_expense_text(chat_id, user_id, text)
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
            
        except Exception as e:
            print(f"Webhook error: {e}")
            import traceback
            traceback.print_exc()
            
            self.send_response(200)
            self.end_headers()
    
    def do_GET(self):
        """GET для проверки"""
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot webhook is running - Full version with AI (Fixed Auth)")
