# database.py - ОБНОВЛЕННАЯ ВЕРСИЯ
import sqlite3
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_name="snoomi_bot.db"):
        """Инициализация базы данных"""
        self.db_name = db_name
        self.conn = sqlite3.connect(db_name)
        self.create_tables()
        logger.info(f"✅ База данных '{db_name}' подключена")
    
    def create_tables(self):
        """Создает все необходимые таблицы"""
        cursor = self.conn.cursor()
        
        # Таблица пользователей бота
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_activity TIMESTAMP,
            conversations_started INTEGER DEFAULT 0,
            conversations_completed INTEGER DEFAULT 0
        )
        ''')
        
        # Таблица администраторов
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            username TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Таблица публикаций
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS publications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT,  -- 'vk', 'telegram', 'both'
            post_id TEXT,
            topic TEXT,
            content TEXT,
            image_path TEXT,
            published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            success BOOLEAN,
            error_message TEXT
        )
        ''')
        
        # Таблица ошибок
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT,
            error_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Таблица тем контента
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS content_themes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL,
            theme TEXT NOT NULL,
            keywords TEXT,  -- JSON массив ключевых слов
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Таблица постов новостей (из старой версии)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS news_posts (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            scheduled_time TIMESTAMP,
            published BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        self.conn.commit()
        logger.info("✅ Таблицы созданы")
    
    # ===================== МЕТОДЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====================
    
    def add_bot_user(self, user_id, username=None, first_name=None, last_name=None):
        """Добавляет или обновляет пользователя бота"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
            INSERT OR REPLACE INTO bot_users 
            (user_id, username, first_name, last_name, last_activity, conversations_started)
            VALUES (?, ?, ?, ?, ?, COALESCE(
                (SELECT conversations_started FROM bot_users WHERE user_id = ?), 
                0
            ) + 1)
            ''', (user_id, username, first_name, last_name, datetime.now(), user_id))
            
            self.conn.commit()
            logger.info(f"✅ Пользователь добавлен/обновлен: {user_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка добавления пользователя: {e}")
            return False
    
    def increment_completed_conversations(self, user_id):
        """Увеличивает счетчик завершенных диалогов"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
            UPDATE bot_users 
            SET conversations_completed = conversations_completed + 1,
                last_activity = ?
            WHERE user_id = ?
            ''', (datetime.now(), user_id))
            
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"❌ Ошибка обновления статистики: {e}")
            return False
    
    def get_user_stats(self, user_id):
        """Получает статистику пользователя"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT conversations_started, conversations_completed, last_activity
        FROM bot_users WHERE user_id = ?
        ''', (user_id,))
        
        return cursor.fetchone()
    
    def count_bot_users(self):
        """Считает количество пользователей бота"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM bot_users')
        return cursor.fetchone()[0]
    
    def get_recent_users(self, limit=10):
        """Получает последних пользователей"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT user_id, username, first_name, last_activity
        FROM bot_users 
        ORDER BY last_activity DESC 
        LIMIT ?
        ''', (limit,))
        
        return cursor.fetchall()
    
    # ===================== МЕТОДЫ ДЛЯ ПУБЛИКАЦИЙ =====================
    
    def add_publication(self, platform, post_id, topic, content, image_path=None, success=True, error_message=None):
        """Добавляет запись о публикации"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
            INSERT INTO publications 
            (platform, post_id, topic, content, image_path, success, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (platform, post_id, topic, content[:1000], image_path, success, error_message))
            
            self.conn.commit()
            logger.info(f"✅ Публикация добавлена: {platform} - {topic}")
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"❌ Ошибка добавления публикации: {e}")
            return None
    
    def get_recent_publications(self, limit=10):
        """Получает последние публикации"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT platform, topic, published_at, success, error_message
        FROM publications 
        ORDER BY published_at DESC 
        LIMIT ?
        ''', (limit,))
        
        return cursor.fetchall()
    
    def count_publications_today(self):
        """Считает публикации за сегодня"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT COUNT(*) FROM publications 
        WHERE DATE(published_at) = DATE('now')
        ''')
        
        return cursor.fetchone()[0]
    
    def get_publication_stats(self, days=7):
        """Получает статистику публикаций за период"""
        cursor = self.conn.cursor()
        
        cursor.execute('''
        SELECT 
            DATE(published_at) as date,
            COUNT(*) as total,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed
        FROM publications 
        WHERE published_at >= datetime('now', ?)
        GROUP BY DATE(published_at)
        ORDER BY date DESC
        ''', (f'-{days} days',))
        
        return cursor.fetchall()
    
    # ===================== МЕТОДЫ ДЛЯ ОШИБОК =====================
    
    def log_error(self, module, error_text):
        """Записывает ошибку в лог"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
            INSERT INTO errors (module, error_text)
            VALUES (?, ?)
            ''', (module, str(error_text)[:500]))
            
            self.conn.commit()
            logger.warning(f"⚠️ Ошибка записана в лог: {module}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка записи ошибки: {e}")
            return False
    
    def get_recent_errors(self, limit=10):
        """Получает последние ошибки"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT module, error_text, created_at
        FROM errors 
        ORDER BY created_at DESC 
        LIMIT ?
        ''', (limit,))
        
        return cursor.fetchall()
    
    def count_errors_today(self):
        """Считает ошибки за сегодня"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT COUNT(*) FROM errors 
        WHERE DATE(created_at) = DATE('now')
        ''')
        
        return cursor.fetchone()[0]
    
    # ===================== МЕТОДЫ ДЛЯ ТЕМ КОНТЕНТА =====================
    
    def add_theme(self, date, theme, keywords=None, status='pending'):
        """Добавляет тему контента"""
        try:
            keywords_json = json.dumps(keywords) if keywords else None
            
            cursor = self.conn.cursor()
            cursor.execute('''
            INSERT INTO content_themes (date, theme, keywords, status)
            VALUES (?, ?, ?, ?)
            ''', (date, theme, keywords_json, status))
            
            self.conn.commit()
            logger.info(f"✅ Тема добавлена: {date} - {theme}")
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"❌ Ошибка добавления темы: {e}")
            return None
    
    def get_todays_theme(self):
        """Получает тему на сегодня"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT id, date, theme, keywords, status
        FROM content_themes 
        WHERE date = date('now') AND status != 'published'
        ORDER BY date LIMIT 1
        ''')
        
        row = cursor.fetchone()
        if row:
            id, date, theme, keywords_json, status = row
            keywords = json.loads(keywords_json) if keywords_json else []
            return {
                'id': id,
                'date': date,
                'theme': theme,
                'keywords': keywords,
                'status': status
            }
        return None
    
    def update_theme_status(self, theme_id, status):
        """Обновляет статус темы"""
        cursor = self.conn.cursor()
        cursor.execute('''
        UPDATE content_themes SET status = ? WHERE id = ?
        ''', (status, theme_id))
        self.conn.commit()
        
        return cursor.rowcount > 0
    
    # ===================== УТИЛИТЫ =====================
    
    def get_database_stats(self):
        """Получает общую статистику базы данных"""
        cursor = self.conn.cursor()
        
        stats = {}
        
        # Пользователи
        cursor.execute('SELECT COUNT(*) FROM bot_users')
        stats['users_total'] = cursor.fetchone()[0]
        
        cursor.execute('''
        SELECT COUNT(*) FROM bot_users 
        WHERE DATE(last_activity) = DATE('now')
        ''')
        stats['users_active_today'] = cursor.fetchone()[0]
        
        # Публикации
        cursor.execute('SELECT COUNT(*) FROM publications')
        stats['publications_total'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM publications WHERE success = 1')
        stats['publications_successful'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM publications WHERE success = 0')
        stats['publications_failed'] = cursor.fetchone()[0]
        
        # Ошибки
        cursor.execute('SELECT COUNT(*) FROM errors')
        stats['errors_total'] = cursor.fetchone()[0]
        
        # Темы
        cursor.execute('SELECT COUNT(*) FROM content_themes')
        stats['themes_total'] = cursor.fetchone()[0]
        
        return stats
    
    def close(self):
        """Закрывает соединение с БД"""
        self.conn.close()
        logger.info("✅ Соединение с БД закрыто")

# Создаем глобальный экземпляр БД
db = Database()

# Тест
if __name__ == "__main__":
    print("🧪 Тест базы данных")
    print("=" * 50)
    
    # Инициализация
    db = Database("test.db")
    
    # Тестовые данные
    print("1. Добавляем тестового пользователя...")
    db.add_bot_user(123456, "test_user", "Test", "User")
    
    print("2. Добавляем тестовую публикацию...")
    db.add_publication("vk", "post_123", "Тестовая тема", "Тестовый контент", success=True)
    
    print("3. Записываем тестовую ошибку...")
    db.log_error("test_module", "Тестовая ошибка")
    
    print("4. Добавляем тестовую тему...")
    db.add_theme("2024-01-01", "Тестовая тема", ["тест", "ключевое слово"])
    
    print("5. Получаем статистику...")
    stats = db.get_database_stats()
    
    print("\n📊 Статистика базы данных:")
    print(f"👥 Пользователей: {stats['users_total']}")
    print(f"📝 Публикаций: {stats['publications_total']}")
    print(f"✅ Успешных: {stats['publications_successful']}")
    print(f"❌ Неудачных: {stats['publications_failed']}")
    print(f"⚠️ Ошибок: {stats['errors_total']}")
    print(f"📋 Тем: {stats['themes_total']}")
    
    print("\n✅ Тест базы данных пройден!")
    print("=" * 50)