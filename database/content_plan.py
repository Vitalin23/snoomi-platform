# database/content_plan.py
"""
Модуль для работы с контент-планом
Временная заглушка
"""

def get_todays_topic():
    """
    Получает тему на сегодня из базы данных
    Пока возвращает тестовые данные
    """
    import random
    from datetime import datetime
    
    test_topics = [
        {
            'topic': '🏆 Топ-5 ортопедических матрасов 2024',
            'keywords': ['рейтинг', 'топ', 'ортопедический', '2024', 'матрасы']
        },
        {
            'topic': '💤 Как матрас влияет на качество сна',
            'keywords': ['сон', 'качество', 'здоровье', 'влияние', 'отдых']
        },
        {
            'topic': '🌿 Эко-матрасы: натуральные материалы',
            'keywords': ['экология', 'натуральный', 'материалы', 'безопасность', 'эко']
        },
        {
            'topic': '⚡ Умные матрасы с технологиями',
            'keywords': ['умный', 'технологии', 'гаджеты', 'инновации', 'смарт']
        },
        {
            'topic': '👫 Матрасы для пар: решение разных предпочтений',
            'keywords': ['пара', 'семья', 'совместимость', 'компромисс', 'отношения']
        }
    ]
    
    # Выбираем тему на основе дня недели
    day_of_week = datetime.now().weekday()  # 0=понедельник
    topic_index = day_of_week % len(test_topics)
    
    topic_data = test_topics[topic_index]
    return topic_data['topic'], topic_data['keywords']

def create_monthly_plan():
    """Создает план на месяц (заглушка)"""
    print("📅 Создание плана публикаций...")
    print("⚠️  В режиме заглушки используется тестовый план")
    return True

if __name__ == "__main__":
    topic, keywords = get_todays_topic()
    print(f"📝 Тема на сегодня: {topic}")
    print(f"🔑 Ключевые слова: {keywords}")