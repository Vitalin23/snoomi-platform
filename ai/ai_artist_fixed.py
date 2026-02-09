# ai_artist_fixed.py
import requests
import time
import random
import os
from config import Config

class AIArtistFixed:
    def __init__(self):
        self.api_key = Config.YANDEX_ART_KEY
        self.folder_id = Config.YANDEX_FOLDER_ID
    
    def create_image_for_article(self, article_text, topic):
        """Создает иллюстрацию для статьи с ожиданием Яндекс Арт"""
        
        # Проверяем, что ключ не пустой и не дефолтный
        if not self.api_key or self.api_key == "ваш_ключ_яндекс_арт" or self.api_key.strip() == "":
            print("⚠️ Яндекс Арт не настроен. Создаю простую картинку.")
            return self._create_simple_image(topic)
        
        try:
            # Создаем КОРОТКИЙ промпт (менее 500 символов)
            prompt = self._create_short_prompt(topic, article_text)
            
            print(f"🎨 Яндекс Арт: промпт ({len(prompt)} символов): {prompt[:100]}...")
            
            if len(prompt) > 500:
                print("⚠️ Промпт слишком длинный, создаю простую картинку")
                return self._create_simple_image(topic)
            
            url = "https://llm.api.cloud.yandex.net/foundationModels/v1/imageGenerationAsync"
            
            headers = {
                "Authorization": f"Api-Key {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "modelUri": f"art://{self.folder_id}/yandex-art/latest",
                "generationOptions": {
                    "seed": random.randint(1, 1000000)
                },
                "messages": [
                    {
                        "weight": 1,
                        "text": prompt
                    }
                ]
            }
            
            print("⏳ Отправка запроса в Яндекс Арт...")
            response = requests.post(url, json=payload, headers=headers, timeout=60)
            
            if response.status_code == 200:
                operation_id = response.json().get('id')
                print(f"✅ Запрос принят, ID операции: {operation_id}")
                print("⏳ Генерация изображения... (может занять 1-2 минуты)")
                
                # Ждем завершения операции
                image_url = self._wait_for_operation_completion(operation_id)
                
                if image_url:
                    # Скачиваем и сохраняем изображение
                    image_path = self._download_image(image_url, topic)
                    if image_path:
                        print(f"✅ Изображение создано Яндекс Арт: {image_path}")
                        return image_path
                    else:
                        print("❌ Не удалось скачать изображение, создаю простую картинку")
                        return self._create_simple_image(topic)
                else:
                    print("❌ Яндекс Арт не вернул изображение, создаю простую картинку")
                    return self._create_simple_image(topic)
                    
            else:
                print(f"❌ Ошибка Яндекс Арт: {response.status_code}")
                print(f"Ответ: {response.text[:200]}")
                return self._create_simple_image(topic)
                
        except Exception as e:
            print(f"❌ Ошибка генерации Яндекс Арт: {e}")
            return self._create_simple_image(topic)
    
    def _wait_for_operation_completion(self, operation_id, max_wait_time=180):
        """
        Ожидает завершения асинхронной операции Яндекс Арт
        Возвращает URL изображения или None
        """
        url = f"https://llm.api.cloud.yandex.net/operations/{operation_id}"
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json"
        }
        
        start_time = time.time()
        check_interval = 5  # Проверяем каждые 5 секунд
        
        print(f"⏳ Ожидание завершения операции...")
        
        while time.time() - start_time < max_wait_time:
            try:
                response = requests.get(url, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    operation = response.json()
                    
                    # Проверяем статус операции
                    if operation.get('done', False):
                        # Операция завершена
                        if 'response' in operation:
                            images = operation['response'].get('images', [])
                            if images and len(images) > 0:
                                image_url = images[0].get('url')
                                if image_url:
                                    elapsed = int(time.time() - start_time)
                                    print(f"✅ Изображение сгенерировано за {elapsed} секунд")
                                    return image_url
                        
                        # Если изображения нет в ответе
                        error = operation.get('error', 'Неизвестная ошибка')
                        print(f"❌ Ошибка в операции: {error}")
                        return None
                    else:
                        # Операция еще выполняется
                        elapsed = int(time.time() - start_time)
                        print(f"⏳ Операция выполняется... ({elapsed} сек)")
                
                else:
                    print(f"⚠️ Ошибка проверки операции: {response.status_code}")
                
                # Ждем перед следующей проверкой
                time.sleep(check_interval)
                
            except Exception as e:
                print(f"⚠️ Ошибка при проверке операции: {e}")
                time.sleep(check_interval)
        
        print(f"❌ Превышено время ожидания ({max_wait_time} сек)")
        return None
    
    def _download_image(self, image_url, topic):
        """
        Скачивает изображение по URL и сохраняет в файл
        """
        try:
            print(f"📥 Скачивание изображения...")
            response = requests.get(image_url, timeout=60)
            
            if response.status_code == 200:
                # Создаем безопасное имя файла
                timestamp = int(time.time())
                safe_topic = "".join(c for c in topic[:30] if c.isalnum() or c in " _-").strip()
                if not safe_topic:
                    safe_topic = "image"
                
                filename = f"yandex_art_{safe_topic}_{timestamp}.jpg"
                
                # Сохраняем изображение
                with open(filename, 'wb') as f:
                    f.write(response.content)
                
                # Проверяем размер файла
                file_size = os.path.getsize(filename)
                if file_size > 1000:  # больше 1KB
                    print(f"✅ Изображение сохранено: {filename} ({file_size // 1024} KB)")
                    return filename
                else:
                    print(f"❌ Файл слишком маленький: {file_size} байт")
                    os.remove(filename)
                    return None
            else:
                print(f"❌ Ошибка скачивания: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Ошибка скачивания изображения: {e}")
            return None
    
    def _create_short_prompt(self, topic, article_text):
        """Создает короткий промпт (<500 символов) для матрасов и здорового сна"""
        
        # Определяем стиль изображения на основе темы
        style = self._determine_style(topic)
        
        # Определяем сцену на основе темы
        scene = self._determine_scene(topic)
        
        prompt = f"""Профессиональная фотография {scene}
Тема статьи: {topic[:50]}
Стиль: {style}
Основной объект: ортопедический матрас премиум-класса
Композиция: гармоничная, эстетичная, с акцентом на качество сна
Освещение: мягкий естественный свет из окна
Цветовая палитра: нейтральные тона, спокойные оттенки
Детали: высокое качество материалов, фактуры ткани, аккуратная постель
Настроение: умиротворение, комфорт, здоровый сон, релаксация
Технические параметры: фотореалистично, высокая детализация, профессиональный свет, глубина резкости"""
        
        # Обрезаем до 450 символов с запасом
        return prompt[:450]
    
    def _determine_style(self, topic):
        """Определяет стиль изображения на основе темы статьи"""
        topic_lower = topic.lower()
        
        if any(word in topic_lower for word in ['премиум', 'люкс', 'элит', 'дорог']):
            return "роскошный интерьер, дизайнерская спальня"
        elif any(word in topic_lower for word in ['здоров', 'ортопед', 'медиц', 'позвоноч']):
            return "клинически чистый, профессиональный, медицинский акцент"
        elif any(word in topic_lower for word in ['детск', 'ребен', 'подрост']):
            return "яркий, дружелюбный, игривый, безопасный"
        elif any(word in topic_lower for word in ['технолог', 'инновац', 'умны', 'смарт']):
            return "современный, технологичный, минимализм"
        elif any(word in topic_lower for word in ['экологич', 'натураль', 'природ', 'эко']):
            return "натуральные материалы, эко-стиль, органические текстуры"
        else:
            return "современная спальня, скандинавский минимализм, уют"
    
    def _determine_scene(self, topic):
        """Определяет сцену для изображения на основе темы"""
        topic_lower = topic.lower()
        
        if any(word in topic_lower for word in ['спальн', 'комнат', 'интерьер']):
            return "современной спальни с ортопедическим матрасом"
        elif any(word in topic_lower for word in ['магазин', 'салон', 'выставк', 'показ']):
            return "выставочного зала с матрасами в интерьере"
        elif any(word in topic_lower for word in ['производ', 'фабрик', 'сборк', 'изготовл']):
            return "производственного цеха с матрасами на конвейере"
        elif any(word in topic_lower for word in ['тест', 'обзор', 'сравнен', 'исследован']):
            return "студийной съемки матраса с акцентом на детали"
        elif any(word in topic_lower for word in ['распродаж', 'акци', 'скидк', 'предложен']):
            return "атмосферы уюта и комфорта с акционным матрасом"
        elif any(word in topic_lower for word in ['аллерг', 'гигиен', 'чистот']):
            return "чистой и гигиеничной спальной среды"
        else:
            return "современной спальни с ортопедическим матрасом"
    
    def _create_simple_image(self, topic):
        """Создает простую картинку если ИИ не доступен"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            import textwrap
            
            img = Image.new('RGB', (1200, 630), color=(40, 40, 80))
            draw = ImageDraw.Draw(img)
            
            try:
                font_large = ImageFont.truetype("arial.ttf", 48)
                font_small = ImageFont.truetype("arial.ttf", 24)
            except:
                font_large = ImageFont.load_default()
                font_small = ImageFont.load_default()
            
            # Добавляем тему
            wrapped_topic = textwrap.fill(topic, width=25)
            draw.text((100, 150), wrapped_topic, font=font_large, fill=(255, 255, 255))
            
            # Добавляем логотип
            draw.rectangle([100, 400, 250, 550], fill=(255, 255, 255), outline=(255, 255, 255))
            draw.text((120, 420), "SNOOMI", font=font_small, fill=(40, 40, 80))
            draw.text((110, 470), "Здоровый сон", font=font_small, fill=(40, 40, 80))
            
            filename = f"simple_{int(time.time())}.jpg"
            img.save(filename, quality=95)
            
            print(f"✅ Создана простая иллюстрация: {filename}")
            return filename
            
        except Exception as e:
            print(f"❌ Ошибка создания простой картинки: {e}")
            return None

# Тест
if __name__ == "__main__":
    print("🧪 Тест Яндекс Арт")
    print("=" * 50)
    
    artist = AIArtistFixed()
    
    # Проверяем настройки
    if not artist.api_key or artist.api_key == "ваш_ключ_яндекс_арт":
        print("❌ Яндекс Арт не настроен")
        print("Добавьте YANDEX_ART_KEY в .env файл")
    else:
        print("✅ Яндекс Арт настроен")
        
        # Тестовый промпт
        test_topic = "Ортопедический матрас для здорового сна"
        test_article = "Статья о важности ортопедических матрасов для качества сна."
        
        print(f"\nТестовая тема: {test_topic}")
        print("Запуск генерации изображения...")
        
        result = artist.create_image_for_article(test_article, test_topic)
        
        if result:
            print(f"\n🎉 Результат: {result}")
        else:
            print("\n❌ Генерация не удалась")