# posting/multi_publisher.py
"""
Мультиплатформенный публикатор для работы с каналами клиентов
"""
import os
import sys
import time
import logging
from typing import Dict, List, Optional, Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

class MultiPlatformPublisher:
    """Публикатор для работы с разными платформами"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.publishers = {}
        self._init_publishers()
    
    def _init_publishers(self):
        """Инициализирует публикаторы для разных платформ"""
        try:
            # Telegram публикатор
            from posting.telegram_sync import TelegramSyncPoster
            self.telegram_publisher = TelegramSyncPoster
            self.logger.info("✅ Telegram публикатор загружен")
        except ImportError as e:
            self.logger.error(f"❌ Не удалось загрузить Telegram публикатор: {e}")
            self.telegram_publisher = None
        
        try:
            # VK публикатор
            from posting.vk_publisher import VKPublisher
            self.vk_publisher = VKPublisher
            self.logger.info("✅ VK публикатор загружен")
        except ImportError as e:
            self.logger.error(f"❌ Не удалось загрузить VK публикатор: {e}")
            self.vk_publisher = None
    
    def publish_to_channel(self, channel_info: Dict, article: str, image_path: Optional[str] = None) -> Dict:
        """
        Публикует контент в указанный канал
        
        Args:
            channel_info: Информация о канале из БД
            article: Текст статьи
            image_path: Путь к изображению
            
        Returns:
            Dict с результатом публикации
        """
        platform = channel_info.get('platform')
        channel_id = channel_info.get('platform_channel_id')
        access_token = channel_info.get('access_token')
        channel_name = channel_info.get('channel_name', 'Unknown')
        
        self.logger.info(f"📤 Публикация в {platform} канал: {channel_name}")
        
        result = {
            'platform': platform,
            'channel_id': channel_id,
            'channel_name': channel_name,
            'success': False,
            'post_id': None,
            'error': None,
            'timestamp': time.time()
        }
        
        try:
            if platform == 'telegram':
                result = self._publish_to_telegram(channel_info, article, image_path)
            
            elif platform == 'vk':
                result = self._publish_to_vk(channel_info, article, image_path)
            
            elif platform == 'ok':  # Одноклассники
                result = self._publish_to_ok(channel_info, article, image_path)
            
            elif platform == 'dzen':  # Яндекс.Дзен
                result = self._publish_to_dzen(channel_info, article, image_path)
            
            else:
                result['error'] = f"Платформа {platform} не поддерживается"
                self.logger.error(f"❌ Неподдерживаемая платформа: {platform}")
        
        except Exception as e:
            result['error'] = str(e)
            self.logger.error(f"❌ Ошибка публикации в {platform}: {e}")
        
        return result
    
    def _publish_to_telegram(self, channel_info: Dict, article: str, image_path: Optional[str]) -> Dict:
        """Публикует в Telegram канал"""
        if not self.telegram_publisher:
            return {'error': 'Telegram публикатор не инициализирован', 'success': False}
        
        try:
            # Форматируем статью для Telegram
            from posting.telegram_sync import format_article_for_telegram
            formatted_article = format_article_for_telegram(article)
            
            # Добавляем хештеги из настроек канала
            hashtags = channel_info.get('hashtags', [])
            if hashtags and isinstance(hashtags, list):
                formatted_article += "\n\n" + " ".join(hashtags)
            
            # Создаем публикатор с токеном из канала
            bot_token = channel_info.get('access_token')
            if not bot_token:
                # Если токен не указан в канале, пробуем из конфига
                try:
                    from config import Config
                    bot_token = Config.TELEGRAM_CHANNEL_TOKEN
                except:
                    return {'error': 'Не указан Telegram токен', 'success': False}
            
            poster = self.telegram_publisher(
                bot_token=bot_token,
                channel_id=channel_info['platform_channel_id']
            )
            
            # Публикуем
            message_id = poster.post_article(formatted_article, image_path)
            
            if message_id:
                return {
                    'success': True,
                    'post_id': str(message_id),
                    'platform': 'telegram',
                    'channel_id': channel_info['platform_channel_id']
                }
            else:
                return {'error': 'Не удалось опубликовать в Telegram', 'success': False}
                
        except Exception as e:
            return {'error': str(e), 'success': False}
    
    def _publish_to_vk(self, channel_info: Dict, article: str, image_path: Optional[str]) -> Dict:
        """Публикует в VK группу"""
        if not self.vk_publisher:
            return {'error': 'VK публикатор не инициализирован', 'success': False}
        
        try:
            # Настраиваем публикатор с токеном из канала
            access_token = channel_info.get('access_token')
            group_id = channel_info['platform_channel_id']
            
            if not access_token:
                # Если токен не указан в канале, пробуем из конфига
                try:
                    from config import Config
                    access_token = Config.VK_ACCESS_TOKEN
                except:
                    return {'error': 'Не указан VK токен', 'success': False}
            
            # Монтируем временный конфиг для этого канала
            class TempConfig:
                VK_ACCESS_TOKEN = access_token
                VK_GROUP_ID = group_id
            
            # Создаем публикатор
            publisher = self.vk_publisher()
            
            # Переопределяем настройки
            publisher.token = access_token
            publisher.group_id = group_id
            
            # Публикуем
            post_id = publisher.publish_article(article, image_path)
            
            if post_id:
                return {
                    'success': True,
                    'post_id': str(post_id),
                    'platform': 'vk',
                    'channel_id': group_id
                }
            else:
                return {'error': 'Не удалось опубликовать в VK', 'success': False}
                
        except Exception as e:
            return {'error': str(e), 'success': False}
    
    def _publish_to_ok(self, channel_info: Dict, article: str, image_path: Optional[str]) -> Dict:
        """Публикует в Одноклассники (заглушка - нужно реализовать)"""
        # TODO: Реализовать публикацию в OK
        return {
            'success': False,
            'error': 'Публикация в Одноклассники пока не реализована',
            'platform': 'ok'
        }
    
    def _publish_to_dzen(self, channel_info: Dict, article: str, image_path: Optional[str]) -> Dict:
        """Публикует в Яндекс.Дзен (заглушка - нужно реализовать)"""
        # TODO: Реализовать публикацию в Дзен
        return {
            'success': False,
            'error': 'Публикация в Яндекс.Дзен пока не реализована',
            'platform': 'dzen'
        }
    
    def publish_to_multiple_channels(self, channels: List[Dict], article: str, 
                                   image_path: Optional[str] = None) -> List[Dict]:
        """
        Публикует один контент в несколько каналов
        
        Args:
            channels: Список каналов для публикации
            article: Текст статьи
            image_path: Путь к изображению
            
        Returns:
            Список результатов публикации для каждого канала
        """
        results = []
        
        self.logger.info(f"📤 Начало мультипубликации в {len(channels)} каналов")
        
        for i, channel in enumerate(channels, 1):
            self.logger.info(f"  {i}/{len(channels)}: {channel.get('platform')}:{channel.get('channel_name')}")
            
            result = self.publish_to_channel(channel, article, image_path)
            results.append(result)
            
            # Небольшая задержка между публикациями
            if i < len(channels):
                time.sleep(2)
        
        # Анализируем результаты
        successful = sum(1 for r in results if r.get('success'))
        failed = len(results) - successful
        
        self.logger.info(f"📊 Результаты мультипубликации: {successful} ✅, {failed} ❌")
        
        return results
    
    def test_channel_connection(self, channel_info: Dict) -> Dict:
        """
        Тестирует подключение к каналу
        
        Args:
            channel_info: Информация о канале
            
        Returns:
            Dict с результатом теста
        """
        platform = channel_info.get('platform')
        channel_id = channel_info.get('platform_channel_id')
        channel_name = channel_info.get('channel_name', 'Unknown')
        
        self.logger.info(f"🔍 Тестирование подключения: {platform}:{channel_name}")
        
        test_result = {
            'platform': platform,
            'channel_id': channel_id,
            'channel_name': channel_name,
            'connected': False,
            'error': None,
            'timestamp': time.time()
        }
        
        try:
            if platform == 'telegram':
                test_result = self._test_telegram_connection(channel_info)
            
            elif platform == 'vk':
                test_result = self._test_vk_connection(channel_info)
            
            else:
                test_result['error'] = f"Тестирование платформы {platform} не реализовано"
        
        except Exception as e:
            test_result['error'] = str(e)
        
        return test_result
    
    def _test_telegram_connection(self, channel_info: Dict) -> Dict:
        """Тестирует подключение к Telegram каналу"""
        try:
            from posting.telegram_sync import test_telegram_connection
            
            bot_token = channel_info.get('access_token')
            if not bot_token:
                try:
                    from config import Config
                    bot_token = Config.TELEGRAM_CHANNEL_TOKEN
                except:
                    return {'error': 'Не указан Telegram токен', 'connected': False}
            
            success = test_telegram_connection(
                bot_token=bot_token,
                channel_id=channel_info['platform_channel_id']
            )
            
            return {
                'connected': success,
                'platform': 'telegram',
                'channel_id': channel_info['platform_channel_id']
            }
            
        except Exception as e:
            return {'error': str(e), 'connected': False}
    
    def _test_vk_connection(self, channel_info: Dict) -> Dict:
        """Тестирует подключение к VK группе"""
        try:
            import vk_api
            
            access_token = channel_info.get('access_token')
            if not access_token:
                try:
                    from config import Config
                    access_token = Config.VK_ACCESS_TOKEN
                except:
                    return {'error': 'Не указан VK токен', 'connected': False}
            
            # Пробуем подключиться
            vk_session = vk_api.VkApi(token=access_token)
            vk = vk_session.get_api()
            
            # Получаем информацию о группе
            group_id = channel_info['platform_channel_id'].replace('-', '')
            group_info = vk.groups.getById(group_id=group_id)
            
            if group_info:
                return {
                    'connected': True,
                    'platform': 'vk',
                    'channel_id': channel_info['platform_channel_id'],
                    'group_name': group_info[0]['name']
                }
            else:
                return {'error': 'Не удалось получить информацию о группе', 'connected': False}
                
        except Exception as e:
            return {'error': str(e), 'connected': False}


# Утилита для быстрого использования
def publish_to_client_channels(client_id: int, topic: str, keywords: List[str] = None) -> Dict:
    """
    Упрощенная функция для публикации во все каналы клиента
    
    Args:
        client_id: ID клиента в БД
        topic: Тема для публикации
        keywords: Ключевые слова для генерации
        
    Returns:
        Dict с общими результатами
    """
    try:
        from database.channels_db import channels_db
        from ai.yandex_research_writer import YandexResearchWriter
        from ai.yandex_art_final import YandexArtGenerator
        
        logger.info(f"🚀 Запуск публикации для клиента {client_id}")
        
        # 1. Получаем каналы клиента
        channels_data = channels_db.get_client_channels(client_id, active_only=True)
        if not channels_data:
            return {'error': 'У клиента нет активных каналов', 'success': False}
        
        # 2. Подготавливаем список каналов
        channels = []
        for channel_data in channels_data:
            channel_id = channel_data[0]  # ID канала в БД
            settings = channels_db.get_channel_settings(channel_id)
            
            if settings and settings.get('is_auto_generate', True):
                channel_info = {
                    'channel_db_id': channel_id,
                    'platform': channel_data[2],  # platform
                    'platform_channel_id': channel_data[3],  # channel_id
                    'channel_name': channel_data[4],  # channel_name
                    'access_token': channel_data[5],  # access_token
                    'hashtags': settings.get('hashtags', [])
                }
                channels.append(channel_info)
        
        if not channels:
            return {'error': 'Нет каналов с автогенерацией', 'success': False}
        
        # 3. Генерируем контент
        writer = YandexResearchWriter()
        article = writer.create_article_with_research(topic, keywords)
        
        if not article or len(article) < 200:
            return {'error': 'Не удалось сгенерировать статью', 'success': False}
        
        # 4. Генерируем изображение (если нужно)
        image_path = None
        if any(ch.get('use_ai_images', True) for ch in channels):
            artist = YandexArtGenerator()
            image_path = artist.create_image_for_article(article, topic)
        
        # 5. Публикуем во все каналы
        publisher = MultiPlatformPublisher()
        results = publisher.publish_to_multiple_channels(channels, article, image_path)
        
        # 6. Записываем результаты в БД
        successful_posts = 0
        for i, result in enumerate(results):
            if result.get('success'):
                channel_db_id = channels[i]['channel_db_id']
                channels_db.add_channel_post(
                    channel_id=channel_db_id,
                    post_id=result.get('post_id'),
                    topic=topic,
                    content=article[:1000],  # Сохраняем начало статьи
                    image_path=image_path,
                    success=True
                )
                successful_posts += 1
            else:
                # Записываем ошибку
                channel_db_id = channels[i]['channel_db_id']
                channels_db.add_channel_post(
                    channel_id=channel_db_id,
                    post_id=None,
                    topic=topic,
                    content=article[:500],
                    success=False,
                    error_message=result.get('error', 'Unknown error')
                )
        
        # 7. Возвращаем итоговый результат
        return {
            'success': successful_posts > 0,
            'total_channels': len(channels),
            'successful_posts': successful_posts,
            'failed_posts': len(channels) - successful_posts,
            'topic': topic,
            'article_length': len(article),
            'has_image': image_path is not None
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка публикации для клиента: {e}")
        return {'error': str(e), 'success': False}


# Тест
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("🧪 Тест мультиплатформенного публикатора")
    print("=" * 60)
    
    # Тестируем публикатор
    publisher = MultiPlatformPublisher()
    
    # Тестовые данные
    test_channel = {
        'platform': 'telegram',
        'platform_channel_id': '@mag_snoomi',
        'channel_name': 'Тестовый канал',
        'hashtags': ['#тест', '#snoomi']
    }
    
    test_article = """🎯 Тестовая публикация в мультиканальной системе

✅ Система поддерживает несколько каналов
✅ Автоматическая генерация контента
✅ Публикация в разные соцсети
✅ Отслеживание статистики

Это тест новой системы монетизации Snoomi Platform.

#тест #мультиканальность #snoomi"""
    
    print("1. Тестируем подключение к каналу...")
    connection_test = publisher.test_channel_connection(test_channel)
    print(f"   Результат: {'✅' if connection_test.get('connected') else '❌'}")
    
    print("\n2. Тестируем публикацию...")
    # В реальном тесте нужно раскомментировать:
    # result = publisher.publish_to_channel(test_channel, test_article)
    # print(f"   Результат: {'✅' if result.get('success') else '❌'}")
    print("   (Публикация временно отключена для теста)")
    
    print("\n3. Тестируем функцию публикации для клиента...")
    # В реальном тесте нужно раскомментировать:
    # client_result = publish_to_client_channels(1, "Тест мультиканальности")
    # print(f"   Результат: {client_result}")
    print("   (Требуется база данных с тестовым клиентом)")
    
    print("\n" + "=" * 60)
    print("✅ Тест публикатора завершен")