# api/auth.py - debug версия
import json


def parse_init_data(init_data: str) -> int | None:
    """
    Парсит user_id из Telegram initData
    """
    print(f"[AUTH DEBUG] Received init_data: {init_data}")
    print(f"[AUTH DEBUG] init_data length: {len(init_data)}")
    print(f"[AUTH DEBUG] init_data type: {type(init_data)}")
    
    try:
        if not init_data:
            print("[AUTH DEBUG] init_data is empty!")
            return None
        
        # Убираем префикс "user="
        if init_data.startswith('user='):
            user_data = init_data[5:]
            print(f"[AUTH DEBUG] After removing 'user=' prefix: {user_data}")
            
            # Пробуем распарсить как JSON
            try:
                user_obj = json.loads(user_data)
                user_id = int(user_obj.get('id'))
                print(f"[AUTH DEBUG] Parsed as JSON, user_id: {user_id}")
                return user_id
            except Exception as e:
                print(f"[AUTH DEBUG] Not JSON, error: {e}")
                # Если не JSON, то просто число
                try:
                    user_id = int(user_data)
                    print(f"[AUTH DEBUG] Parsed as int, user_id: {user_id}")
                    return user_id
                except Exception as e2:
                    print(f"[AUTH DEBUG] Not int either, error: {e2}")
                    return None
        else:
            print(f"[AUTH DEBUG] Doesn't start with 'user='")
            return None
    except Exception as e:
        print(f"[AUTH DEBUG] Exception: {e}")
        return None


def require_user_id(handler) -> int | None:
    """
    Извлекает user_id из заголовка X-Tg-Init-Data
    """
    print("[AUTH DEBUG] ===================")
    print("[AUTH DEBUG] require_user_id called")
    
    # Печатаем все заголовки
    print("[AUTH DEBUG] All headers:")
    for key, value in handler.headers.items():
        print(f"[AUTH DEBUG]   {key}: {value[:100] if len(value) > 100 else value}")
    
    init_data = handler.headers.get('X-Tg-Init-Data', '')
    print(f"[AUTH DEBUG] X-Tg-Init-Data: '{init_data}'")
    
    user_id = parse_init_data(init_data)
    
    if user_id is None:
        print(f"[AUTH DEBUG] FAILED to extract user_id!")
        # Отправляем 401 Unauthorized
        handler.send_response(401)
        handler.send_header('Content-type', 'application/json')
        handler.end_headers()
        handler.wfile.write(json.dumps({
            "error": "Unauthorized",
            "message": "Invalid or missing X-Tg-Init-Data header",
            "debug": {
                "received_header": init_data[:100] if init_data else "empty"
            }
        }).encode())
        return None
    
    print(f"[AUTH DEBUG] SUCCESS! user_id: {user_id}")
    print("[AUTH DEBUG] ===================")
    return user_id
