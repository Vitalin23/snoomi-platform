# ai/yandex_art_final.py
"""
ФИНАЛЬНАЯ РАБОЧАЯ ВЕРСИЯ Яндекс Арт
Простая и надежная реализация через прямое API
"""
import os
import sys
import time
import re
import hashlib
import requests
import json
import base64
from typing import Optional, Dict, Any, List
from datetime import datetime

# Добавляем родительскую директорию в путь для импорта config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PIL import Image, ImageDraw, ImageFont
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

class YandexArtGenerator:
    """Генератор изображений через Яндекс ART API"""
    
    def __init__(self, api_key: Optional[str] = None, folder_id: Optional[str] = None):
        """
        Инициализация генератора
        
        Args:
            api_key: API ключ Яндекс Cloud
            folder_id: Folder ID из Яндекс Cloud
        """
        # Получаем ключи из параметров или config
        if api_key and folder_id:
            self.api_key = api_key
            self.folder_id = folder_id
        else:
            try:
                from config import Config
                self.api_key = Config.YANDEX_API_KEY or Config.YANDEX_ART_KEY
                self.folder_id = Config.YANDEX_FOLDER_ID
            except ImportError:
                raise ValueError("Не удалось загрузить конфигурацию. Проверьте файл .env")
        
        if not self.api_key or not self.folder_id:
            raise ValueError("Не настроены YANDEX_API_KEY или YANDEX_FOLDER_ID")
        
        # URL для API
        self.api_url = "https://llm.api.cloud.yandex.net/foundationModels/v1/imageGenerationAsync"
    
    def generate_image(self, prompt: str, topic: str = "изображение") -> Optional[str]:
        """
        Генерирует изображение по промпту
        
        Args:
            prompt: Текст промпта для генерации
            topic: Тема для имени файла
            
        Returns:
            Путь к созданному файлу изображения или None
        """
        print(f"🎨 Генерация изображения: {topic[:50]}...")
        
        try:
            # 1. Создаем операцию генерации
            operation_id = self._create_generation_operation(prompt, topic_seed_hint=topic)
            if not operation_id:
                return None
            
            # 2. Ждем завершения операции
            operation_result = self._wait_for_operation(operation_id)
            if not operation_result:
                return None
            
            # 3. Извлекаем и сохраняем изображение
            image_path = self._extract_and_save_image(operation_result, topic)
            
            if image_path:
                print(f"✅ Изображение создано: {image_path}")
                return image_path
            else:
                print("❌ Не удалось сохранить изображение")
                return None
                
        except Exception as e:
            print(f"❌ Ошибка генерации: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def create_image_for_article(self, article_text: str, topic: str) -> Optional[str]:
        """
        Создает иллюстрацию для статьи
        
        Args:
            article_text: Текст статьи (используется как дополнительный контекст)
            topic: Тема статьи для промпта
            
        Returns:
            Путь к созданному файлу изображения
        """
        article_hint = self._extract_article_visual_hint(article_text)
        prompt_topic = topic
        if article_hint:
            prompt_topic = f"{topic}. Контекст статьи: {article_hint}"

        # Создаем оптимизированный и более вариативный промпт на основе темы
        prompt = self._create_article_prompt(prompt_topic)
        
        # Генерируем изображение
        return self.generate_image(prompt, topic)

    def _pick_variant(self, topic: str, salt: str, options: List[str]) -> str:
        if not options:
            return ""
        digest = hashlib.sha256(f"{topic}|{salt}".encode("utf-8")).hexdigest()
        idx = int(digest[:8], 16) % len(options)
        return options[idx]

    def _extract_topic_keywords(self, text_value: str, limit: int = 6) -> List[str]:
        words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", str(text_value or "").lower(), flags=re.UNICODE)
        stop_words = {
            "как", "что", "для", "при", "это", "или", "the", "and", "with", "post",
            "telegram", "vk", "контекст", "статьи", "тема", "короткий", "чек", "лист",
        }
        unique: List[str] = []
        seen = set()
        for word in words:
            if len(word) < 4 or word in stop_words:
                continue
            if word in seen:
                continue
            seen.add(word)
            unique.append(word)
            if len(unique) >= limit:
                break
        return unique

    def _extract_article_visual_hint(self, article_text: str, max_words: int = 24) -> str:
        words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", str(article_text or ""), flags=re.UNICODE)
        if not words:
            return ""
        return " ".join(words[:max_words])
    
    def _create_generation_operation(self, prompt: str, topic_seed_hint: str = "") -> Optional[str]:
        """Создает операцию генерации изображения"""
        try:
            headers = {
                "Authorization": f"Api-Key {self.api_key}",
                "Content-Type": "application/json"
            }
            seed_material = f"{topic_seed_hint}|{prompt[:200]}|{time.time_ns()}"
            seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:12], 16) % 2147483647
            if seed <= 0:
                seed = int(time.time()) % 1000000 or 1
            
            payload = {
                "modelUri": f"art://{self.folder_id}/yandex-art/latest",
                "generationOptions": {
                    "seed": seed
                },
                "messages": [
                    {
                        "weight": 1,
                        "text": prompt
                    }
                ]
            }
            
            print("📤 Отправка запроса на генерацию...")
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                operation_id = result.get('id')
                
                if operation_id:
                    print(f"✅ Запрос принят, ID операции: {operation_id}")
                    return operation_id
                else:
                    print(f"❌ Нет ID операции в ответе")
            else:
                print(f"❌ Ошибка API: {response.status_code}")
                print(f"Ответ: {response.text[:200]}")
                
        except Exception as e:
            print(f"❌ Ошибка при создании операции: {e}")
        
        return None
    
    def _wait_for_operation(self, operation_id: str) -> Optional[Dict]:
        """Ожидает завершения операции"""
        try:
            operation_url = f"https://llm.api.cloud.yandex.net/operations/{operation_id}"
            headers = {
                "Authorization": f"Api-Key {self.api_key}",
                "Content-Type": "application/json"
            }
            
            max_wait_time = 300  # 5 минут
            check_interval = 3   # Проверять каждые 3 секунды
            start_time = time.time()
            
            print(f"⏳ Ожидание завершения операции...")
            
            while time.time() - start_time < max_wait_time:
                try:
                    response = requests.get(operation_url, headers=headers, timeout=30)
                    
                    if response.status_code == 200:
                        operation = response.json()
                        
                        if operation.get('done', False):
                            print("✅ Операция завершена")
                            
                            # Проверяем ошибки
                            if 'error' in operation:
                                error_msg = operation['error']
                                print(f"❌ Ошибка в операции: {error_msg}")
                                return None
                            
                            return operation
                        else:
                            # Показываем прогресс
                            elapsed = int(time.time() - start_time)
                            if elapsed % 15 == 0:  # Каждые 15 секунд
                                print(f"   Ожидание... ({elapsed} сек)")
                    
                    time.sleep(check_interval)
                    
                except Exception as check_error:
                    # Игнорируем ошибки проверки, продолжаем ожидание
                    time.sleep(check_interval)
            
            print(f"❌ Превышено время ожидания ({max_wait_time} сек)")
            return None
            
        except Exception as e:
            print(f"❌ Ошибка ожидания операции: {e}")
            return None
    
    def _extract_and_save_image(self, operation: Dict, topic: str) -> Optional[str]:
        """Извлекает и сохраняет изображение из операции"""
        try:
            # Ищем изображение в response.image (base64)
            if 'response' in operation:
                response_data = operation['response']
                
                if 'image' in response_data:
                    image_base64 = response_data['image']
                    
                    if isinstance(image_base64, str) and len(image_base64) > 1000:
                        print(f"✅ Найден base64 изображение")
                        
                        # Декодируем base64
                        try:
                            image_bytes = base64.b64decode(image_base64)
                            
                            # Сохраняем в файл
                            return self._save_image_file(image_bytes, topic)
                            
                        except Exception as decode_error:
                            print(f"❌ Ошибка декодирования base64: {decode_error}")
            
            print("❌ Не найден base64 изображение в операции")
            return None
            
        except Exception as e:
            print(f"❌ Ошибка извлечения изображения: {e}")
            return None
    
    def _save_image_file(self, image_bytes: bytes, topic: str) -> Optional[str]:
        """Сохраняет изображение в файл"""
        try:
            # Создаем безопасное имя файла
            timestamp = int(time.time())
            safe_topic = "".join(c for c in topic[:30] if c.isalnum() or c in " _-").strip()
            if not safe_topic:
                safe_topic = "image"
            
            # Определяем формат изображения
            if image_bytes.startswith(b'\xff\xd8'):
                ext = ".jpg"
            elif image_bytes.startswith(b'\x89PNG'):
                ext = ".png"
            elif image_bytes.startswith(b'GIF'):
                ext = ".gif"
            else:
                ext = ".jpg"  # По умолчанию
            
            filename = f"yandex_art_{safe_topic}_{timestamp}{ext}"
            
            # Сохраняем файл
            with open(filename, 'wb') as f:
                f.write(image_bytes)
            
            # Проверяем размер
            file_size = os.path.getsize(filename)
            if file_size > 1000:
                print(f"📁 Файл сохранен: {filename} ({file_size // 1024} KB)")
                return filename
            else:
                print(f"❌ Файл слишком маленький: {file_size} байт")
                os.remove(filename)
                return None
                
        except Exception as e:
            print(f"❌ Ошибка сохранения файла: {e}")
            return None
    
    def _create_article_prompt(self, topic: str) -> str:
        """Создает вариативный промпт под тему статьи (меньше однотипных кадров)."""
        topic_lower = str(topic or "").lower()
        keywords = self._extract_topic_keywords(topic, limit=6)

        style_candidates = [
            "скандинавский минимализм, чистые линии, уют",
            "современный теплый интерьер, натуральные материалы",
            "премиальная спальня, тактильные фактуры, мягкий свет",
            "нейтральный экспертный интерьер, спокойная палитра",
            "lifestyle-сцена домашнего уюта, реалистично",
        ]
        if any(word in topic_lower for word in ["премиум", "люкс", "элит", "дорог"]):
            style_candidates = [
                "премиальный интерьер, дизайнерская мебель, фотореализм",
                "роскошная современная спальня, дорогие фактуры, мягкий контраст",
            ]
        elif any(word in topic_lower for word in ["эко", "натураль", "природ", "органич"]):
            style_candidates = [
                "эко-интерьер, дерево и лен, спокойные природные оттенки",
                "натуральные материалы, светлая спальня, экологичный стиль",
            ]
        elif any(word in topic_lower for word in ["ортопед", "здоров", "медиц", "боль в спине"]):
            style_candidates = [
                "практичный экспертный интерьер, чистая композиция, акцент на поддержку спины",
                "клинически аккуратный интерьер спальни, но уютный и домашний",
            ]
        elif any(word in topic_lower for word in ["vk пост", "vk"]):
            style_candidates.append("вовлекающий lifestyle-кадр для ленты соцсети")
        elif any(word in topic_lower for word in ["telegram пост", "telegram"]):
            style_candidates.append("минималистичный кадр для Telegram, один главный акцент")

        angle_options = [
            "ракурс 3/4, уровень глаз",
            "ракурс с легкой верхней точки, фокус на матрасе",
            "низкий ракурс, акцент на фактуре поверхности",
            "боковой ракурс, глубина помещения",
        ]
        composition_options = [
            "один главный объект в кадре, чистый передний план",
            "асимметричная композиция с пространством для взгляда",
            "сбалансированная композиция с естественной перспективой",
            "композиция с акцентом на текстуру ткани и формы",
        ]
        lighting_options = [
            "мягкий утренний свет из окна",
            "дневной рассеянный свет без резких теней",
            "теплый вечерний свет, спокойная атмосфера",
            "естественный нейтральный свет, чистая цветопередача",
        ]
        color_options = [
            "молочные, песочные и древесные тона",
            "нейтральная палитра с мягкими акцентами",
            "теплые натуральные оттенки без кислотных цветов",
            "сдержанные современные цвета, спокойный контраст",
        ]

        style = self._pick_variant(topic, "style", style_candidates)
        camera_angle = self._pick_variant(topic, "angle", angle_options)
        composition = self._pick_variant(topic, "composition", composition_options)
        lighting = self._pick_variant(topic, "lighting", lighting_options)
        palette = self._pick_variant(topic, "palette", color_options)

        subject_focus = "матрас и спальная зона"
        if any(word in topic_lower for word in ["детск", "ребен", "подрост"]):
            subject_focus = "детская спальня с безопасным и удобным матрасом"
        elif any(word in topic_lower for word in ["ортопед", "спин", "поясниц"]):
            subject_focus = "ортопедический матрас и визуальный акцент на поддержке позвоночника"
        elif any(word in topic_lower for word in ["интерьер", "спальн", "дизайн"]):
            subject_focus = "гармоничный интерьер спальни с выразительным матрасом в центре"

        keywords_line = f"Ключевые образы: {', '.join(keywords)}." if keywords else ""
        prompt = (
            "Фотореалистичная интерьерная фотография для поста в соцсети.\n"
            f"Тема: {topic}.\n"
            f"Сюжет: {subject_focus}.\n"
            f"Стиль: {style}.\n"
            f"Камера: {camera_angle}.\n"
            f"Композиция: {composition}.\n"
            f"Свет: {lighting}.\n"
            f"Палитра: {palette}.\n"
            f"{keywords_line}\n"
            "Качество: высокая детализация, натуральные текстуры, реалистичная оптика.\n"
            "Ограничения: без текста, логотипов, водяных знаков, коллажей и лишних декоративных элементов."
        ).strip()

        return prompt[:900]

# Функция для обратной совместимости
class YandexArtFinal(YandexArtGenerator):
    """Алиас для обратной совместимости со старым кодом"""
    pass

def create_simple_image(topic: str) -> Optional[str]:
    """Создает простую картинку если ИИ не доступен"""
    if not PILLOW_AVAILABLE:
        print("❌ Pillow не установлен")
        return None
        
    try:
        img = Image.new('RGB', (800, 450), color=(60, 80, 140))
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except:
            font = ImageFont.load_default()
        
        draw.text((50, 50), "🎨 Иллюстрация", font=font, fill=(255, 255, 255))
        draw.text((50, 120), topic[:40], font=font, fill=(255, 255, 200))
        draw.text((50, 180), "Snoomi - здоровый сон", font=font, fill=(200, 200, 255))
        
        filename = f"simple_{int(time.time())}.jpg"
        img.save(filename, quality=90)
        
        print(f"✅ Создана простая иллюстрация: {filename}")
        return filename
        
    except Exception as e:
        print(f"❌ Ошибка создания простой картинки: {e}")
        return None

# Быстрая проверка работы
if __name__ == "__main__":
    print("🔍 Проверка работы Яндекс Арт...")
    
    try:
        generator = YandexArtGenerator()
        print("✅ Генератор инициализирован")
        
        # Тестовый промпт
        test_result = generator.generate_image(
            "спальня с матрасом, фотореалистично",
            "тестовая генерация"
        )
        
        if test_result:
            print(f"\n🎉 Яндекс Арт работает! Файл: {test_result}")
        else:
            print("\n❌ Яндекс Арт не сработал")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")