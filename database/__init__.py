# database/__init__.py
from .database import Database

# Импортируем функции если они есть
try:
    from .content_plan import get_todays_topic
except ImportError:
    # Создаем заглушку
    def get_todays_topic():
        return None

# Убираем глобальный экземпляр db, чтобы избежать проблем с двойной инициализацией
# Вместо этого пользователи должны создавать экземпляр сами

__all__ = ['Database', 'get_todays_topic']