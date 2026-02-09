# posting/telegram_sync.py
"""
Синхронная версия публикатора в Telegram
Использует правильный API для публикации в каналы
"""
import requests
import os
import json
import re
import sys
import time

# Добавляем родительскую директорию в путь
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TelegramSyncPoster:
    """
    Синхронный публикатор в Telegram канал
    Использует правильный формат для каналы
    """
    
    def __init__(self, bot_token=None, channel_id=None):
        # Если параметры не переданы, пытаемся взять из config
        if not bot_token or not channel_id:
            try:
                from config import Config
                self.bot_token = Config.TELEGRAM_CHANNEL_TOKEN
                self.channel_id = Config.TELEGRAM_CHANNEL_ID
            except ImportError:
                print("❌ Не удалось импортировать config.py")
                print("   Используйте: TelegramSyncPoster(bot_token='...', channel_id='...')")
                raise
        else:
            self.bot_token = bot_token
            self.channel_id = channel_id
        
        if not self.bot_token or not self.channel_id:
            raise ValueError("Не указаны bot_token или channel_id")
        
        # Проверяем формат channel_id
        if not self.channel_id.startswith('@') and not self.channel_id.startswith('-'):
            # Если это не @username и не -100... формат, добавляем @
            if not self.channel_id.startswith('-100'):
                self.channel_id = f"@{self.channel_id}"
        
        # Базовый URL для Telegram Bot API
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        
        print(f"✅ Telegram Sync Poster инициализирован")
        print(f"   Канал: {self.channel_id}")
        print(f"   Bot Token: {self.bot_token[:10]}...")
    
    def _send_photo_with_caption(self, image_path, caption):
        """Отправляет фото с подписью в канал"""
        try:
            url = f"{self.base_url}/sendPhoto"
            
            # Проверяем файл
            if not os.path.exists(image_path):
                print(f"❌ Файл не найден: {image_path}")
                return None
            
            file_size = os.path.getsize(image_path)
            print(f"📊 Размер файла: {file_size // 1024} KB")
            
            if file_size > 10 * 1024 * 1024:  # 10 MB limit
                print(f"❌ Файл слишком большой: {file_size // 1024} KB")
                return None
            
            # Сжимаем изображение если оно больше 2MB
            if file_size > 2 * 1024 * 1024:
                print("🔄 Сжимаю изображение...")
                compressed_path = self._compress_image(image_path)
                if compressed_path:
                    image_path = compressed_path
                    file_size = os.path.getsize(image_path)
                    print(f"📊 Новый размер: {file_size // 1024} KB")
            
            print(f"📤 Отправка фото с подписью ({file_size // 1024} KB)...")
            
            # Форматируем подпись (без лишнего экранирования)
            caption = self._clean_text_for_caption(caption)
            if len(caption) > 1024:
                caption = caption[:1020] + "..."
            
            # Подготавливаем данные
            data = {
                'chat_id': self.channel_id,
                'caption': caption,
                'parse_mode': 'HTML',
                'disable_notification': False
            }
            
            # Открываем файл и отправляем с увеличенным таймаутом
            with open(image_path, 'rb') as photo:
                files = {'photo': photo}
                
                # Увеличиваем таймаут для больших файлов
                timeout = 60 if file_size > 500 * 1024 else 30
                
                print(f"⏱️  Таймаут установлен: {timeout} секунд")
                start_time = time.time()
                
                response = requests.post(url, data=data, files=files, timeout=timeout)
                
                elapsed = time.time() - start_time
                print(f"📡 Ответ Telegram: {response.status_code} (за {elapsed:.1f} сек)")
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get('ok'):
                        message_id = result['result'].get('message_id')
                        print(f"✅ Фото с подписью отправлено, message_id: {message_id}")
                        return message_id
                    else:
                        error_desc = result.get('description', 'Unknown error')
                        print(f"❌ Ошибка Telegram API: {error_desc}")
                        
                        # Fallback: пробуем без HTML разметки
                        print("🔄 Пробую отправить без HTML разметки...")
                        data['parse_mode'] = None
                        response2 = requests.post(url, data=data, files=files, timeout=timeout)
                        if response2.status_code == 200:
                            result2 = response2.json()
                            if result2.get('ok'):
                                message_id = result2['result'].get('message_id')
                                print(f"✅ Фото отправлено без HTML, message_id: {message_id}")
                                return message_id
                        
                        return None
                else:
                    print(f"❌ HTTP ошибка: {response.status_code}")
                    return None
                    
        except requests.exceptions.Timeout:
            print("❌ Таймаут при отправке фото.")
            return None
        except Exception as e:
            print(f"❌ Ошибка отправки фото: {type(e).__name__}: {e}")
            return None
    
    def _compress_image(self, image_path, max_size_kb=1500):
        """Сжимает изображение до указанного размера"""
        try:
            from PIL import Image
            import io
            
            # Открываем изображение
            img = Image.open(image_path)
            
            # Сохраняем оригинальный формат
            original_format = img.format
            
            # Если это JPEG, можем регулировать качество
            if original_format == 'JPEG' or image_path.lower().endswith(('.jpg', '.jpeg')):
                # Пробуем разные уровни качества
                for quality in [85, 75, 65, 55]:
                    buffer = io.BytesIO()
                    img.save(buffer, format='JPEG', quality=quality, optimize=True)
                    size_kb = len(buffer.getvalue()) // 1024
                    
                    if size_kb <= max_size_kb:
                        # Сохраняем сжатый файл
                        compressed_path = image_path.replace('.jpg', f'_compressed_{quality}.jpg')
                        with open(compressed_path, 'wb') as f:
                            f.write(buffer.getvalue())
                        print(f"✅ Сжато до {size_kb} KB (качество: {quality}%)")
                        return compressed_path
            
            # Для других форматов или если JPEG сжатие не помогло
            # Масштабируем изображение
            width, height = img.size
            if width > 1200 or height > 1200:
                # Вычисляем новый размер
                ratio = min(1200/width, 1200/height)
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                print(f"🔄 Изменен размер: {width}x{height} → {new_width}x{new_height}")
            
            # Сохраняем
            compressed_path = image_path.replace('.jpg', '_compressed.jpg').replace('.png', '_compressed.jpg')
            img.save(compressed_path, format='JPEG', quality=85, optimize=True)
            
            size_kb = os.path.getsize(compressed_path) // 1024
            print(f"✅ Сжато до {size_kb} KB")
            
            return compressed_path
            
        except ImportError:
            print("⚠️  Pillow не установлен, не могу сжать изображение")
            return None
        except Exception as e:
            print(f"❌ Ошибка сжатия изображения: {e}")
            return None
    
    def _send_message_only(self, text):
        """Отправляет только текстовое сообщение (без фото)"""
        try:
            url = f"{self.base_url}/sendMessage"
            
            # Форматируем текст
            text = self._clean_text_for_message(text)
            
            data = {
                'chat_id': self.channel_id,
                'text': text,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True,
                'disable_notification': False
            }
            
            print("📤 Отправка текстового сообщения...")
            
            response = requests.post(url, json=data, timeout=30)
            
            print(f"📡 Ответ Telegram: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    message_id = result['result'].get('message_id')
                    print(f"✅ Сообщение отправлено, message_id: {message_id}")
                    return message_id
                else:
                    error_desc = result.get('description', 'Unknown error')
                    print(f"❌ Ошибка Telegram API: {error_desc}")
                    return None
            else:
                print(f"❌ HTTP ошибка: {response.status_code}")
                print(f"Ответ: {response.text[:200]}")
                return None
                
        except Exception as e:
            print(f"❌ Ошибка отправки сообщения: {e}")
            return None
    
    def _clean_text_for_caption(self, text):
        """
        Очищает текст для подписи к фото
        Максимально просто, минимум разметки
        """
        if not text:
            return ""
        
        # 1. Убираем все HTML теги
        text = re.sub(r'<[^>]+>', '', text)
        
        # 2. Экранируем только < и >, но не трогаем &
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        
        # 3. Делаем первую строку жирной (если она не пустая)
        lines = text.strip().split('\n')
        if lines:
            first_line = lines[0].strip()
            if first_line:
                lines[0] = f'<b>{first_line}</b>'
        
        # 4. Собираем обратно
        text = '\n'.join(lines)
        
        # 5. Ограничиваем длину
        if len(text) > 1024:  # Ограничение для подписей
            text = text[:1020] + "..."
        
        return text.strip()
    
    def _clean_text_for_message(self, text):
        """
        Очищает текст для отдельного сообщения
        """
        if not text:
            return ""
        
        # 1. Убираем все HTML теги
        text = re.sub(r'<[^>]+>', '', text)
        
        # 2. Экранируем только < и >
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        
        # 3. Находим первую значимую строку и делаем ее жирной
        lines = text.strip().split('\n')
        for i, line in enumerate(lines):
            line = line.strip()
            if line and len(line) > 10:  # Нашли значимую строку
                lines[i] = f'<b>{line}</b>'
                break
        
        # 4. Собираем обратно
        text = '\n'.join(lines)
        
        # 5. Ограничиваем длину
        if len(text) > 4096:
            text = text[:4090] + "..."
        
        return text.strip()
    
    def post_article(self, article_text, image_path=None):
        """
        Публикует статью в Telegram канал
        
        Args:
            article_text: Текст статьи
            image_path: Путь к изображению (опционально)
            
        Returns:
            message_id или None
        """
        print(f"📤 Публикация в Telegram канал {self.channel_id}")
        
        try:
            # 1. Если есть изображение, отправляем фото с подписью
            if image_path and os.path.exists(image_path):
                print(f"📷 Отправка фото с текстом...")
                
                # Обрезаем текст для подписи (макс 1024 символа)
                caption = article_text
                if len(caption) > 1000:
                    # Пробуем найти хорошее место для обрезки
                    if '\n\n' in caption:
                        parts = caption.split('\n\n')
                        caption = parts[0]
                        if len(parts) > 1:
                            caption += '\n\n' + parts[1][:200] + "..."
                    else:
                        caption = caption[:970] + "..."
                
                message_id = self._send_photo_with_caption(image_path, caption)
                
                if message_id:
                    print(f"✅ Статья с изображением опубликована. Message ID: {message_id}")
                    
                    # 2. Если текст длинный, отправляем остаток отдельным сообщением
                    if len(article_text) > 1000:
                        print("📝 Текст длинный, отправляю продолжение...")
                        
                        # Вырезаем уже отправленную часть
                        remaining_text = article_text[len(caption):].strip()
                        if remaining_text and len(remaining_text) > 50:
                            # Добавляем пометку что это продолжение
                            remaining_text = f"📄 Продолжение:\n\n{remaining_text}"
                            self._send_message_only(remaining_text)
                    
                    return message_id
                else:
                    print("⚠️  Не удалось отправить с изображением, пробую только текст...")
            
            # 3. Fallback: отправляем только текст
            print("📝 Отправка только текста...")
            message_id = self._send_message_only(article_text)
            
            if message_id:
                print(f"✅ Текст опубликован. Message ID: {message_id}")
                return message_id
            else:
                print("❌ Не удалось опубликовать в Telegram")
                return None
                
        except Exception as e:
            print(f"❌ Критическая ошибка публикации в Telegram: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def send_test_message(self):
        """Отправляет тестовое сообщение для проверки"""
        try:
            test_text = """🧪 Тестовая публикация от Snoomi Platform

✅ Генерация статей работает
✅ Генерация изображений работает
✅ Публикация в VK работает
✅ Теперь и в Telegram!

Это тест системы публикации контента.

#тест #snoomi #матрасы #здоровыйсон"""
            
            print("🧪 Отправка тестового сообщения...")
            message_id = self._send_message_only(test_text)
            
            if message_id:
                print(f"🎉 Тест пройден! Message ID: {message_id}")
                return True
            else:
                print("❌ Тест не пройден")
                return False
                
        except Exception as e:
            print(f"❌ Ошибка тестового сообщения: {e}")
            return False

# Обновим также функцию генерации статей, чтобы текст был в правильном формате
def format_article_for_telegram(article_text, max_length=1000):
    """
    Форматирует статью для публикации в Telegram
    """
    if not article_text:
        return ""
    
    # 1. Убираем лишние HTML теги если есть
    article_text = re.sub(r'<[^>]+>', '', article_text)
    
    # 2. Убираем лишние переносы строк
    article_text = re.sub(r'\n{3,}', '\n\n', article_text)
    
    # 3. Если статья слишком длинная, обрезаем в логичном месте
    if len(article_text) > max_length:
        # Ищем место для обрезки после абзаца
        cut_pos = article_text.rfind('\n\n', 0, max_length)
        if cut_pos == -1:
            cut_pos = article_text.rfind('\n', 0, max_length)
        if cut_pos == -1:
            cut_pos = article_text.rfind('. ', 0, max_length)
        if cut_pos == -1:
            cut_pos = max_length
        
        article_text = article_text[:cut_pos] + "..."
    
    return article_text

# Простая функция для быстрого использования
def post_to_telegram_simple(article_text, image_path=None, bot_token=None, channel_id=None):
    """Простая синхронная функция для публикации"""
    if not bot_token or not channel_id:
        print("❌ Не указаны bot_token или channel_id")
        return None
    
    # Форматируем статью
    article_text = format_article_for_telegram(article_text)
    
    poster = TelegramSyncPoster(bot_token, channel_id)
    return poster.post_article(article_text, image_path)

# Функция для тестирования
def test_telegram_connection(bot_token=None, channel_id=None):
    """Тестирует подключение к Telegram"""
    print("🧪 Тест подключения к Telegram")
    print("="*50)
    
    try:
        if not bot_token or not channel_id:
            # Пытаемся получить из конфига
            try:
                from config import Config
                bot_token = Config.TELEGRAM_CHANNEL_TOKEN
                channel_id = Config.TELEGRAM_CHANNEL_ID
            except ImportError:
                print("❌ Не удалось получить настройки Telegram")
                return False
        
        poster = TelegramSyncPoster(bot_token, channel_id)
        
        print("\n1. Отправка тестового сообщения...")
        success = poster.send_test_message()
        
        if success:
            print("\n🎉 Все тесты пройдены!")
            return True
        else:
            print("\n❌ Тесты не пройдены")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка теста: {e}")
        return False

# Тест
if __name__ == "__main__":
    print("🧪 Тест Telegram публикатора")
    print("="*50)
    
    # Сначала пробуем импортировать конфиг
    try:
        import sys
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from config import Config
        
        if Config.TELEGRAM_CHANNEL_TOKEN and Config.TELEGRAM_CHANNEL_ID:
            print("✅ Конфигурация Telegram найдена")
            
            # Тестируем подключение
            test_ok = test_telegram_connection(
                Config.TELEGRAM_CHANNEL_TOKEN,
                Config.TELEGRAM_CHANNEL_ID
            )
            
            if test_ok:
                print("\n🔄 Тест публикации с изображением...")
                
                # Ищем тестовое изображение
                test_image = None
                try:
                    import glob
                    image_patterns = ['yandex_art_*.jpg', 'simple_*.jpg', 'test_*.jpg']
                    
                    for pattern in image_patterns:
                        files = glob.glob(pattern)
                        if files:
                            test_image = files[0]
                            break
                except:
                    pass
                
                if test_image:
                    print(f"📷 Найдено изображение: {test_image}")
                    
                    test_text = """🎯 Тест публикации с изображением в одном посте

✅ Текст и изображение отправляются вместе
✅ Это выглядит как единый пост
✅ Пользователи видят всё сразу

Это тест правильной публикации контента в Telegram.

#тест #snoomi #telegram"""
                    
                    result = post_to_telegram_simple(
                        test_text,
                        test_image,
                        bot_token=Config.TELEGRAM_CHANNEL_TOKEN,
                        channel_id=Config.TELEGRAM_CHANNEL_ID
                    )
                    
                    if result:
                        print(f"🎉 Тест пройден! Message ID: {result}")
                    else:
                        print("❌ Тест публикации не пройден")
                else:
                    print("⚠️  Тестовое изображение не найдено, тестирую только текст")
                    test_ok = test_telegram_connection(
                        Config.TELEGRAM_CHANNEL_TOKEN,
                        Config.TELEGRAM_CHANNEL_ID
                    )
            else:
                print("❌ Тест подключения не пройден")
        else:
            print("⚠️  TELEGRAM_CHANNEL_TOKEN или TELEGRAM_CHANNEL_ID не настроены в конфиге")
            
    except ImportError as e:
        print("❌ Не удалось импортировать config.py")
        print("Создайте файл .env с настройками:")
        print("TELEGRAM_CHANNEL_TOKEN=ваш_токен_бота")
        print("TELEGRAM_CHANNEL_ID=@ваш_канал_или_id")
        print("\nИли используйте класс напрямую:")
        print("from posting.telegram_sync import TelegramSyncPoster")
        print("poster = TelegramSyncPoster(bot_token='ваш_токен', channel_id='@ваш_канал')")
        print("poster.send_test_message()")
    
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()