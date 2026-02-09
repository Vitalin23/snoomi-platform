# ai/stablediffusion_artist.py
"""
Альтернатива Яндекс Арт - использует Stable Diffusion через бесплатные API
"""
import requests
import time
import os
from PIL import Image
import io

class StableDiffusionArtist:
    """Генерация изображений через Stable Diffusion API"""
    
    def __init__(self):
        self.api_url = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
        # Можно использовать бесплатный API ключ от Hugging Face
        self.api_key = os.getenv('HUGGINGFACE_TOKEN', '')
    
    def create_image_for_article(self, article_text, topic):
        """Создает иллюстрацию через Stable Diffusion"""
        
        print(f"🎨 Stable Diffusion: генерация для темы '{topic}'")
        
        # Создаем промпт
        prompt = self._create_prompt(topic)
        
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
                "Content-Type": "application/json"
            }
            
            payload = {
                "inputs": prompt,
                "parameters": {
                    "negative_prompt": "blurry, ugly, deformed, text, watermark",
                    "num_inference_steps": 30,
                    "guidance_scale": 7.5
                }
            }
            
            print(f"⏳ Отправка запроса в Stable Diffusion...")
            
            # Если нет API ключа, используем демо-режим
            if not self.api_key:
                print("⚠️  Нет API ключа, использую демо-режим")
                return self._create_demo_image(topic)
            
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=120)
            
            if response.status_code == 200:
                # Сохраняем изображение
                image = Image.open(io.BytesIO(response.content))
                filename = f"sd_{int(time.time())}.jpg"
                image.save(filename, "JPEG", quality=95)
                
                print(f"✅ Изображение создано: {filename}")
                return filename
                
            elif response.status_code == 503:
                print("⚠️  Модель загружается, попробуйте через минуту")
                return self._create_demo_image(topic)
            else:
                print(f"❌ Ошибка Stable Diffusion: {response.status_code}")
                print(f"Ответ: {response.text[:200]}")
                return self._create_demo_image(topic)
                
        except Exception as e:
            print(f"❌ Ошибка Stable Diffusion: {e}")
            return self._create_demo_image(topic)
    
    def _create_prompt(self, topic):
        """Создает промпт для Stable Diffusion"""
        
        # Упрощенный промпт на английском (лучше работает)
        prompt = f"""Professional photography of a modern bedroom with orthopedic mattress,
        high quality, photorealistic, natural lighting, cozy atmosphere,
        interior design, minimalist style, bedroom interior,
        related to topic: {topic[:50]}"""
        
        return prompt[:400]
    
    def _create_demo_image(self, topic):
        """Создает демо-изображение"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            import textwrap
            
            img = Image.new('RGB', (1024, 768), color=(60, 80, 120))
            draw = ImageDraw.Draw(img)
            
            try:
                font = ImageFont.truetype("arial.ttf", 36)
            except:
                font = ImageFont.load_default()
            
            # Текст
            draw.text((50, 50), "🎨 Stable Diffusion", font=font, fill=(255, 255, 255))
            draw.text((50, 100), f"Тема: {topic[:40]}", font=font, fill=(255, 255, 200))
            draw.text((50, 150), "Для реальной генерации нужен", font=font, fill=(200, 200, 255))
            draw.text((50, 200), "Hugging Face API токен", font=font, fill=(200, 200, 255))
            
            filename = f"sd_demo_{int(time.time())}.jpg"
            img.save(filename, quality=95)
            
            print(f"✅ Создано демо-изображение: {filename}")
            return filename
            
        except Exception as e:
            print(f"❌ Ошибка создания демо-изображения: {e}")
            return None

# Тест
if __name__ == "__main__":
    artist = StableDiffusionArtist()
    result = artist.create_image_for_article(
        "Статья о матрасах",
        "Ортопедические матрасы для здорового сна"
    )
    print(f"Результат: {result}")