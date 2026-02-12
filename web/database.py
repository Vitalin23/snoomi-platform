"""
Модуль управления базой данных для Snoomi Platform
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path

class DatabaseManager:
    """Менеджер базы данных SQLite"""
    
    def __init__(self, db_path='web/database.db'):
        self.db_path = Path(db_path)
        self.connection = None
        self.cursor = None
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных и создание таблиц"""
        self.connect()
        
        # Создание таблиц
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                platform TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                access_token TEXT,
                category TEXT DEFAULT 'general',
                is_active BOOLEAN DEFAULT 1,
                settings TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                text TEXT NOT NULL,
                image_path TEXT,
                channel_id INTEGER,
                topic TEXT,
                status TEXT DEFAULT 'draft',
                scheduled_time TIMESTAMP,
                published_time TIMESTAMP,
                platform TEXT,
                engagement INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES channels (id)
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id INTEGER,
                channel_id INTEGER NOT NULL,
                scheduled_time TIMESTAMP NOT NULL,
                published_time TIMESTAMP,
                task_id TEXT,
                status TEXT DEFAULT 'scheduled',
                error_message TEXT,
                platform_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (content_id) REFERENCES content (id),
                FOREIGN KEY (channel_id) REFERENCES channels (id)
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                date DATE NOT NULL,
                views INTEGER DEFAULT 0,
                likes INTEGER DEFAULT 0,
                shares INTEGER DEFAULT 0,
                comments INTEGER DEFAULT 0,
                reach INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES channels (id)
            )
        ''')
        
        # Индексы для ускорения запросов
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_content_status ON content(status)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_content_channel ON content(channel_id)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_scheduled_status ON scheduled_posts(status)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_scheduled_time ON scheduled_posts(scheduled_time)')
        
        self.connection.commit()
        
        # Добавление тестовых данных если база пустая
        self.add_sample_data()
    
    def connect(self):
        """Подключение к базе данных"""
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.cursor = self.connection.cursor()
    
    def close(self):
        """Закрытие соединения с базой данных"""
        if self.connection:
            self.connection.close()
    
    def add_sample_data(self):
        """Добавление тестовых данных"""
        # Проверяем, есть ли уже каналы
        self.cursor.execute("SELECT COUNT(*) as count FROM channels")
        count = self.cursor.fetchone()['count']
        
        if count == 0:
            # Добавляем тестовые каналы
            test_channels = [
                ('Матрасы и здоровый сон', 'Канал о выборе матрасов', 'vk', 'club123456', None, 'матрасы'),
                ('Интерьер и уют', 'Идеи для дома', 'telegram', '@interior_channel', None, 'интерьер'),
                ('Здоровый образ жизни', 'Советы для здоровья', 'vk', 'club789012', None, 'здоровье')
            ]
            
            for channel in test_channels:
                self.cursor.execute('''
                    INSERT INTO channels (name, description, platform, channel_id, category)
                    VALUES (?, ?, ?, ?, ?)
                ''', channel)
            
            # Добавляем тестовый контент
            test_content = [
                ('Как выбрать ортопедический матрас', 
                 'Полное руководство по выбору ортопедического матраса...', 
                 1, 'ортопедические матрасы', 'draft'),
                ('10 идей для уютной спальни',
                 'Создайте идеальную атмосферу для отдыха...',
                 2, 'интерьер спальни', 'published'),
                ('Важность здорового сна',
                 'Как сон влияет на продуктивность и здоровье...',
                 3, 'здоровый сон', 'scheduled')
            ]
            
            for content in test_content:
                self.cursor.execute('''
                    INSERT INTO content (title, text, channel_id, topic, status)
                    VALUES (?, ?, ?, ?, ?)
                ''', content)
            
            self.connection.commit()
            print("✅ Добавлены тестовые данные")
    
    def get_channels(self, active_only=True):
        """Получение списка каналов"""
        if active_only:
            self.cursor.execute("SELECT * FROM channels WHERE is_active = 1 ORDER BY name")
        else:
            self.cursor.execute("SELECT * FROM channels ORDER BY name")
        return [dict(row) for row in self.cursor.fetchall()]
    
    def add_channel(self, name, platform, channel_id, category='general', **kwargs):
        """Добавление нового канала"""
        self.cursor.execute('''
            INSERT INTO channels (name, platform, channel_id, category, 
                                 description, access_token, settings)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (name, platform, channel_id, category, 
              kwargs.get('description'), kwargs.get('access_token'),
              json.dumps(kwargs.get('settings', {}))))
        self.connection.commit()
        return self.cursor.lastrowid
    
    def get_content(self, filters=None):
        """Получение контента с фильтрами"""
        query = "SELECT c.*, ch.name as channel_name FROM content c LEFT JOIN channels ch ON c.channel_id = ch.id WHERE 1=1"
        params = []
        
        if filters:
            if filters.get('status'):
                query += " AND c.status = ?"
                params.append(filters['status'])
            if filters.get('channel_id'):
                query += " AND c.channel_id = ?"
                params.append(filters['channel_id'])
            if filters.get('search'):
                query += " AND (c.title LIKE ? OR c.text LIKE ? OR c.topic LIKE ?)"
                search_term = f"%{filters['search']}%"
                params.extend([search_term, search_term, search_term])
        
        query += " ORDER BY c.created_at DESC"
        
        if filters and filters.get('limit'):
            query += " LIMIT ?"
            params.append(filters['limit'])
        
        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]
    
    def add_content(self, text, channel_id=None, **kwargs):
        """Добавление нового контента"""
        self.cursor.execute('''
            INSERT INTO content (text, channel_id, title, topic, status, 
                                image_path, scheduled_time, platform)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (text, channel_id, 
              kwargs.get('title'), kwargs.get('topic'), 
              kwargs.get('status', 'draft'), kwargs.get('image_path'),
              kwargs.get('scheduled_time'), kwargs.get('platform')))
        self.connection.commit()
        return self.cursor.lastrowid
    
    def schedule_post(self, content_id, channel_id, scheduled_time, task_id=None):
        """Планирование публикации"""
        self.cursor.execute('''
            INSERT INTO scheduled_posts (content_id, channel_id, scheduled_time, task_id)
            VALUES (?, ?, ?, ?)
        ''', (content_id, channel_id, scheduled_time, task_id))
        
        # Обновляем статус контента
        self.cursor.execute('''
            UPDATE content SET status = 'scheduled', scheduled_time = ?
            WHERE id = ?
        ''', (scheduled_time, content_id))
        
        self.connection.commit()
        return self.cursor.lastrowid
    
    def get_scheduled_posts(self, upcoming_only=True):
        """Получение запланированных публикаций"""
        if upcoming_only:
            query = '''
                SELECT sp.*, c.title, c.text, ch.name as channel_name
                FROM scheduled_posts sp
                LEFT JOIN content c ON sp.content_id = c.id
                LEFT JOIN channels ch ON sp.channel_id = ch.id
                WHERE sp.status = 'scheduled' AND sp.scheduled_time > datetime('now')
                ORDER BY sp.scheduled_time ASC
            '''
        else:
            query = '''
                SELECT sp.*, c.title, c.text, ch.name as channel_name
                FROM scheduled_posts sp
                LEFT JOIN content c ON sp.content_id = c.id
                LEFT JOIN channels ch ON sp.channel_id = ch.id
                WHERE sp.status = 'scheduled'
                ORDER BY sp.scheduled_time ASC
            '''
        
        self.cursor.execute(query)
        return [dict(row) for row in self.cursor.fetchall()]
    
    def update_post_status(self, schedule_id, status, error_message=None):
        """Обновление статуса публикации"""
        query = "UPDATE scheduled_posts SET status = ?, error_message = ? WHERE id = ?"
        self.cursor.execute(query, (status, error_message, schedule_id))
        
        # Если опубликовано, обновляем время публикации
        if status == 'published':
            self.cursor.execute('''
                UPDATE scheduled_posts SET published_time = datetime('now')
                WHERE id = ?
            ''', (schedule_id,))
            
            # Обновляем статус контента
            self.cursor.execute('''
                UPDATE content c SET status = 'published', published_time = datetime('now')
                WHERE id = (SELECT content_id FROM scheduled_posts WHERE id = ?)
            ''', (schedule_id,))
        
        self.connection.commit()
    
    def get_statistics(self, channel_id=None, days=7):
        """Получение статистики"""
        query = '''
            SELECT 
                date,
                SUM(views) as total_views,
                SUM(likes) as total_likes,
                SUM(shares) as total_shares,
                SUM(comments) as total_comments,
                SUM(reach) as total_reach,
                COUNT(*) as post_count
            FROM statistics
            WHERE date >= date('now', ?)
        '''
        params = [f'-{days} days']
        
        if channel_id:
            query += " AND channel_id = ?"
            params.append(channel_id)
        
        query += " GROUP BY date ORDER BY date"
        
        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]

# Глобальный экземпляр менеджера базы данных
db_manager = DatabaseManager()

if __name__ == '__main__':
    # Тестирование базы данных
    print("📊 Тестирование базы данных Snoomi Platform")
    print(f"База данных: {db_manager.db_path}")
    
    channels = db_manager.get_channels()
    print(f"\nКаналы ({len(channels)}):")
    for channel in channels:
        print(f"  - {channel['name']} ({channel['platform']}) - {channel['category']}")
    
    content = db_manager.get_content({'limit': 3})
    print(f"\nПоследний контент ({len(content)}):")
    for item in content:
        print(f"  - {item['title']} [{item['status']}]")
    
    scheduled = db_manager.get_scheduled_posts()
    print(f"\nЗапланированные публикации: {len(scheduled)}")
    
    print("\n✅ База данных готова к работе!")