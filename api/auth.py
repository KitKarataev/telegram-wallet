# api/auth.py - универсальная версия для бота И веб-приложения
import json
from urllib.parse import parse_qs, unquote


def parse_init_data(init_data: str) -> int | None:
    """
    Парсит user_id из Telegram initData
    
    Поддерживает форматы:
    1. От бота: user={"id":123,"first_name":"User",...}
    2. От WebApp: query_id=...&user={"id":123,...}&auth_date=...&hash=...
    3. Простой: user=123
    """
    try:
        if not init_data:
            return None
        
        # Формат 1: Простой от бота - user={"id":123}
        if init_data.startswith('user=') and '&' not in init_data:
            user_data = init_data[5:]
            
            # Пробуем распарсить как JSON
            try:
                user_obj = json.loads(user_data)
                return int(user_obj.get('id'))
            except:
                # Если не JSON, то просто число
                try:
                    return int(user_data)
                except:
                    return None
        
        # Формат 2: Полный от WebApp - query_id=...&user=...&auth_date=...
        if '&' in init_data or 'query_id=' in init_data:
            # Парсим как query string
            params = parse_qs(init_data)
            
            # Извлекаем user
            user_param = params.get('user', [None])[0]
            
            if user_param:
                try:
                    # Декодируем если нужно
                    user_data = unquote(user_param)
                    user_obj = json.loads(user_data)
                    return int(user_obj.get('id'))
                except Exception as e:
                    print(f"Failed to parse user from WebApp initData: {e}")
                    return None
        
        return None
        
    except Exception as e:
        print(f"Parse init_data error: {e}")
        return None


def require_user_id(handler) -> int | None:
    """
    Извлекает user_id из заголовка X-Tg-Init-Data
    Если не найден - отправляет 401 ошибку
    
    Returns:
        user_id если найден, None если нет (и уже отправлена ошибка)
    """
    init_data = handler.headers.get('X-Tg-Init-Data', '')
    
    # Для отладки (можно убрать потом)
    if init_data:
        print(f"[AUTH] Received initData (first 100 chars): {init_data[:100]}...")
    
    user_id = parse_init_data(init_data)
    
    if user_id is None:
        print(f"[AUTH] Failed to extract user_id from initData")
        
        # Отправляем 401 Unauthorized
        handler.send_response(401)
        handler.send_header('Content-type', 'application/json')
        handler.end_headers()
        handler.wfile.write(json.dumps({
            "error": "Unauthorized",
            "message": "Invalid or missing X-Tg-Init-Data header"
        }).encode())
        return None
    
    print(f"[AUTH] Successfully extracted user_id: {user_id}")
    return user_id
