# api/logger.py
import logging
import json
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

logger = logging.getLogger(__name__)


def log_event(event_type: str, user_id: int = 0, details: dict = None, level: str = "info"):
    """
    Структурированное логирование событий
    
    Args:
        event_type: Тип события (например, "expense_created")
        user_id: ID пользователя
        details: Дополнительные детали (словарь)
        level: Уровень логирования ("info", "warning", "error")
    """
    log_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "event": event_type,
        "user_id": user_id,
        "details": details or {}
    }
    
    log_message = json.dumps(log_data, ensure_ascii=False)
    
    if level == "error":
        logger.error(log_message)
    elif level == "warning":
        logger.warning(log_message)
    else:
        logger.info(log_message)
