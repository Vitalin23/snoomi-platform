# ai/yandex_research_writer.py
import requests
import json
from config import Config

class YandexResearchWriter:
    """Объединенный класс: поиск в интернете + генерация статьи"""
    
    def __init__(self):
        self.api_key = Config.YANDEX_API_KEY
        self.folder_id = Config.YANDEX_FOLDER_ID
        
        # Проверяем наличие атрибута USE_SEARCH в конфиге
        if hasattr(Config, 'USE_SEARCH'):
            self.use_search = Config.USE_SEARCH
        else:
            self.use_search = True  # По умолчанию включен поиск
    
    def create_article_with_research(self, topic, keywords=None):
        """Ищет информацию и создает статью за один запрос"""
        
        print(f"🔍 YandexGPT: поиск и генерация по теме '{topic}'")
        
        # Подготавливаем промпт с инструкциями
        prompt = self._create_prompt(topic, keywords)
        
        # Настраиваем параметры с поиском или без
        completion_options = {
            "stream": False,
            "temperature": 0.7,
            "maxTokens": 4000  # Больше токенов для поиска + статья
        }
        
        if self.use_search:
            # Включаем поиск в интернете
            completion_options["useWebSearch"] = True
            completion_options["searchRegion"] = "ru"
            print("   📡 Используется поиск в интернете")
        
        try:
            headers = {
                "Authorization": f"Api-Key {self.api_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "modelUri": f"gpt://{self.folder_id}/yandexgpt",  # Основная модель с поиском
                "completionOptions": completion_options,
                "messages": [
                    {
                        "role": "system",
                        "text": """Ты профессиональный автор блога Snoomi о матрасах и здоровом сне. 
Ты ищешь актуальную информацию в интернете и пишешь экспертные статьи на основе найденных данных.
Твои статьи: информативные, полезные, с практическими советами."""
                    },
                    {
                        "role": "user",
                        "text": prompt
                    }
                ]
            }
            
            print("   ⏳ Отправка запроса к YandexGPT...")
            response = requests.post(
                "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
                headers=headers,
                json=data,
                timeout=120  # Больше времени для поиска
            )
            
            if response.status_code == 200:
                result = response.json()
                article = result['result']['alternatives'][0]['message']['text']
                
                # Извлекаем использованные источники (если есть)
                sources = self._extract_sources(result)
                if sources:
                    print(f"   📚 Использовано источников: {len(sources)}")
                
                print(f"   ✅ Статья создана: {len(article)} символов")
                return article
            else:
                print(f"❌ Ошибка YandexGPT: {response.status_code}")
                print(f"Ответ: {response.text[:200]}...")
                return self._create_fallback_article(topic)
                
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            import traceback
            traceback.print_exc()
            return self._create_fallback_article(topic)
    
    def _create_prompt(self, topic, keywords):
        """Создает УЛУЧШЕННЫЙ промпт для YandexGPT"""
        
        keywords_text = ""
        if keywords:
            keywords_text = f"Ключевые слова: {', '.join(keywords)}\n\n"
        
        prompt = f"""НАЙДИ АКТУАЛЬНУЮ ИНФОРМАЦИЮ И НАПИШИ ЖИВУЮ СТАТЬЮ ДЛЯ БЛОГА SNOOMI:

ТЕМА: {topic}

{keywords_text}
ТРЕБОВАНИЯ К СТАТЬЕ:
1. Язык: живой, разговорный, без бюрократизмов
2. Тон: дружеский, экспертный, но не заумный
3. Структура: без формальных заголовков "Введение", "Основная часть", "Заключение"
4. Длина: 1200-1800 символов (кратко, по делу)
5. НЕ используй HTML теги (<b>, </b>, и т.д.)
6. Используй обычные переносы строк

ФОРМАТ СТАТЬИ:
🎯 Начни с цепляющего заголовка с эмодзи
✨ Сразу переходи к сути - почему тема важна для читателя
🔍 Дай 3-4 ключевых совета/факта (каждый с эмодзи)
💡 Добавь практические рекомендации "как сделать"
🎁 Закончи кратким выводом и вопросом к читателям
🏷️ Хештеги: #матрасы #здоровыйсон #snoomi

ЧЕГО ИЗБЕГАТЬ:
- "В данной статье мы рассмотрим"
- "Основная часть", "Заключение"
- Воды и общих фраз
- Слишком технических терминов
- Длинных сложных предложений

СТИЛЬ:
- Пиши так, как будто общаешься с другом
- Используй короткие абзацы (2-3 предложения)
- Добавляй эмодзи для наглядности
- Делай акцент на практической пользе

ИЩИ в интернете:
- Конкретные цифры и исследования (если есть)
- Реальные отзывы и опыт людей
- Актуальные тренды 2025-2026 года
- Практические лайфхаки"""
        
        return prompt
    
    def _extract_sources(self, api_response):
        """Извлекает источники из ответа API"""
        try:
            # В некоторых версиях API источники могут быть в метаданных
            if 'result' in api_response and 'usage' in api_response['result']:
                usage = api_response['result']['usage']
                if 'searchQueries' in usage:
                    return usage['searchQueries']
        except:
            pass
        return []
    
    def _create_fallback_article(self, topic):
        """Статья-заглушка при ошибке"""
        return f"""🏆 {topic}

Качественный сон — основа здоровья и продуктивности. Правильный выбор матраса играет ключевую роль в качестве отдыха.

В современном мире существует множество вариантов матрасов: от классических пружинных до инновационных материалов с памятью формы.

💡 Советы по выбору:
1. Определите нужную жесткость
2. Учитывайте вес и рост
3. Обратите внимание на материалы
4. Проверьте гарантию

Инвестируйте в качественный сон — это инвестиция в ваше здоровье!

#матрасы #здоровыйсон #snoomi"""

# Быстрый тест
if __name__ == "__main__":
    # Тест импорта конфига
    try:
        from config import Config
        print("✅ Конфигурация загружена")
        
        if Config.YANDEX_API_KEY and Config.YANDEX_FOLDER_ID:
            writer = YandexResearchWriter()
            
            print("="*60)
            print("🧪 ТЕСТ YANDEX GPT С ПОИСКОМ")
            print("="*60)
            
            article = writer.create_article_with_research(
                "Новинки ортопедических матрасов 2024 года",
                ["ортопедический", "матрас", "новинки", "2024"]
            )
            
            print("\n📄 РЕЗУЛЬТАТ:")
            print("="*60)
            print(article[:500] + "..." if len(article) > 500 else article)
            print("="*60)
        else:
            print("❌ Yandex API ключи не настроены")
            
    except ImportError as e:
        print(f"❌ Не удалось импортировать конфиг: {e}")
    except Exception as e:
        print(f"❌ Ошибка теста: {e}")
        import traceback
        traceback.print_exc()