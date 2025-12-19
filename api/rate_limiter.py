# api/rate_limiter.py
from datetime import datetime, timedelta
from typing import Dict
import os

# Хранилище лимитов (в памяти)
RATE_LIMITS: Dict[str, list] = {}
MAX_REQUESTS_PER_MINUTE = 20  # Лимит: 20 запросов в минуту


def check_rate_limit(user_id: int) -> tuple[bool, int]:
    """
    Проверяет, не превышен ли лимит запросов
    
    Возвращает:
        (разрешено: bool, осталось запросов: int)
    """
    now = datetime.utcnow()
    key = str(user_id)
    
    # Инициализируем или очищаем старые записи
    if key not in RATE_LIMITS:
        RATE_LIMITS[key] = []
    
    # Удаляем запросы старше 1 минуты
    cutoff = now - timedelta(minutes=1)
    RATE_LIMITS[key] = [ts for ts in RATE_LIMITS[key] if ts > cutoff]
    
    # Проверяем лимит
    current_count = len(RATE_LIMITS[key])
    if current_count >= MAX_REQUESTS_PER_MINUTE:
        return False, 0
    
    # Записываем этот запрос
    RATE_LIMITS[key].append(now)
    remaining = MAX_REQUESTS_PER_MINUTE - current_count - 1
    
    return True, remaining
