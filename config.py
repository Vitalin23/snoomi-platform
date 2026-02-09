# config.py - ОБНОВЛЕННЫЙ ВАРИАНТ
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # ===== YANDEX API =====
    YANDEX_API_KEY = os.getenv('YANDEX_API_KEY', '')
    YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', '')
    YANDEX_ART_KEY = os.getenv('YANDEX_ART_KEY', '')
    
    # ===== TELEGRAM =====
    # Для бота-консультанта
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
    
    # Для авто-постинга в канал
    TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID', '')
    TELEGRAM_CHANNEL_TOKEN = os.getenv('TELEGRAM_CHANNEL_TOKEN', '')  # Токен для публикации
    TG_ADMIN = os.getenv('TG_ADMIN', '')
    
    # ===== VK =====
    VK_ACCESS_TOKEN = os.getenv('VK_ACCESS_TOKEN', '')
    VK_GROUP_ID = os.getenv('VK_GROUP_ID', '')
    
    # ===== НАСТРОЙКИ СИСТЕМЫ =====
    PUBLISH_TO_VK = os.getenv('PUBLISH_TO_VK', 'True').lower() == 'true'
    PUBLISH_TO_TG = os.getenv('PUBLISH_TO_TG', 'True').lower() == 'true'
    PUBLISH_HOUR = int(os.getenv('PUBLISH_HOUR', '10'))  # Время публикации (10 утра)
    
    # ===== ИЗОЛЯЦИЯ КОМПОНЕНТОВ =====
    # По умолчанию сайтовый бот работает без монетизационной админ-панели.
    ENABLE_MONETIZATION_ADMIN_PANEL = (
        os.getenv('ENABLE_MONETIZATION_ADMIN_PANEL', 'False').lower() == 'true'
    )
    WEB_HOST = os.getenv('WEB_HOST', '0.0.0.0')
    WEB_PORT = int(os.getenv('WEB_PORT', '5000'))
    
    # config.py - добавьте проверку Telegram канала
@classmethod
def validate(cls):
    """Проверяет минимальную конфигурацию"""
    
    print("🔍 Проверка конфигурации...")
    
    # Проверяем Yandex для генерации (обязательно)
    yandex_ok = bool(cls.YANDEX_API_KEY and cls.YANDEX_FOLDER_ID)
    if not yandex_ok:
        print("❌ YANDEX_API_KEY и YANDEX_FOLDER_ID обязательны для генерации контента")
        return False
    
    print("✅ Yandex GPT настроен")
    
    # Проверяем Telegram бота (опционально, только предупреждение)
    if not cls.TELEGRAM_BOT_TOKEN:
        print("⚠️  TELEGRAM_BOT_TOKEN не настроен (бот-консультант работать не будет)")
    else:
        print("✅ Telegram бот настроен")
    
    # Проверяем платформы публикации
    vk_configured = bool(cls.VK_ACCESS_TOKEN and cls.VK_GROUP_ID)
    tg_configured = bool(cls.TELEGRAM_CHANNEL_TOKEN and cls.TELEGRAM_CHANNEL_ID)
    
    if cls.PUBLISH_TO_VK and not vk_configured:
        print("⚠️  PUBLISH_TO_VK=True, но VK_ACCESS_TOKEN или VK_GROUP_ID не настроены")
    elif cls.PUBLISH_TO_VK and vk_configured:
        print("✅ VK публикация настроена")
    
    if cls.PUBLISH_TO_TG and not tg_configured:
        print("⚠️  PUBLISH_TO_TG=True, но TELEGRAM_CHANNEL_TOKEN или TELEGRAM_CHANNEL_ID не настроены")
    elif cls.PUBLISH_TO_TG and tg_configured:
        print("✅ Telegram публикация настроена")
    
    # Проверяем Yandex Art
    if cls.YANDEX_ART_KEY:
        print("✅ Yandex Art настроен")
    else:
        print("⚠️  YANDEX_ART_KEY не настроен (будут простые картинки)")
    
    print("✅ Конфигурация проверена")
    return True
        