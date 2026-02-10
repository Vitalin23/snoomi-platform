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
        temp_files = []
        try:
            url = f"{self.base_url}/sendPhoto"
            print("🔁 sendPhoto resilient mode v2")

            # Проверяем файл
            if not os.path.exists(image_path):
                print(f"❌ Файл не найден: {image_path}")
                return None

            file_size = os.path.getsize(image_path)
            print(f"📊 Размер файла: {file_size // 1024} KB")

            if file_size > 10 * 1024 * 1024:  # 10 MB limit
                print(f"❌ Файл слишком большой: {file_size // 1024} KB")
                return None

            # Форматируем подпись (без лишнего экранирования)
            caption = self._clean_text_for_caption(caption)
            if len(caption) > 1024:
                caption = caption[:1020] + "..."

            # Готовим список кандидатов файла: оригинал + варианты сжатия.
            upload_candidates = []
            if file_size > 700 * 1024:
                print("🔄 Подготовка сжатых копий для стабильной отправки...")
                compressed_800 = self._compress_image(image_path, max_size_kb=800)
                if compressed_800 and compressed_800 not in upload_candidates:
                    upload_candidates.append(compressed_800)
                    temp_files.append(compressed_800)
                compressed_550 = self._compress_image(image_path, max_size_kb=550)
                if compressed_550 and compressed_550 not in upload_candidates:
                    upload_candidates.append(compressed_550)
                    temp_files.append(compressed_550)
                compressed_400 = self._compress_image(image_path, max_size_kb=400)
                if compressed_400 and compressed_400 not in upload_candidates:
                    upload_candidates.append(compressed_400)
                    temp_files.append(compressed_400)

            # Оригинал пробуем тоже, но после более легких вариантов.
            if image_path not in upload_candidates:
                upload_candidates.append(image_path)

            parse_modes = ["HTML", None]
            last_error = None

            for candidate_index, candidate_path in enumerate(upload_candidates, start=1):
                if not os.path.exists(candidate_path):
                    continue
                candidate_size = os.path.getsize(candidate_path)
                print(
                    f"📤 Кандидат {candidate_index}/{len(upload_candidates)}: "
                    f"{os.path.basename(candidate_path)} ({candidate_size // 1024} KB)"
                )

                # Для крупных файлов увеличиваем read timeout.
                read_timeout = 180 if candidate_size > 700 * 1024 else 120
                timeout = (20, read_timeout)  # connect timeout, read timeout
                print(f"⏱️  Таймаут установлен: connect=20s read={read_timeout}s")

                for parse_mode in parse_modes:
                    mode_label = "HTML" if parse_mode else "без parse_mode"
                    for attempt in range(1, 4):
                        data = {
                            "chat_id": self.channel_id,
                            "caption": caption,
                            "disable_notification": False,
                        }
                        if parse_mode:
                            data["parse_mode"] = parse_mode

                        try:
                            print(f"🚀 sendPhoto попытка {attempt}/3 ({mode_label})...")
                            start_time = time.time()
                            # Каждый retry открывает файл заново — это важно для multipart upload.
                            with open(candidate_path, "rb") as photo:
                                files = {"photo": photo}
                                response = requests.post(
                                    url,
                                    data=data,
                                    files=files,
                                    timeout=timeout,
                                    headers={"Connection": "close"},
                                )

                            elapsed = time.time() - start_time
                            print(f"📡 Ответ Telegram: {response.status_code} (за {elapsed:.1f} сек)")

                            if response.status_code == 200:
                                result = response.json()
                                if result.get("ok"):
                                    message_id = result["result"].get("message_id")
                                    print(f"✅ Фото с подписью отправлено, message_id: {message_id}")
                                    return message_id

                                error_desc = result.get("description", "Unknown error")
                                last_error = error_desc
                                print(f"❌ Ошибка Telegram API: {error_desc}")

                                # Retry-after для flood control.
                                retry_after = None
                                params = result.get("parameters") or {}
                                if isinstance(params, dict):
                                    retry_after = params.get("retry_after")
                                if retry_after:
                                    wait_s = min(max(int(retry_after), 1), 30)
                                    print(f"⏳ Telegram просит подождать {wait_s} сек...")
                                    time.sleep(wait_s)
                                    continue

                            else:
                                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                                print(f"❌ HTTP ошибка: {response.status_code}")

                        except requests.exceptions.Timeout as e:
                            last_error = f"Timeout: {e}"
                            print(f"⚠️ Таймаут при sendPhoto (попытка {attempt}/3): {e}")
                        except requests.exceptions.ConnectionError as e:
                            last_error = f"ConnectionError: {e}"
                            print(f"⚠️ Сетевая ошибка при sendPhoto (попытка {attempt}/3): {e}")
                        except Exception as e:
                            last_error = f"{type(e).__name__}: {e}"
                            print(f"⚠️ Ошибка sendPhoto (попытка {attempt}/3): {last_error}")

                        # Экспоненциальная пауза между попытками.
                        if attempt < 3:
                            wait_s = 2 ** attempt
                            print(f"🔄 Повтор через {wait_s} сек...")
                            time.sleep(wait_s)

            # Если sendPhoto не удалось, пробуем sendDocument (единым сообщением с подписью).
            smallest_candidate = min(
                upload_candidates,
                key=lambda path: os.path.getsize(path) if os.path.exists(path) else float("inf"),
            )
            print("🔄 sendPhoto не прошел, пробуем sendDocument fallback...")
            document_message_id = self._send_document_with_caption(smallest_candidate, caption)
            if document_message_id:
                return document_message_id

            print(f"❌ Не удалось отправить фото после всех попыток. Последняя ошибка: {last_error}")
            return None

        except Exception as e:
            print(f"❌ Ошибка отправки фото: {type(e).__name__}: {e}")
            return None
        finally:
            for temp_file in temp_files:
                self._safe_remove_file(temp_file)

    def _send_document_with_caption(self, file_path, caption):
        """Fallback: отправка файла как document с подписью."""
        try:
            if not file_path or not os.path.exists(file_path):
                return None

            url = f"{self.base_url}/sendDocument"
            data = {
                "chat_id": self.channel_id,
                "caption": caption[:1024],
                "parse_mode": "HTML",
                "disable_notification": False,
            }

            for attempt in range(1, 3):
                try:
                    print(f"📦 sendDocument попытка {attempt}/2...")
                    with open(file_path, "rb") as doc_file:
                        files = {"document": doc_file}
                        response = requests.post(
                            url,
                            data=data,
                            files=files,
                            timeout=(20, 120),
                            headers={"Connection": "close"},
                        )

                    if response.status_code != 200:
                        print(f"❌ sendDocument HTTP {response.status_code}")
                        if attempt < 2:
                            time.sleep(2 ** attempt)
                        continue

                    result = response.json()
                    if result.get("ok"):
                        message_id = result["result"].get("message_id")
                        print(f"✅ sendDocument успешно, message_id: {message_id}")
                        return message_id

                    print(f"❌ sendDocument API error: {result.get('description')}")
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                except Exception as e:
                    print(f"⚠️ sendDocument ошибка (попытка {attempt}/2): {e}")
                    if attempt < 2:
                        time.sleep(2 ** attempt)
            return None
        except Exception as e:
            print(f"❌ Ошибка sendDocument fallback: {e}")
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
                        base_name, _ = os.path.splitext(image_path)
                        compressed_path = f"{base_name}_compressed_{max_size_kb}kb_q{quality}.jpg"
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
            base_name, _ = os.path.splitext(image_path)
            compressed_path = f"{base_name}_compressed_{max_size_kb}kb.jpg"
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

    def _safe_remove_file(self, file_path):
        """Безопасно удаляет временный файл."""
        if not file_path:
            return
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
    
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

    def _split_long_text(self, text, max_chunk_len=3800):
        """Разбивает длинный текст на несколько сообщений."""
        source = (text or "").strip()
        if not source:
            return []

        chunks = []
        while source:
            if len(source) <= max_chunk_len:
                chunks.append(source)
                break

            window = source[:max_chunk_len]
            split_at = window.rfind("\n\n")
            if split_at < int(max_chunk_len * 0.55):
                split_at = window.rfind("\n")
            if split_at < int(max_chunk_len * 0.55):
                split_at = window.rfind(". ")
                if split_at > 0:
                    split_at += 1
            if split_at < int(max_chunk_len * 0.55):
                split_at = window.rfind(" ")
            if split_at < int(max_chunk_len * 0.55):
                split_at = max_chunk_len

            chunk = source[:split_at].strip()
            if not chunk:
                chunk = source[:max_chunk_len].strip()
                split_at = len(chunk)

            chunks.append(chunk)
            source = source[split_at:].strip()

        return chunks

    def _send_long_text(self, text, prefix=""):
        """Отправляет длинный текст в 1..N сообщений."""
        chunks = self._split_long_text(text, max_chunk_len=3800)
        if not chunks:
            return []

        sent_ids = []
        total = len(chunks)
        for idx, chunk in enumerate(chunks, start=1):
            if total == 1:
                payload = f"{prefix}{chunk}".strip()
            elif idx == 1 and prefix:
                payload = f"{prefix}{chunk}".strip()
            else:
                payload = f"📄 Продолжение ({idx}/{total}):\n\n{chunk}".strip()

            message_id = self._send_message_only(payload)
            if message_id:
                sent_ids.append(message_id)
            else:
                print(f"⚠️ Не удалось отправить часть {idx}/{total}")

        return sent_ids
    
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
                caption = format_article_for_telegram(article_text, max_length=980)
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
                    # Важный UX: единый пост (картинка + подпись), без отправки продолжений.
                    return message_id
                else:
                    print("⚠️  Не удалось отправить с изображением, пробую только текст...")
            
            # 3. Fallback: отправляем только текст
            print("📝 Отправка только текста...")
            message_id = self._send_message_only(format_article_for_telegram(article_text, max_length=3800))
            
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