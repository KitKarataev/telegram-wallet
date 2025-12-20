# api/bot.py
from http.server import BaseHTTPRequestHandler
import os
import json
import requests
from datetime import datetime

from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# Конфигурация
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_BASE_URL = os.environ.get("API_BASE_URL", "https://your-app.vercel.app")
WEBAPP_URL = f"{API_BASE_URL}/index.html"

# AI режим: словарь пользователей в AI чате
AI_WAITING_USERS = {}

# Категории расходов (для распознавания текста)
EXPENSE_CATEGORIES = {
    "Алкоголь и Табак": ["к&б", "красное и белое", "пиво", "вино", "wine", "beer", "alcohol", "iqos", "glo", "vape"],
    "Продукты": ["пятерочка", "перекресток", "магнит", "ашан", "лента", "вкусвилл", "lidl", "aldi", "carrefour", "mercadona", "grocery", "supermarket"],
    "Кафе и Рестораны": ["кофе", "cafe", "coffee", "restaurant", "burger", "pizza", "sushi", "wolt", "glovo", "deliveroo"],
    "Транспорт": ["uber", "bolt", "taxi", "метро", "автобус", "train", "bus", "metro", "ticket"],
    "Авто и Бензин": ["shell", "bp", "repsol", "fuel", "gas", "petrol", "parking", "парковка", "заправка"],
    "Дом и Связь": ["ikea", "leroy", "internet", "mobile", "vodafone", "orange", "аренда", "жкх", "ремонт"],
    "Здоровье и Аптека": ["pharmacy", "apteka", "аптека", "doctor", "clinic", "hospital", "лекарства"],
    "Одежда и Шопинг": ["zara", "uniqlo", "mango", "amazon", "ozon", "wb", "wildberries", "asos", "одежда", "обувь"],
    "Развлечения": ["netflix", "spotify", "steam", "cinema", "кино", "театр", "youtube", "подписка"],
}

INCOME_CATEGORIES = {
    "Зарплата": ["зарплата", "salary", "зп"],
    "Фриланс": ["фриланс", "freelance", "upwork", "фл"],
    "Инвестиции": ["дивиденды", "dividends", "акции", "stocks"],
    "Подарки": ["подарок", "gift", "др"],
    "Другое": []
}


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def parse_expense_text(text: str) -> dict | None:
    """
    Парсит текст вида: "500 Кофе" или "Такси 300"
    Возвращает: {"amount": 500, "description": "Кофе", "category": "Кафе и Рестораны"}
    """
    text = text.strip()
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2:
        return None
    
    # Пробуем оба порядка: "500 Кофе" и "Кофе 500"
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
    
    # Определяем категорию
    category = "Разное"
    desc_lower = description.lower()
    
    for cat, keywords in EXPENSE_CATEGORIES.items():
        if any(kw in desc_lower for kw in keywords):
            category = cat
            break
    
    return {
        "amount": amount,
        "description": description,
        "category": category
    }


def parse_income_text(text: str) -> dict | None:
    """Парсит доход"""
    result = parse_expense_text(text)
    if not result:
        return None
    
    # Определяем категорию дохода
    category = "Другое"
    desc_lower = result["description"].lower()
    
    for cat, keywords in INCOME_CATEGORIES.items():
        if any(kw in desc_lower for kw in keywords):
            category = cat
            break
    
    result["category"] = category
    return result


# ==================== КОМАНДЫ БОТА ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    keyboard = [
        [KeyboardButton(text="💰 Открыть приложение", web_app=WebAppInfo(url=WEBAPP_URL))]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "👋 *Привет! Я твой финансовый помощник.*\n\n"
        "📱 Нажми кнопку ниже чтобы открыть приложение\n"
        "💬 Или используй команды:\n\n"
        "/help - список команд\n"
        "/ai - 🤖 AI финансовый ассистент\n"
        "/stats - статистика\n"
        "/quick - быстрое добавление",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    help_text = """
🤖 *Доступные команды:*

📊 *Основные:*
/start - главное меню
/stats - моя статистика
/quick - быстрые кнопки

💬 *Быстрое добавление:*
Просто напиши в чат:
• `500 Кофе` - расход
• `+ 50000 Зарплата` - доход

🤖 *AI Ассистент:*
/ai - запустить AI помощника
/cancel - выйти из AI режима

💡 *Примеры для AI:*
• "Где я больше всего трачу?"
• "Как сэкономить 5000₽?"
• "Составь бюджет на месяц"
• "Хватит ли денег до конца месяца?"

📱 *Приложение:*
Нажми кнопку "Открыть приложение" для полного функционала
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats - показывает статистику"""
    user_id = update.effective_user.id
    
    try:
        response = requests.get(
            f"{API_BASE_URL}/api/stats?period=month",
            headers={"X-Tg-Init-Data": f"user={user_id}"},
            timeout=10
        )
        
        if response.status_code != 200:
            await update.message.reply_text("❌ Не удалось загрузить статистику")
            return
        
        data = response.json().get('data', {})
        
        balance = data.get('total_balance', 0)
        income = data.get('period', {}).get('income', 0)
        expense = data.get('period', {}).get('expense', 0)
        currency = data.get('currency', 'RUB')
        
        symbol = {"RUB": "₽", "USD": "$", "EUR": "€"}.get(currency, "₽")
        
        stats_text = f"""
📊 *Твоя статистика за месяц:*

💰 Баланс: `{balance} {symbol}`
📈 Доход: `+{income} {symbol}`
📉 Расход: `-{expense} {symbol}`

📱 Открой приложение для подробной статистики
"""
        
        await update.message.reply_text(stats_text, parse_mode='Markdown')
        
    except Exception as e:
        print(f"Stats error: {e}")
        await update.message.reply_text("❌ Ошибка при загрузке статистики")


async def quick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /quick - показывает быстрые кнопки"""
    user_id = update.effective_user.id
    
    try:
        response = requests.get(
            f"{API_BASE_URL}/api/quick-buttons",
            headers={"X-Tg-Init-Data": f"user={user_id}"},
            timeout=10
        )
        
        if response.status_code != 200:
            await update.message.reply_text("❌ Не удалось загрузить кнопки")
            return
        
        data = response.json().get('data', {})
        buttons = data.get('buttons', [])
        
        if not buttons:
            await update.message.reply_text(
                "У тебя пока нет быстрых кнопок.\n\n"
                "Настрой их в приложении: Настройки → Быстрые кнопки"
            )
            return
        
        keyboard = []
        for i in range(0, len(buttons), 2):
            row = []
            row.append(InlineKeyboardButton(buttons[i], callback_data=f"quick_{i}"))
            if i + 1 < len(buttons):
                row.append(InlineKeyboardButton(buttons[i + 1], callback_data=f"quick_{i+1}"))
            keyboard.append(row)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "⚡️ *Быстрые кнопки:*\n\nВыбери действие:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
    except Exception as e:
        print(f"Quick buttons error: {e}")
        await update.message.reply_text("❌ Ошибка загрузки кнопок")


async def quick_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на быстрые кнопки"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    button_index = int(query.data.replace("quick_", ""))
    
    try:
        # Получаем кнопки пользователя
        response = requests.get(
            f"{API_BASE_URL}/api/quick-buttons",
            headers={"X-Tg-Init-Data": f"user={user_id}"},
            timeout=10
        )
        
        if response.status_code != 200:
            await query.edit_message_text("❌ Ошибка")
            return
        
        data = response.json().get('data', {})
        buttons = data.get('buttons', [])
        
        if button_index >= len(buttons):
            await query.edit_message_text("❌ Кнопка не найдена")
            return
        
        button_text = buttons[button_index]
        
        # Парсим текст кнопки
        parsed = parse_expense_text(button_text)
        
        if not parsed:
            await query.edit_message_text(f"❌ Не удалось распознать: {button_text}")
            return
        
        # Добавляем расход
        add_response = requests.post(
            f"{API_BASE_URL}/api/index",
            headers={"X-Tg-Init-Data": f"user={user_id}"},
            json={
                "text": button_text,
                "type": "expense",
                "date": datetime.now().strftime('%Y-%m-%d')
            },
            timeout=10
        )
        
        if add_response.status_code == 200:
            await query.edit_message_text(
                f"✅ Добавлено:\n"
                f"💸 -{parsed['amount']} ₽\n"
                f"📝 {parsed['description']}\n"
                f"📂 {parsed['category']}"
            )
        else:
            await query.edit_message_text("❌ Не удалось добавить")
        
    except Exception as e:
        print(f"Quick callback error: {e}")
        await query.edit_message_text("❌ Ошибка")


# ==================== AI АССИСТЕНТ ====================

async def handle_ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /ai - запуск AI финансового ассистента"""
    user_id = update.effective_user.id
    
    # Активируем AI режим для пользователя
    AI_WAITING_USERS[user_id] = True
    
    await update.message.reply_text(
        "🤖 *AI Финансовый Ассистент активирован!*\n\n"
        "Теперь я буду анализировать твои финансы и давать персональные советы.\n\n"
        "💡 *Примеры вопросов:*\n"
        "• Где я больше всего трачу?\n"
        "• Как сэкономить 5000 рублей?\n"
        "• Составь бюджет на следующий месяц\n"
        "• Хватит ли мне денег до конца месяца?\n"
        "• Какие подписки мне отменить?\n"
        "• Найди аномалии в моих тратах\n\n"
        "_Чтобы выйти, напиши /cancel_",
        parse_mode='Markdown'
    )


async def handle_ai_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /cancel - выход из AI режима"""
    user_id = update.effective_user.id
    
    if user_id in AI_WAITING_USERS:
        del AI_WAITING_USERS[user_id]
        await update.message.reply_text(
            "✅ AI ассистент деактивирован.\n\n"
            "Используй /ai чтобы запустить снова."
        )
    else:
        await update.message.reply_text(
            "AI ассистент и так не был активен.\n\n"
            "Используй /ai чтобы запустить."
        )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик текстовых сообщений
    - Если AI режим активен → отправляет в AI
    - Если нет → парсит как расход/доход
    """
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Проверяем AI режим
    if user_id in AI_WAITING_USERS:
        # Режим AI чата
        await update.message.chat.send_action(action="typing")
        
        try:
            response = requests.post(
                f"{API_BASE_URL}/api/ai-assistant",
                json={"message": text},
                headers={"X-Tg-Init-Data": f"user={user_id}"},
                timeout=30
            )
            
            if response.status_code != 200:
                await update.message.reply_text(
                    "❌ Произошла ошибка при обращении к AI.\n\n"
                    "Попробуй ещё раз или напиши /cancel"
                )
                return
            
            data = response.json().get('data', {})
            ai_message = data.get('message', 'Не удалось получить ответ от AI')
            
            # Отправляем ответ AI
            await update.message.reply_text(
                f"🤖 *AI Ассистент:*\n\n{ai_message}",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            print(f"AI error: {e}")
            await update.message.reply_text(
                "❌ Не удалось связаться с AI. Попробуй позже или напиши /cancel"
            )
        
        return
    
    # Обычный режим - парсим как расход/доход
    is_income = text.startswith('+')
    if is_income:
        text = text[1:].strip()
    
    parsed = parse_income_text(text) if is_income else parse_expense_text(text)
    
    if not parsed:
        # Не смогли распознать - показываем подсказку
        await update.message.reply_text(
            "❓ Не понял команду.\n\n"
            "Попробуй так:\n"
            "• `500 Кофе` - расход\n"
            "• `+ 50000 Зарплата` - доход\n\n"
            "Или используй /help для списка команд\n"
            "Или /ai для AI помощника",
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
            await update.message.reply_text("❌ Не удалось добавить операцию")
    
    except Exception as e:
        print(f"Add operation error: {e}")
        await update.message.reply_text("❌ Ошибка при добавлении")


# ==================== MAIN ====================

def main():
    """Запуск бота"""
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set")
        return
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("quick", quick_command))
    
    # AI команды
    application.add_handler(CommandHandler("ai", handle_ai_command))
    application.add_handler(CommandHandler("cancel", handle_ai_cancel))
    
    # Callback кнопки
    application.add_handler(CallbackQueryHandler(quick_button_callback, pattern="^quick_"))
    
    # Обработчик текста (ВАЖНО: добавляется в самом конце!)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text_message
    ))
    
    print("Bot started polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


# ==================== VERCEL HANDLER ====================

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        """Webhook для Telegram (если используешь webhook вместо polling)"""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())


if __name__ == "__main__":
    main()
