"""
Точка входа для запуска веб-приложения Snoomi Platform
"""
import sys
import os
from pathlib import Path

# Добавление корневой директории в путь
sys.path.append(str(Path(__file__).parent.parent))

from web.app import app
from web.database import db_manager
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('web/app.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def check_dependencies():
    """Проверка зависимостей и модулей"""
    logger.info("🔍 Проверка зависимостей...")
    
    # Проверка модулей Snoomi
    modules_to_check = [
        ('ai.text_generator', 'TextGenerator'),
        ('ai.image_generator', 'ImageGenerator'),
        ('posting.scheduler', 'ContentScheduler'),
        ('posting.vk_poster', 'VKPoster'),
        ('posting.tg_poster', 'TGPoster')
    ]
    
    for module_path, class_name in modules_to_check:
        try:
            __import__(module_path)
            logger.info(f"✅ {module_path} доступен")
        except ImportError as e:
            logger.warning(f"⚠️  {module_path} недоступен: {e}")
    
    # Проверка базы данных
    try:
        channels = db_manager.get_channels()
        logger.info(f"✅ База данных: {len(channels)} каналов")
    except Exception as e:
        logger.error(f"❌ Ошибка базы данных: {e}")
    
    return True

def main():
    """Основная функция запуска"""
    print("🚀 Запуск Snoomi Platform Web Interface")
    print("=" * 50)
    
    # Проверка зависимостей
    if not check_dependencies():
        print("❌ Проверка зависимостей не пройдена")
        return
    
    # Информация о приложении
    print(f"\n🌐 Веб-интерфейс доступен по адресу: http://localhost:5000")
    print(f"📊 База данных: {db_manager.db_path}")
    print(f"📁 Каналов в базе: {len(db_manager.get_channels())}")
    print(f"📝 Контента в базе: {len(db_manager.get_content({'limit': 1000}))}")
    
    print("\n🔧 Доступные эндпоинты:")
    print("  /              - Главная страница")
    print("  /content       - Управление контентом")
    print("  /channels      - Управление каналами")
    print("  /analytics     - Аналитика")
    print("  /health        - Проверка здоровья системы")
    print("  /api/*         - API эндпоинты")
    
    print("\n⚡ Запуск сервера...")
    print("=" * 50)
    
    # Запуск Flask приложения
    app.run(
        host=os.environ.get('FLASK_HOST', '0.0.0.0'),
        port=int(os.environ.get('FLASK_PORT', 5000)),
        debug=os.environ.get('FLASK_ENV') != 'production',
        threaded=True
    )

if __name__ == '__main__':
    main()