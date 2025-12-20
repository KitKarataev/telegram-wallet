# api/auth.py - исправленная аутентификация
import json


def parse_init_data(init_data: str) -> int | None:
    """
    Парсит user_id из Telegram initData
    
    Поддерживает форматы:
    - user={"id":123,...}  (JSON объект)
    - user=123             (просто число)
    """
    try:
        if not init_data:
            return None
        
        # Убираем префикс "user="
        if init_data.startswith('user='):
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
    user_id = parse_init_data(init_data)
    
    if user_id is None:
        # Отправляем 401 Unauthorized
        handler.send_response(401)
        handler.send_header('Content-type', 'application/json')
        handler.end_headers()
        handler.wfile.write(json.dumps({
            "error": "Unauthorized",
            "message": "Invalid or missing X-Tg-Init-Data header"
        }).encode())
        return None
    
    return user_id
