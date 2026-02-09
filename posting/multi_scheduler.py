# posting/multi_scheduler.py
"""
Обновленный планировщик для работы с множеством каналов клиентов
"""
import schedule
import time
import threading
from datetime import datetime, timedelta
import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

class MultiChannelScheduler:
    """
    Планировщик для мультиканальной системы
    Управляет публикациями для всех каналов всех клиентов
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        print("🔧 Инициализация MultiChannelScheduler...")
        
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
        self.multi_publisher = None
        
        self._init_components()
        
        # Состояние
        self.is_running = False
        self.last_published = {}
        
        print("✅ MultiChannelScheduler инициализирован")
    
    def _init_components(self):
        """Инициализирует все компоненты"""
        
        print("🔧 Инициализация компонентов...")
        
        # 1. AI Writer
        try:
            from ai.yandex_research_writer import YandexResearchWriter
            self.writer = YandexResearchWriter()
            print("✅ Yandex Writer загружен")
        except ImportError as e:
            print(f"❌ Не удалось загрузить Yandex Writer: {e}")
        
        # 2. AI Artist
        try:
            from ai.yandex_art_final import YandexArtGenerator
            self.artist = YandexArtGenerator()
            print("✅ Яндекс Арт Generator загружен")
        except ImportError as e:
            print(f"❌ Не удалось загрузить Яндекс Арт: {e}")
            self.artist = None
        
        # 3. Multi Platform Publisher
        try:
            from posting.multi_publisher import MultiPlatformPublisher
            self.multi_publisher = MultiPlatformPublisher()
            print("✅ Multi Platform Publisher загружен")
        except ImportError as e:
            print(f"❌ Не удалось загрузить Multi Publisher: {e}")
            self.multi_publisher = None
        
        # 4. Channels Database
        try:
            from database.channels_db import channels_db
            self.channels_db = channels_db
            print("✅ Channels Database загружена")
        except ImportError as e:
            print(f"❌ Не удалось загрузить Channels DB: {e}")
            self.channels_db = None
    
    def get_channels_for_hour(self, hour=None):
        """Получает каналы для публикации в указанный час"""
        if not self.channels_db:
            self.logger.error("❌ Channels DB не доступна")
            return []
        
        if hour is None:
            hour = datetime.now().hour
        
        channels = self.channels_db.get_channels_for_publishing(hour)
        
        # Группируем по клиентам для оптимальной генерации
        channels_by_client = {}
        for channel in channels:
            client_id = channel['client_id']
            if client_id not in channels_by_client:
                channels_by_client[client_id] = []
            channels_by_client[client_id].append(channel)
        
        return channels_by_client
    
    def publish_for_client(self, client_id, channels):
        """
        Генерирует и публикует контент для всех каналов клиента
        
        Args:
            client_id: ID клиента
            channels: Список каналов клиента
        """
        if not channels:
            return
        
        self.logger.info(f"🚀 Публикация для клиента {client_id} ({len(channels)} каналов)")
        
        try:
            # 1. Выбираем тему для публикации
            # Берем первый канал и его темы
            first_channel = channels[0]
            channel_db_id = first_channel['channel_id']
            
            topics = self.channels_db.get_channel_topics(channel_db_id) if self.channels_db else []
            
            if not topics:
                self.logger.warning(f"⚠️ Нет тем для канала {channel_db_id}")
                return
            
            # Выбираем тему с наибольшим приоритетом
            selected_topic = max(topics, key=lambda x: x.get('priority', 1))
            topic_text = selected_topic['topic']
            keywords = selected_topic.get('keywords', [])
            
            self.logger.info(f"📝 Тема: {topic_text}")
            
            # 2. Генерируем статью (если есть writer)
            article = None
            if self.writer:
                article = self.writer.create_article_with_research(topic_text, keywords)
                
                if not article or len(article) < 200:
                    self.logger.error("❌ Статья не сгенерирована или слишком короткая")
                    article = f"📰 {topic_text}\n\nСтатья на данную тему будет скоро опубликована. Следите за обновлениями!"
                else:
                    self.logger.info(f"✅ Статья создана ({len(article)} символов)")
            else:
                article = f"📰 {topic_text}\n\nНовая публикация в нашем канале!"
            
            # 3. Генерируем изображение (если нужно и есть artist)
            image_path = None
            if self.artist and any(ch.get('use_ai_images', True) for ch in channels):
                image_path = self.artist.create_image_for_article(article, topic_text)
                if image_path:
                    self.logger.info(f"✅ Изображение создано: {image_path}")
                else:
                    self.logger.warning("⚠️ Изображение не создано")
            
            # 4. Публикуем во все каналы клиента
            if self.multi_publisher and article:
                results = self.multi_publisher.publish_to_multiple_channels(channels, article, image_path)
                
                # 5. Записываем результаты в БД
                successful = 0
                for i, result in enumerate(results):
                    channel = channels[i]
                    channel_db_id = channel['channel_id']
                    
                    if result.get('success'):
                        self.channels_db.add_channel_post(
                            channel_id=channel_db_id,
                            post_id=result.get('post_id'),
                            topic=topic_text,
                            content=article[:1500],
                            image_path=image_path,
                            success=True
                        )
                        successful += 1
                        
                        # Обновляем время последней публикации
                        client_name = channel.get('client_name', f'Клиент {client_id}')
                        if client_id not in self.last_published:
                            self.last_published[client_id] = {}
                        self.last_published[client_id][channel_db_id] = datetime.now()
                        
                        self.logger.info(f"✅ Опубликовано в {channel['platform']}:{channel['channel_name']}")
                    else:
                        self.channels_db.add_channel_post(
                            channel_id=channel_db_id,
                            post_id=None,
                            topic=topic_text,
                            content=article[:500],
                            success=False,
                            error_message=result.get('error', 'Unknown error')
                        )
                        self.logger.error(f"❌ Ошибка публикации в {channel['platform']}:{result.get('error')}")
                
                self.logger.info(f"📊 Итог для клиента {client_id}: {successful}/{len(channels)} успешно")
            
            # 6. Очищаем временные файлы изображений
            if image_path and os.path.exists(image_path):
                try:
                    os.remove(image_path)
                    self.logger.info(f"🗑️ Удален временный файл: {image_path}")
                except:
                    pass
                
        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка публикации для клиента {client_id}: {e}")
            import traceback
            traceback.print_exc()
    
    def hourly_publication_task(self):
        """Задача, выполняемая каждый час для публикации в каналы"""
        try:
            current_hour = datetime.now().hour
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            self.logger.info(f"⏰ Запуск hourly_publication_task в {current_time} (час: {current_hour})")
            
            # Получаем каналы для текущего часа
            channels_by_client = self.get_channels_for_hour(current_hour)
            
            if not channels_by_client:
                self.logger.info(f"ℹ️ Нет каналов для публикации в {current_hour}:00")
                return
            
            total_clients = len(channels_by_client)
            total_channels = sum(len(channels) for channels in channels_by_client.values())
            
            self.logger.info(f"📊 Найдено {total_clients} клиентов, {total_channels} каналов для публикации")
            
            # Публикуем для каждого клиента
            for client_id, channels in channels_by_client.items():
                # Запускаем в отдельном потоке для параллельной обработки клиентов
                thread = threading.Thread(
                    target=self.publish_for_client,
                    args=(client_id, channels),
                    daemon=True
                )
                thread.start()
                
                # Небольшая задержка между запуском потоков для разных клиентов
                time.sleep(1)
            
            self.logger.info(f"✅ Задачи публикации запущены для {total_clients} клиентов")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка в hourly_publication_task: {e}")
            import traceback
            traceback.print_exc()
    
    def run_test_publication(self, client_id=None):
        """Запускает тестовую публикацию"""
        print("\n🧪 ТЕСТОВАЯ ПУБЛИКАЦИЯ ДЛЯ КЛИЕНТОВ")
        print("=" * 60)
        
        print("🔍 Проверка компонентов:")
        print(f"   Writer: {'✅' if self.writer else '❌'}")
        print(f"   Artist: {'✅' if self.artist else '❌'}")
        print(f"   Multi Publisher: {'✅' if self.multi_publisher else '❌'}")
        print(f"   Channels DB: {'✅' if self.channels_db else '❌'}")
        print("=" * 60)
        
        # Если указан client_id, тестируем только его
        if client_id and self.channels_db:
            print(f"\n🔍 Тестирование для клиента {client_id}...")
            
            # Получаем каналы клиента
            channels_data = self.channels_db.get_client_channels(client_id, active_only=True)
            
            if not channels_data:
                print("❌ У клиента нет активных каналов")
                return False
            
            # Преобразуем в формат для публикатора
            channels = []
            for channel_data in channels_data:
                channel_db_id = channel_data[0]
                settings = self.channels_db.get_channel_settings(channel_db_id)
                
                channel_info = {
                    'channel_id': channel_db_id,
                    'platform': channel_data[2],
                    'platform_channel_id': channel_data[3],
                    'channel_name': channel_data[4],
                    'access_token': channel_data[5],
                    'use_ai_images': settings.get('use_ai_images', True) if settings else True
                }
                channels.append(channel_info)
            
            # Запускаем публикацию
            self.publish_for_client(client_id, channels)
            return True
        
        else:
            # Тестируем всех клиентов
            print("\n🚀 Тестовая публикация для всех клиентов...")
            
            # Получаем каналы для текущего часа
            channels_by_client = self.get_channels_for_hour()
            
            if not channels_by_client:
                print("⚠️ Нет активных клиентов с каналами для публикации")
                return False
            
            print(f"📊 Найдено {len(channels_by_client)} клиентов")
            
            # Ограничимся 2 клиентами для теста
            test_clients = list(channels_by_client.items())[:2]
            
            for client_id, channels in test_clients:
                print(f"\n👤 Клиент {client_id}: {len(channels)} каналов")
                
                # Запускаем публикацию
                self.publish_for_client(client_id, channels)
            
            print("\n" + "=" * 60)
            print("✅ Тестовая публикация запущена")
            return True
    
    def run(self):
        """Запускает планировщик"""
        print("\n🚀 ЗАПУСК MULTI-CHANNEL ПЛАНИРОВЩИКА")
        print("=" * 60)
        
        # Настраиваем расписание - проверка каждый час
        schedule.every().hour.at(":00").do(self.hourly_publication_task)
        
        # Также планируем проверку каждые 10 минут для отладки
        schedule.every(10).minutes.do(self._health_check)
        
        # Ежедневная статистика в 23:00
        schedule.every().day.at("23:00").do(self._daily_report)
        
        print("⏰ Планировщик запущен:")
        print("   • Проверка каждый час (в :00)")
        print("   • Отчет каждый день в 23:00")
        print("   • Проверка здоровья каждые 10 минут")
        print("\n🔄 Планировщик работает...")
        print("⏸️  Ctrl+C для остановки")
        
        # Тестовый запуск сразу (опционально)
        print("\n🧪 Запуск тестовой публикации...")
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
            current_time = datetime.now().strftime('%H:%M:%S')
            
            print(f"\n🔍 Проверка системы: {current_time}")
            
            # Проверяем компоненты
            components = {
                "Writer": self.writer is not None,
                "Artist": self.artist is not None,
                "Multi Publisher": self.multi_publisher is not None,
                "Channels DB": self.channels_db is not None
            }
            
            for name, status in components.items():
                print(f"   {name}: {'✅' if status else '❌'}")
            
            # Статистика клиентов
            if self.channels_db:
                cursor = self.channels_db.conn.cursor()
                
                # Количество активных клиентов
                cursor.execute("SELECT COUNT(*) FROM clients WHERE status = 'active'")
                active_clients = cursor.fetchone()[0]
                
                # Количество активных каналов
                cursor.execute('''
                SELECT COUNT(*) FROM client_channels cc
                JOIN clients c ON cc.client_id = c.id
                WHERE cc.is_active = 1 AND c.status = 'active'
                ''')
                active_channels = cursor.fetchone()[0]
                
                # Публикации сегодня
                today = datetime.now().date()
                cursor.execute('''
                SELECT COUNT(*) FROM channel_posts 
                WHERE DATE(published_at) = ?
                ''', (today,))
                posts_today = cursor.fetchone()[0]
                
                print(f"   👥 Активных клиентов: {active_clients}")
                print(f"   📺 Активных каналов: {active_channels}")
                print(f"   📝 Публикаций сегодня: {posts_today}")
            
            print("✅ Проверка завершена")
            
        except Exception as e:
            print(f"⚠️  Ошибка проверки здоровья: {e}")
    
    def _daily_report(self):
        """Ежедневный отчет"""
        try:
            if not self.channels_db:
                return
            
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            
            cursor = self.channels_db.conn.cursor()
            
            # Статистика за вчера
            cursor.execute('''
            SELECT 
                COUNT(DISTINCT cp.channel_id) as channels_with_posts,
                COUNT(cp.id) as total_posts,
                SUM(CASE WHEN cp.success = 1 THEN 1 ELSE 0 END) as successful_posts,
                SUM(CASE WHEN cp.success = 0 THEN 1 ELSE 0 END) as failed_posts
            FROM channel_posts cp
            WHERE DATE(cp.published_at) = ?
            ''', (yesterday,))
            
            stats = cursor.fetchone()
            
            if stats:
                channels_with_posts, total_posts, successful_posts, failed_posts = stats
                
                print(f"\n📊 ЕЖЕДНЕВНЫЙ ОТЧЕТ за {yesterday}")
                print("=" * 50)
                print(f"   Каналов с публикациями: {channels_with_posts}")
                print(f"   Всего публикаций: {total_posts}")
                print(f"   Успешных: {successful_posts}")
                print(f"   Неудачных: {failed_posts}")
                print("=" * 50)
                
                # Логируем отчет
                self.logger.info(f"📊 Daily Report: {total_posts} posts, {successful_posts} successful, {failed_posts} failed")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка формирования ежедневного отчета: {e}")


# Функции для быстрого использования
def start_multi_scheduler():
    """Запускает мультиканальный планировщик"""
    scheduler = MultiChannelScheduler()
    scheduler.run()

def test_client_publication(client_id: int):
    """Тестирует публикацию для конкретного клиента"""
    scheduler = MultiChannelScheduler()
    return scheduler.run_test_publication(client_id)

def get_client_stats(client_id: int):
    """Получает статистику клиента"""
    try:
        from database.channels_db import channels_db
        return channels_db.get_client_statistics(client_id)
    except:
        return None

# Тест
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("🧪 ТЕСТ MULTI-CHANNEL ПЛАНИРОВЩИКА")
    print("=" * 60)
    
    # Создаем планировщик
    scheduler = MultiChannelScheduler()
    
    # Тестовая публикация
    success = scheduler.run_test_publication()
    
    if success:
        print("\n✅ Система готова к работе!")
        print("\n💡 Для запуска планировщика используйте:")
        print("   scheduler.run()")
        print("\n💡 Для теста конкретного клиента:")
        print("   scheduler.run_test_publication(client_id=1)")
    else:
        print("\n⚠️  СИСТЕМА ТРЕБУЕТ НАСТРОЙКИ")
    
    print("\n" + "=" * 60)