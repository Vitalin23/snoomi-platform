# posting/tg_poster.py
import asyncio
import logging
from telegram import Bot
from telegram.error import TelegramError, NetworkError
import aiohttp

logger = logging.getLogger(__name__)

class TelegramPoster:
    """
    Класс для публикации контента в Telegram канал
    Использует Telegram Bot API
    """
    
    def __init__(self, bot_token, channel_id):
        """
        Инициализация публикатора
        
        Args:
            bot_token: Токен бота для публикации
            channel_id: ID канала или @username
        """
        self.bot = Bot(token=bot_token)
        self.channel_id = channel_id
        self.logger = logging.getLogger(__name__)
        
        # Проверяем доступность
        self._check_access()
    
    def _check_access(self):
        """Проверяет доступ к каналу"""
        try:
            # Пробуем получить информацию о боте
            asyncio.run(self.bot.get_me())
            self.logger.info("✅ Telegram Bot доступен")
            return True
        except Exception as e:
            self.logger.error(f"❌ Ошибка доступа к Telegram: {e}")
            return False
    
    async def _send_photo_with_caption(self, image_path, caption):
        """Отправляет фото с подписью"""
        try:
            with open(image_path, 'rb') as photo:
                message = await self.bot.send_photo(
                    chat_id=self.channel_id,
                    photo=photo,
                    caption=caption[:1024],  # Ограничение Telegram на подпись
                    parse_mode='HTML'
                )
            return message
        except FileNotFoundError:
            self.logger.error(f"❌ Файл не найден: {image_path}")
            return None
    
    async def _send_text_message(self, text):
        """Отправляет текстовое сообщение"""
        try:
            message = await self.bot.send_message(
                chat_id=self.channel_id,
                text=text,
                parse_mode='HTML',
                disable_web_page_preview=False
            )
            return message
        except Exception as e:
            self.logger.error(f"❌ Ошибка отправки текста: {e}")
            return None
    
    async def post_article(self, article_text, image_path=None):
        """
        Публикует статью в Telegram канал
        
        Args:
            article_text: Текст статьи (можно с HTML разметкой)
            image_path: Путь к изображению (опционально)
            
        Returns:
            message_id или None в случае ошибки
        """
        try:
            self.logger.info(f"📤 Публикация в Telegram канал {self.channel_id}")
            
            # Форматируем текст для Telegram
            formatted_text = self._format_for_telegram(article_text)
            
            # Если есть изображение - отправляем с подписью
            if image_path:
                message = await self._send_photo_with_caption(image_path, formatted_text)
            else:
                message = await self._send_text_message(formatted_text)
            
            if message:
                self.logger.info(f"✅ Опубликовано в Telegram: {message.message_id}")
                
                # Если текст длинный, отправляем продолжение
                if len(article_text) > 1024:
                    await self._send_remaining_text(article_text[1024:])
                
                return message.message_id
            else:
                return None
                
        except NetworkError as e:
            self.logger.error(f"📡 Ошибка сети Telegram: {e}")
            return None
        except TelegramError as e:
            self.logger.error(f"❌ Ошибка Telegram API: {e}")
            return None
        except Exception as e:
            self.logger.error(f"❌ Неизвестная ошибка: {e}")
            return None
    
    async def _send_remaining_text(self, remaining_text):
        """Отправляет оставшийся текст отдельным сообщением"""
        try:
            chunks = self._split_text(remaining_text, 4096)  # Ограничение Telegram
            for chunk in chunks:
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=chunk,
                    parse_mode='HTML'
                )
        except Exception as e:
            self.logger.error(f"❌ Ошибка отправки продолжения: {e}")
    
    def _format_for_telegram(self, text):
        """Форматирует текст для Telegram"""
        # Заменяем Markdown на HTML если нужно
        text = text.replace('**', '<b>').replace('**', '</b>')
        text = text.replace('*', '<i>').replace('*', '</i>')
        text = text.replace('__', '<u>').replace('__', '</u>')
        
        # Убеждаемся что теги закрыты
        return text
    
    def _split_text(self, text, max_length):
        """Разбивает текст на части"""
        chunks = []
        while len(text) > max_length:
            # Ищем точку разрыва
            split_pos = text.rfind('\n', 0, max_length)
            if split_pos == -1:
                split_pos = text.rfind(' ', 0, max_length)
            if split_pos == -1:
                split_pos = max_length
            
            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip()
        
        if text:
            chunks.append(text)
        
        return chunks

# Функция для синхронного использования
def post_to_telegram_sync(article_text, image_path=None, 
                         bot_token=None, channel_id=None):
    """
    Синхронная обертка для публикации в Telegram
    """
    if not bot_token or not channel_id:
        logger.error("❌ Не указаны bot_token или channel_id")
        return None
    
    poster = TelegramPoster(bot_token, channel_id)
    
    # Создаем event loop для асинхронного вызова
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(
        poster.post_article(article_text, image_path)
    )

# Быстрый тест
if __name__ == "__main__":
    import sys
    sys.path.append('..')
    
    from config import Config
    
    # Тестируем подключение
    if Config.TELEGRAM_CHANNEL_TOKEN and Config.TELEGRAM_CHANNEL_ID:
        print("🔍 Тестирование Telegram Poster...")
        
        poster = TelegramPoster(
            Config.TELEGRAM_CHANNEL_TOKEN,
            Config.TELEGRAM_CHANNEL_ID
        )
        
        # Тестовый пост
        test_text = "🧪 <b>Тестовый пост от Snoomi Platform</b>\n\nЭто тестовая публикация для проверки работы системы."
        
        result = asyncio.run(poster.post_article(test_text))
        
        if result:
            print(f"✅ Тест пройден! ID сообщения: {result}")
        else:
            print("❌ Тест не пройден")
    else:
        print("⚠️  TELEGRAM_CHANNEL_TOKEN или TELEGRAM_CHANNEL_ID не настроены")