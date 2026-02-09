# posting/scheduler.py
"""
Главный планировщик публикаций
Управляет генерацией и публикацией контента
"""
import schedule
import time
import threading
from datetime import datetime, timedelta
import logging
import os
import sys

# Добавляем пути для импорта
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

class ContentScheduler:
    """
    Главный планировщик публикаций
    Управляет генерацией и публикацией контента
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        print("🔧 Инициализация планировщика...")
        
        # Загружаем конфиг
        try:
            from config import Config
            self.config = Config
            print("✅ Конфигурация загружена")
        except ImportError as e:
            print(f"❌ Ошибка загрузки конфига: {e}")
            return
        
        # Инициализация компонентов
        self.writer = None
        self.artist = None
        self.vk_publisher = None
        self.tg_poster = None
        
        self._init_components()
        
        # Состояние
        self.is_running = False
        self.last_published = None
        
        print("✅ Планировщик инициализирован")
    
    def _init_components(self):
        """Инициализирует все компоненты"""
        
        print("🔧 Инициализация компонентов...")
        
        # 1. AI Writer (генератор статей)
        try:
            from ai.yandex_research_writer import YandexResearchWriter
            self.writer = YandexResearchWriter()
            print("✅ Yandex Writer загружен")
        except ImportError as e:
            print(f"❌ Не удалось загрузить Yandex Writer: {e}")
            print("   Установите: pip install requests")
        
        # 2. AI Artist (генератор изображений)
        try:
            from ai.yandex_art_final import YandexArtGenerator
            self.artist = YandexArtGenerator()
            print("✅ Яндекс Арт Generator загружен")
        except ImportError as e:
            print(f"❌ Не удалось загрузить Яндекс Арт: {e}")
            self.artist = None
        
        # 3. VK Publisher (если включено в настройках)
        if self.config.PUBLISH_TO_VK:
            try:
                from posting.vk_publisher import VKPublisher
                self.vk_publisher = VKPublisher()
                if hasattr(self.vk_publisher, 'enabled') and self.vk_publisher.enabled:
                    print("✅ VK Publisher загружен и настроен")
                else:
                    print("⚠️  VK Publisher загружен, но не настроен")
            except ImportError as e:
                print(f"❌ Не удалось загрузить VK Publisher: {e}")
                print("   Установите: pip install vk-api")
            except Exception as e:
                print(f"⚠️  Ошибка инициализации VK Publisher: {e}")
        
        # 4. Telegram Poster (если включено в настройках)
        if self.config.PUBLISH_TO_TG:
            try:
                from posting.telegram_sync import TelegramSyncPoster
                self.tg_poster = TelegramSyncPoster(
                    bot_token=self.config.TELEGRAM_CHANNEL_TOKEN,
                    channel_id=self.config.TELEGRAM_CHANNEL_ID
                )
                print("✅ Telegram Poster загружен")
            except ImportError as e:
                print(f"❌ Не удалось загрузить Telegram Sync Poster: {e}")
                print("   Установите: pip install requests")
            except Exception as e:
                print(f"⚠️  Ошибка инициализации Telegram Poster: {e}")
    
    def _get_todays_topic(self):
        """Получает тему на сегодня"""
        # Сначала пробуем из базы данных
        try:
            from database.content_plan import get_todays_topic
            topic_data = get_todays_topic()
            if topic_data:
                if isinstance(topic_data, tuple):
                    return topic_data[0], topic_data[1]
                else:
                    return topic_data.get('topic', ''), topic_data.get('keywords', [])
        except ImportError:
            print("⚠️  База данных не настроена, использую тестовые темы")
        
        # Fallback: тестовые темы на основе дня недели
        import random
        from datetime import datetime
        
        day_of_week = datetime.now().weekday()  # 0=понедельник
        
        fallback_topics = [
            ("🏆 Топ-5 ортопедических матрасов 2024 года", ["рейтинг", "топ", "ортопедический", "2024", "матрасы"]),
            ("💤 Как матрас влияет на качество сна и здоровье", ["сон", "качество", "здоровье", "влияние", "отдых"]),
            ("🌿 Эко-матрасы: натуральные материалы для здорового сна", ["экология", "натуральный", "материалы", "безопасность", "эко"]),
            ("⚡ Умные матрасы с технологиями мониторинга сна", ["умный", "технологии", "гаджеты", "инновации", "смарт"]),
            ("👫 Матрасы для пар: решение разных предпочтений в жесткости", ["пара", "семья", "совместимость", "компромисс", "отношения"]),
            ("💰 Как правильно выбрать матрас по соотношению цена/качество", ["цена", "качество", "выбор", "бюджет", "экономия"]),
            ("🚀 Новинки матрасов с эффектом памяти формы", ["новинки", "память формы", "ортопедия", "инновации", "комфорт"])
        ]
        
        topic_index = day_of_week % len(fallback_topics)
        topic, keywords = fallback_topics[topic_index]
        
        print(f"📝 Используется тема: {topic}")
        return topic, keywords
    
    def daily_publication_task(self):
        """Основная задача: генерация и публикация контента"""
        try:
            print("\n" + "="*60)
            print(f"📅 ЗАПУСК ПУБЛИКАЦИИ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("="*60)
            
            # 1. Проверяем AI модули
            if not self.writer:
                print("❌ Yandex Writer не инициализирован")
                return False
            
            # 2. Получаем тему дня
            print("📝 Получение темы дня...")
            topic, keywords = self._get_todays_topic()
            print(f"✅ Тема: {topic}")
            print(f"✅ Ключевые слова: {', '.join(keywords)}")
            
            # 3. Генерируем статью
            print("🤖 Генерация статьи...")
            article = self.writer.create_article_with_research(topic, keywords)
            
            if not article or len(article) < 100:
                print("❌ Статья не сгенерирована или слишком короткая")
                return False
            
            print(f"✅ Статья создана ({len(article)} символов)")
            print(f"📄 Начало статьи:\n{article[:200]}...\n")
            
            # 4. Создаем иллюстрацию (если есть artist)
            image_path = None
            if self.artist:
                print("🎨 Создание иллюстрации...")
                image_path = self.artist.create_image_for_article(article, topic)
                
                if image_path and os.path.exists(image_path):
                    file_size = os.path.getsize(image_path)
                    print(f"✅ Иллюстрация создана: {image_path} ({file_size // 1024} KB)")
                else:
                    print("⚠️  Иллюстрация не создана или файл не найден")
                    image_path = None
            else:
                print("⚠️  Генератор изображений не инициализирован")
            
            # 5. Публикуем в VK (если есть publisher и включено)
            vk_result = None
            if self.vk_publisher and self.config.PUBLISH_TO_VK:
                print("📤 Публикация в VK...")
                try:
                    vk_result = self.vk_publisher.publish_article(article, image_path)
                    if vk_result:
                        print(f"✅ Опубликовано в VK: post_id={vk_result}")
                    else:
                        print("❌ Ошибка публикации в VK")
                except Exception as e:
                    print(f"❌ Исключение при публикации в VK: {e}")
                    import traceback
                    traceback.print_exc()
            
            # 6. Публикуем в Telegram (если есть poster и включено)
            tg_result = None
            if self.tg_poster and self.config.PUBLISH_TO_TG:
                print("📤 Публикация в Telegram канал...")
                try:
                    tg_result = self.tg_poster.post_article(article, image_path)
                    
                    if tg_result:
                        print(f"✅ Опубликовано в Telegram: message_id={tg_result}")
                    else:
                        print("❌ Ошибка публикации в Telegram")
                        
                except Exception as e:
                    print(f"❌ Исключение при публикации в Telegram: {e}")
                    import traceback
                    traceback.print_exc()
            
            # 7. Обновляем статус
            self.last_published = datetime.now()
            
            # 8. Логируем результат
            success = vk_result is not None or tg_result is not None
            
            print("="*60)
            if success:
                print("✅ ЗАДАЧА ВЫПОЛНЕНА УСПЕШНО")
                print(f"📊 Результат: VK={'✅' if vk_result else '❌'}, TG={'✅' if tg_result else '❌'}")
            else:
                print("⚠️  ЗАДАЧА ВЫПОЛНЕНА ЧАСТИЧНО (контент сгенерирован, но не опубликован)")
            
            print("="*60)
            
            return success
            
        except Exception as e:
            print(f"❌ Критическая ошибка в задаче публикации: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def run_test_publication(self):
        """Запускает тестовую публикацию немедленно"""
        print("\n🧪 ТЕСТОВАЯ ПУБЛИКАЦИЯ")
        print("="*60)
        
        print("🔍 Проверка компонентов:")
        print(f"   Writer: {'✅' if self.writer else '❌'}")
        print(f"   Artist: {'✅' if self.artist else '❌'}")
        print(f"   VK Publisher: {'✅' if self.vk_publisher else '❌'}")
        print(f"   TG Poster: {'✅' if self.tg_poster else '❌'}")
        print("="*60)
        
        # Проверяем минимальные требования
        if not self.writer:
            print("❌ Невозможно выполнить тест: Writer не инициализирован")
            return False
        
        # Запускаем публикацию с тестовой темой
        print("\n🚀 Запуск тестовой публикации...")
        
        # Используем тестовую тему
        test_topic = "Тестовая публикация системы Snoomi"
        test_keywords = ["тест", "snoomi", "матрасы", "здоровый сон"]
        
        print(f"📝 Тестовая тема: {test_topic}")
        
        try:
            # Генерируем тестовую статью
            print("🤖 Генерация тестовой статьи...")
            article = self.writer.create_article_with_research(test_topic, test_keywords)
            
            if not article or len(article) < 100:
                print("❌ Тестовая статья не сгенерирована")
                return False
            
            print(f"✅ Тестовая статья создана ({len(article)} символов)")
            
            # Генерируем тестовое изображение
            image_path = None
            if self.artist:
                print("🎨 Генерация тестового изображения...")
                image_path = self.artist.create_image_for_article(article, test_topic)
                
                if image_path:
                    print(f"✅ Тестовое изображение создано: {image_path}")
                else:
                    print("⚠️  Тестовое изображение не создано")
            
            # Тест публикации в VK (только если включено)
            vk_test_ok = False
            if self.vk_publisher and self.config.PUBLISH_TO_VK:
                print("\n🔍 Тест публикации в VK...")
                try:
                    # Создаем тестовый пост
                    test_post = f"🧪 Тестовая публикация от Snoomi Platform\n\n{article[:500]}...\n\n#тест #snoomi #матрасы"
                    vk_result = self.vk_publisher.publish_article(test_post, image_path)
                    
                    if vk_result:
                        print(f"✅ Тест VK пройден: post_id={vk_result}")
                        vk_test_ok = True
                    else:
                        print("❌ Тест VK не пройден")
                except Exception as e:
                    print(f"❌ Ошибка теста VK: {e}")
            
            # Тест публикации в Telegram (только если включено)
            tg_test_ok = False
            if self.tg_poster and self.config.PUBLISH_TO_TG:
                print("\n🔍 Тест публикации в Telegram...")
                try:
                    # Создаем тестовый пост
                    test_post = f"🧪 <b>Тестовая публикация от Snoomi Platform</b>\n\n{article[:300]}...\n\n#тест #snoomi #матрасы"
                    tg_result = self.tg_poster.post_article(test_post, image_path)
                    
                    if tg_result:
                        print(f"✅ Тест Telegram пройден: message_id={tg_result}")
                        tg_test_ok = True
                    else:
                        print("❌ Тест Telegram не пройден")
                except Exception as e:
                    print(f"❌ Ошибка теста Telegram: {e}")
            
            print("\n" + "="*60)
            print("📊 РЕЗУЛЬТАТЫ ТЕСТА:")
            print(f"✅ Генерация статей: {'Работает' if article else 'Не работает'}")
            print(f"✅ Генерация изображений: {'Работает' if image_path else 'Не работает'}")
            print(f"✅ Публикация в VK: {'Работает' if vk_test_ok else ('Не настроена' if not self.config.PUBLISH_TO_VK else 'Не работает')}")
            print(f"✅ Публикация в Telegram: {'Работает' if tg_test_ok else ('Не настроена' if not self.config.PUBLISH_TO_TG else 'Не работает')}")
            print("="*60)
            
            return article is not None
            
        except Exception as e:
            print(f"❌ Ошибка тестовой публикации: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def run_single_publication(self, topic: str = None, keywords: list = None):
        """
        Запускает единичную публикацию с заданной темой
        
        Args:
            topic: Тема для публикации (если None - берется сегодняшняя тема)
            keywords: Ключевые слова для темы
        """
        print("\n🚀 ЗАПУСК ЕДИНИЧНОЙ ПУБЛИКАЦИИ")
        print("="*60)
        
        if topic:
            print(f"📝 Заданная тема: {topic}")
            if not keywords:
                keywords = ["матрасы", "сон", "здоровье"]
        else:
            topic, keywords = self._get_todays_topic()
            print(f"📝 Тема дня: {topic}")
        
        print(f"🔑 Ключевые слова: {', '.join(keywords)}")
        print("="*60)
        
        return self.daily_publication_task()
    
    def run(self):
        """Запускает планировщик"""
        print("\n🚀 ЗАПУСК ПЛАНИРОВЩИКА")
        print("="*60)
        
        # Проверяем конфигурацию
        if not hasattr(self.config, 'PUBLISH_HOUR'):
            print("❌ PUBLISH_HOUR не настроен в конфиге")
            return
        
        # Настраиваем расписание
        publish_time = f"{self.config.PUBLISH_HOUR:02d}:00"
        schedule.every().day.at(publish_time).do(self.daily_publication_task)
        
        # Также планируем проверку каждые 10 минут для отладки
        schedule.every(10).minutes.do(self._health_check)
        
        print(f"⏰ Публикация каждый день в {publish_time}")
        print("🔄 Планировщик работает...")
        print("⏸️  Ctrl+C для остановки\n")
        
        # Тестовый запуск сразу (опционально)
        print("🧪 Запуск тестовой публикации...")
        self.run_test_publication()
        
        print("\n📅 Расписание запущено:")
        for job in schedule.jobs:
            print(f"   {job}")
        
        # Основной цикл
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)
        except KeyboardInterrupt:
            print("\n🛑 Планировщик остановлен")
    
    def _health_check(self):
        """Проверка здоровья системы"""
        try:
            print(f"🔍 Проверка системы: {datetime.now().strftime('%H:%M:%S')}")
            
            # Проверяем компоненты
            components = {
                "Writer": self.writer is not None,
                "Artist": self.artist is not None,
                "VK Publisher": self.vk_publisher is not None,
                "TG Poster": self.tg_poster is not None
            }
            
            for name, status in components.items():
                print(f"   {name}: {'✅' if status else '❌'}")
            
            # Показываем время последней публикации
            if self.last_published:
                elapsed = datetime.now() - self.last_published
                hours = elapsed.total_seconds() / 3600
                print(f"   Последняя публикация: {hours:.1f} часов назад")
            
            print("✅ Проверка завершена\n")
            
        except Exception as e:
            print(f"⚠️  Ошибка проверки здоровья: {e}")

# Утилиты для быстрого использования
def run_quick_test():
    """Быстрая проверка системы"""
    print("🧪 БЫСТРАЯ ПРОВЕРКА СИСТЕМЫ")
    print("="*60)
    
    scheduler = ContentScheduler()
    
    print("\n🔍 Тест генерации контента...")
    success = scheduler.run_test_publication()
    
    if success:
        print("\n🎉 СИСТЕМА ГОТОВА К РАБОТЕ!")
        print("\n💡 Для запуска планировщика используйте:")
        print("   scheduler.run()")
    else:
        print("\n⚠️  СИСТЕМА ТРЕБУЕТ НАСТРОЙКИ")
    
    return success

def run_scheduled():
    """Запуск планировщика в фоновом режиме"""
    scheduler = ContentScheduler()
    scheduler.run()

# Быстрый тест
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("🧪 ТЕСТ ПЛАНИРОВЩИКА")
    print("="*60)
    
    # Создаем планировщик
    scheduler = ContentScheduler()
    
    # Запускаем тестовую публикацию
    scheduler.run_test_publication()
    
    # Спрашиваем пользователя
    print("\n🔧 ВЫБЕРИТЕ РЕЖИМ:")
    print("1. 🧪 Только тест (по умолчанию)")
    print("2. 🚀 Запустить планировщик")
    print("3. 📝 Единичная публикация с темой")
    
    choice = input("\nВаш выбор (1-3): ").strip()
    
    if choice == "2":
        print("\n🚀 ЗАПУСК ПЛАНИРОВЩИКА...")
        scheduler.run()
    elif choice == "3":
        topic = input("Введите тему: ").strip()
        if topic:
            scheduler.run_single_publication(topic=topic)
        else:
            scheduler.run_single_publication()
    else:
        print("\n✅ Тест завершен. Планировщик готов к работе.")