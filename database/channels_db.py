# database/channels_db.py
"""
Система управления каналами для монетизации
"""
import sqlite3
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

TRIAL_MAX_DAYS = 30
TRIAL_AUTO_POSTS_LIMIT = 15
TRIAL_MANUAL_POSTS_LIMIT = 5

class ChannelsDatabase:
    """База данных для управления клиентскими каналами"""
    
    def __init__(self, db_name="snoomi_channels.db"):
        self.db_name = db_name
        self.conn = sqlite3.connect(db_name)
        self.create_tables()
        logger.info(f"✅ Channels Database '{db_name}' подключена")

    @staticmethod
    def _safe_nonnegative_int(value, default=0):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return int(default)
        return parsed if parsed >= 0 else int(default)

    @staticmethod
    def _parse_datetime(raw_value):
        if not raw_value:
            return None
        value = str(raw_value).strip()
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            pass
        patterns = (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        )
        for pattern in patterns:
            try:
                return datetime.strptime(value, pattern)
            except Exception:
                continue
        return None

    def _ensure_column(self, table_name, column_name, ddl):
        cursor = self.conn.cursor()
        cursor.execute(f"PRAGMA table_info('{table_name}')")
        columns = {row[1] for row in cursor.fetchall()}
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")

    def _ensure_trial_schema(self):
        self._ensure_column("clients", "trial_days", f"INTEGER DEFAULT {TRIAL_MAX_DAYS}")
        self._ensure_column("clients", "trial_started_at", "TIMESTAMP")
        self._ensure_column("clients", "trial_ends_at", "TIMESTAMP")
        self._ensure_column("clients", "trial_auto_posts_limit", f"INTEGER DEFAULT {TRIAL_AUTO_POSTS_LIMIT}")
        self._ensure_column("clients", "trial_auto_posts_used", "INTEGER DEFAULT 0")
        self._ensure_column("clients", "trial_manual_posts_limit", f"INTEGER DEFAULT {TRIAL_MANUAL_POSTS_LIMIT}")
        self._ensure_column("clients", "trial_manual_posts_used", "INTEGER DEFAULT 0")
        self._ensure_column("clients", "trial_completed_at", "TIMESTAMP")
        self._ensure_column("channel_posts", "publish_mode", "TEXT DEFAULT 'auto'")

        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            UPDATE clients
            SET trial_days = COALESCE(NULLIF(trial_days, 0), {TRIAL_MAX_DAYS})
            WHERE trial_days IS NULL OR trial_days <= 0
            """
        )
        cursor.execute(
            f"""
            UPDATE clients
            SET trial_auto_posts_limit = COALESCE(NULLIF(trial_auto_posts_limit, 0), {TRIAL_AUTO_POSTS_LIMIT})
            WHERE trial_auto_posts_limit IS NULL OR trial_auto_posts_limit <= 0
            """
        )
        cursor.execute(
            """
            UPDATE clients
            SET trial_auto_posts_used = COALESCE(trial_auto_posts_used, 0)
            WHERE trial_auto_posts_used IS NULL
            """
        )
        cursor.execute(
            f"""
            UPDATE clients
            SET trial_manual_posts_limit = COALESCE(NULLIF(trial_manual_posts_limit, 0), {TRIAL_MANUAL_POSTS_LIMIT})
            WHERE trial_manual_posts_limit IS NULL OR trial_manual_posts_limit <= 0
            """
        )
        cursor.execute(
            """
            UPDATE clients
            SET trial_manual_posts_used = COALESCE(trial_manual_posts_used, 0)
            WHERE trial_manual_posts_used IS NULL
            """
        )
        cursor.execute(
            """
            UPDATE clients
            SET trial_started_at = COALESCE(trial_started_at, created_at)
            WHERE plan = 'trial' AND (trial_started_at IS NULL OR trial_started_at = '')
            """
        )
        cursor.execute(
            """
            UPDATE clients
            SET trial_ends_at = datetime(COALESCE(trial_started_at, created_at), '+' || trial_days || ' days')
            WHERE plan = 'trial' AND (trial_ends_at IS NULL OR trial_ends_at = '')
            """
        )
        self.conn.commit()

    def _is_trial_channel_allowed_for_auto_publish(self, channel_row):
        if str(channel_row.get("client_plan") or "").strip().lower() != "trial":
            return True

        trial_completed_at = self._parse_datetime(channel_row.get("trial_completed_at"))
        if trial_completed_at:
            return False

        trial_ends_at = self._parse_datetime(channel_row.get("trial_ends_at"))
        if trial_ends_at and datetime.now() > trial_ends_at:
            return False

        auto_limit = self._safe_nonnegative_int(
            channel_row.get("trial_auto_posts_limit"),
            TRIAL_AUTO_POSTS_LIMIT,
        )
        auto_limit = max(1, auto_limit)
        auto_used = self._safe_nonnegative_int(channel_row.get("trial_auto_posts_used"), 0)
        return auto_used < auto_limit

    def _increment_trial_auto_usage(self, channel_id):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT c.id, c.plan, c.trial_auto_posts_used, c.trial_auto_posts_limit, c.trial_completed_at
            FROM clients c
            JOIN client_channels cc ON cc.client_id = c.id
            WHERE cc.id = ?
            LIMIT 1
            """,
            (channel_id,),
        )
        row = cursor.fetchone()
        if not row:
            return

        client_id, plan_name, used_raw, limit_raw, completed_at = row
        if str(plan_name or "").strip().lower() != "trial":
            return
        if completed_at:
            return

        auto_used = self._safe_nonnegative_int(used_raw, 0) + 1
        auto_limit = max(1, self._safe_nonnegative_int(limit_raw, TRIAL_AUTO_POSTS_LIMIT))

        if auto_used >= auto_limit:
            cursor.execute(
                """
                UPDATE clients
                SET trial_auto_posts_used = ?, trial_completed_at = COALESCE(trial_completed_at, CURRENT_TIMESTAMP)
                WHERE id = ?
                """,
                (auto_used, client_id),
            )
        else:
            cursor.execute(
                "UPDATE clients SET trial_auto_posts_used = ? WHERE id = ?",
                (auto_used, client_id),
            )
    
    def create_tables(self):
        """Создает таблицы для системы каналов"""
        cursor = self.conn.cursor()
        
        # Таблица клиентов
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            telegram_id INTEGER UNIQUE,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active',  -- active, paused, cancelled
            plan TEXT DEFAULT 'basic',     -- basic, premium, custom
            billing_day INTEGER DEFAULT 1, -- день месяца для списания
            next_billing_date DATE
        )
        ''')
        
        # Таблица каналов клиентов
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS client_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            platform TEXT NOT NULL,  -- 'telegram', 'vk', 'ok', 'dzen'
            channel_id TEXT NOT NULL,  -- ID канала или @username
            channel_name TEXT,
            access_token TEXT,  -- токен для доступа
            additional_config TEXT,  -- JSON с дополнительными настройками
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE CASCADE
        )
        ''')
        
        # Таблица настроек публикаций для каналов
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS channel_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            publish_hour INTEGER DEFAULT 10,  -- время публикации (0-23)
            publish_frequency TEXT DEFAULT 'daily',  -- daily, weekly, manual
            topics TEXT,  -- JSON массив разрешенных тем
            hashtags TEXT,  -- JSON массив хештегов
            max_posts_per_day INTEGER DEFAULT 1,
            is_auto_generate BOOLEAN DEFAULT 1,
            use_ai_images BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (channel_id) REFERENCES client_channels (id) ON DELETE CASCADE
        )
        ''')
        
        # Таблица истории публикаций
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS channel_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            post_id TEXT,  -- ID поста в платформе
            topic TEXT,
            content TEXT,
            image_path TEXT,
            publish_mode TEXT DEFAULT 'auto',  -- auto, manual, manual_test, manual_agent
            published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            success BOOLEAN,
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            error_message TEXT,
            FOREIGN KEY (channel_id) REFERENCES client_channels (id) ON DELETE CASCADE
        )
        ''')
        
        # Таблица статистики
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS channel_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            date DATE NOT NULL,
            posts_published INTEGER DEFAULT 0,
            total_views INTEGER DEFAULT 0,
            total_likes INTEGER DEFAULT 0,
            total_shares INTEGER DEFAULT 0,
            total_comments INTEGER DEFAULT 0,
            UNIQUE(channel_id, date),
            FOREIGN KEY (channel_id) REFERENCES client_channels (id) ON DELETE CASCADE
        )
        ''')
        
        # Таблица тем для каналов
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS channel_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            topic TEXT NOT NULL,
            keywords TEXT,  -- JSON массив ключевых слов
            priority INTEGER DEFAULT 1,  -- приоритет (1-10)
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (channel_id) REFERENCES client_channels (id) ON DELETE CASCADE
        )
        ''')

        self._ensure_trial_schema()
        self.conn.commit()
        logger.info("✅ Таблицы системы каналов созданы")
    
    # ===================== МЕТОДЫ ДЛЯ КЛИЕНТОВ =====================
    
    def add_client(self, name, email=None, telegram_id=None, phone=None, 
                   plan='basic', billing_day=1):
        """Добавляет нового клиента"""
        try:
            cursor = self.conn.cursor()
            
            # Вычисляем дату следующего списания
            today = datetime.now()
            if billing_day > 28:
                billing_day = 28
            
            next_billing = datetime(today.year, today.month, billing_day)
            if today.day >= billing_day:
                # Если сегодняшний день уже после дня списания, берем следующий месяц
                if today.month == 12:
                    next_billing = datetime(today.year + 1, 1, billing_day)
                else:
                    next_billing = datetime(today.year, today.month + 1, billing_day)
            
            cursor.execute('''
            INSERT INTO clients 
            (name, email, telegram_id, phone, plan, billing_day, next_billing_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (name, email, telegram_id, phone, plan, billing_day, next_billing.date()))
            
            self.conn.commit()
            client_id = cursor.lastrowid
            logger.info(f"✅ Клиент добавлен: {name} (ID: {client_id})")
            return client_id
            
        except Exception as e:
            logger.error(f"❌ Ошибка добавления клиента: {e}")
            return None
    
    def get_client_by_telegram(self, telegram_id):
        """Получает клиента по Telegram ID"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM clients WHERE telegram_id = ?', (telegram_id,))
        return cursor.fetchone()
    
    def update_client_status(self, client_id, status):
        """Обновляет статус клиента"""
        cursor = self.conn.cursor()
        cursor.execute('UPDATE clients SET status = ? WHERE id = ?', (status, client_id))
        self.conn.commit()
        return cursor.rowcount > 0
    
    # ===================== МЕТОДЫ ДЛЯ КАНАЛОВ =====================
    
    def add_channel(self, client_id, platform, channel_id, channel_name=None, 
                   access_token=None, config=None):
        """Добавляет канал клиента"""
        try:
            config_json = json.dumps(config) if config else None
            
            cursor = self.conn.cursor()
            cursor.execute('''
            INSERT INTO client_channels 
            (client_id, platform, channel_id, channel_name, access_token, additional_config)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (client_id, platform, channel_id, channel_name, access_token, config_json))
            
            channel_db_id = cursor.lastrowid
            
            # Создаем настройки по умолчанию для канала
            cursor.execute('''
            INSERT INTO channel_settings (channel_id) VALUES (?)
            ''', (channel_db_id,))
            
            self.conn.commit()
            logger.info(f"✅ Канал добавлен: {platform}:{channel_id}")
            return channel_db_id
            
        except Exception as e:
            logger.error(f"❌ Ошибка добавления канала: {e}")
            return None
    
    def get_client_channels(self, client_id, active_only=True):
        """Получает все каналы клиента"""
        cursor = self.conn.cursor()
        if active_only:
            cursor.execute('''
            SELECT * FROM client_channels 
            WHERE client_id = ? AND is_active = 1
            ORDER BY created_at DESC
            ''', (client_id,))
        else:
            cursor.execute('''
            SELECT * FROM client_channels 
            WHERE client_id = ? 
            ORDER BY created_at DESC
            ''', (client_id,))
        return cursor.fetchall()
    
    def get_channel_settings(self, channel_id):
        """Получает настройки канала"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM channel_settings WHERE channel_id = ?', (channel_id,))
        row = cursor.fetchone()
        
        if row:
            # Парсим JSON поля
            settings = dict(zip([description[0] for description in cursor.description], row))
            if settings.get('topics'):
                settings['topics'] = json.loads(settings['topics'])
            if settings.get('hashtags'):
                settings['hashtags'] = json.loads(settings['hashtags'])
            return settings
        return None
    
    def update_channel_settings(self, channel_id, **settings):
        """Обновляет настройки канала"""
        try:
            cursor = self.conn.cursor()
            
            # Подготавливаем данные
            topics_json = json.dumps(settings.get('topics')) if 'topics' in settings else None
            hashtags_json = json.dumps(settings.get('hashtags')) if 'hashtags' in settings else None
            
            # Формируем запрос динамически
            update_fields = []
            params = []
            
            field_map = {
                'publish_hour': settings.get('publish_hour'),
                'publish_frequency': settings.get('publish_frequency'),
                'topics': topics_json,
                'hashtags': hashtags_json,
                'max_posts_per_day': settings.get('max_posts_per_day'),
                'is_auto_generate': settings.get('is_auto_generate'),
                'use_ai_images': settings.get('use_ai_images')
            }
            
            for field, value in field_map.items():
                if value is not None:
                    update_fields.append(f"{field} = ?")
                    params.append(value)
            
            if not update_fields:
                return False
            
            params.append(channel_id)
            query = f"UPDATE channel_settings SET {', '.join(update_fields)} WHERE channel_id = ?"
            
            cursor.execute(query, params)
            self.conn.commit()
            
            logger.info(f"✅ Настройки канала {channel_id} обновлены")
            return cursor.rowcount > 0
            
        except Exception as e:
            logger.error(f"❌ Ошибка обновления настроек: {e}")
            return False
    
    # ===================== МЕТОДЫ ДЛЯ ТЕМ =====================
    
    def add_topic_to_channel(self, channel_id, topic, keywords=None, priority=1):
        """Добавляет тему для канала"""
        try:
            keywords_json = json.dumps(keywords) if keywords else None
            
            cursor = self.conn.cursor()
            cursor.execute('''
            INSERT INTO channel_topics 
            (channel_id, topic, keywords, priority)
            VALUES (?, ?, ?, ?)
            ''', (channel_id, topic, keywords_json, priority))
            
            self.conn.commit()
            topic_id = cursor.lastrowid
            logger.info(f"✅ Тема добавлена для канала {channel_id}: {topic}")
            return topic_id
            
        except Exception as e:
            logger.error(f"❌ Ошибка добавления темы: {e}")
            return None
    
    def get_channel_topics(self, channel_id, active_only=True):
        """Получает все темы канала"""
        cursor = self.conn.cursor()
        if active_only:
            cursor.execute('''
            SELECT * FROM channel_topics 
            WHERE channel_id = ? AND is_active = 1
            ORDER BY priority DESC, created_at DESC
            ''', (channel_id,))
        else:
            cursor.execute('''
            SELECT * FROM channel_topics 
            WHERE channel_id = ? 
            ORDER BY priority DESC, created_at DESC
            ''', (channel_id,))
        
        rows = cursor.fetchall()
        topics = []
        for row in rows:
            topic = dict(zip([description[0] for description in cursor.description], row))
            if topic.get('keywords'):
                topic['keywords'] = json.loads(topic['keywords'])
            topics.append(topic)
        
        return topics
    
    # ===================== МЕТОДЫ ДЛЯ ПУБЛИКАЦИЙ =====================
    
    def add_channel_post(
        self,
        channel_id,
        post_id,
        topic,
        content,
        image_path=None,
        success=True,
        error_message=None,
        publish_mode="auto",
    ):
        """Добавляет запись о публикации в канал"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
            INSERT INTO channel_posts 
            (channel_id, post_id, topic, content, image_path, success, error_message, publish_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                channel_id,
                post_id,
                topic,
                content[:2000],
                image_path,
                success,
                error_message,
                str(publish_mode or "auto").strip().lower()[:30],
            ))
            
            # Обновляем статистику за сегодня
            today = datetime.now().date()
            self._update_daily_stats(channel_id, today, 1 if success else 0)

            if success and str(publish_mode or "").strip().lower() == "auto":
                self._increment_trial_auto_usage(channel_id)
            
            self.conn.commit()
            post_db_id = cursor.lastrowid
            logger.info(f"✅ Публикация добавлена для канала {channel_id}")
            return post_db_id
            
        except Exception as e:
            logger.error(f"❌ Ошибка добавления публикации: {e}")
            return None
    
    def _update_daily_stats(self, channel_id, date, posts_increment=0):
        """Обновляет дневную статистику"""
        try:
            cursor = self.conn.cursor()
            
            # Пробуем обновить существующую запись
            cursor.execute('''
            UPDATE channel_stats 
            SET posts_published = posts_published + ?
            WHERE channel_id = ? AND date = ?
            ''', (posts_increment, channel_id, date))
            
            # Если не было записи, создаем новую
            if cursor.rowcount == 0:
                cursor.execute('''
                INSERT INTO channel_stats (channel_id, date, posts_published)
                VALUES (?, ?, ?)
                ''', (channel_id, date, posts_increment))
            
            self.conn.commit()
            
        except Exception as e:
            logger.error(f"❌ Ошибка обновления статистики: {e}")
    
    def get_channel_stats(self, channel_id, days=30):
        """Получает статистику канала за период"""
        cursor = self.conn.cursor()
        
        cursor.execute('''
        SELECT 
            date,
            posts_published,
            total_views,
            total_likes,
            total_shares,
            total_comments
        FROM channel_stats 
        WHERE channel_id = ? AND date >= date('now', ?)
        ORDER BY date DESC
        ''', (channel_id, f'-{days} days'))
        
        return cursor.fetchall()
    
    def get_channel_posts(self, channel_id, limit=50):
        """Получает последние публикации канала"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT 
            post_id, topic, published_at, success, views, likes, shares, comments
        FROM channel_posts 
        WHERE channel_id = ?
        ORDER BY published_at DESC 
        LIMIT ?
        ''', (channel_id, limit))
        
        return cursor.fetchall()
    
    # ===================== УТИЛИТЫ =====================
    
    def _should_publish_by_frequency(self, publish_frequency, last_published_at):
        """
        Проверяет, можно ли публиковать сегодня по частотности.

        Поддерживаемые значения:
        - daily: каждый день
        - every_other_day: через день
        - every_two_days: через 2 дня
        """
        if not publish_frequency or publish_frequency == 'daily':
            return True
        if publish_frequency == 'manual':
            return False

        interval_days = {
            'daily': 1,
            'every_other_day': 2,
            'every_two_days': 3,
            # обратная совместимость
            'every_2_days': 3,
            'weekly': 7,
        }.get(str(publish_frequency).strip().lower(), 1)

        if not last_published_at:
            return True

        try:
            last_dt = datetime.fromisoformat(str(last_published_at))
        except Exception:
            return True

        elapsed_days = (datetime.now() - last_dt).total_seconds() / 86400
        return elapsed_days >= interval_days

    def get_channels_for_publishing(self, hour=None):
        """Получает каналы, которые нужно опубликовать сейчас"""
        cursor = self.conn.cursor()
        
        query = '''
        SELECT 
            cc.id as channel_id,
            cc.platform,
            cc.channel_id as platform_channel_id,
            cc.channel_name,
            cc.access_token,
            cs.publish_hour,
            cs.publish_frequency,
            cs.topics,
            cs.hashtags,
            cs.max_posts_per_day,
            cs.is_auto_generate,
            cs.use_ai_images,
            cc.client_id as client_id,
            cl.name as client_name,
            cl.plan as client_plan,
            cl.trial_ends_at,
            cl.trial_auto_posts_limit,
            cl.trial_auto_posts_used,
            cl.trial_completed_at,
            lp.last_published_at
        FROM client_channels cc
        JOIN channel_settings cs ON cc.id = cs.channel_id
        JOIN clients cl ON cc.client_id = cl.id
        LEFT JOIN (
            SELECT channel_id, MAX(published_at) as last_published_at
            FROM channel_posts
            WHERE success = 1
            GROUP BY channel_id
        ) lp ON cc.id = lp.channel_id
        WHERE cc.is_active = 1 
        AND cl.status = 'active'
        AND cs.is_auto_generate = 1
        '''
        
        params = []
        
        if hour is not None:
            query += ' AND cs.publish_hour = ?'
            params.append(hour)
        
        query += ' ORDER BY cc.created_at'
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        channels = []
        for row in rows:
            channel = dict(zip([description[0] for description in cursor.description], row))

            if not self._should_publish_by_frequency(
                channel.get('publish_frequency'),
                channel.get('last_published_at')
            ):
                continue

            if not self._is_trial_channel_allowed_for_auto_publish(channel):
                continue
            
            # Парсим JSON поля
            if channel.get('topics'):
                channel['topics'] = json.loads(channel['topics'])
            if channel.get('hashtags'):
                channel['hashtags'] = json.loads(channel['hashtags'])
            
            channels.append(channel)
        
        return channels
    
    def get_client_statistics(self, client_id):
        """Получает статистику по всем каналам клиента"""
        cursor = self.conn.cursor()
        
        # Общая статистика по клиенту
        cursor.execute('''
        SELECT 
            COUNT(DISTINCT cc.id) as total_channels,
            COUNT(DISTINCT CASE WHEN cc.is_active = 1 THEN cc.id END) as active_channels,
            SUM(cs.posts_published) as total_posts,
            SUM(cs.total_views) as total_views,
            SUM(cs.total_likes) as total_likes,
            SUM(cs.total_shares) as total_shares
        FROM clients c
        LEFT JOIN client_channels cc ON c.id = cc.client_id
        LEFT JOIN (
            SELECT channel_id, 
                   SUM(posts_published) as posts_published,
                   SUM(total_views) as total_views,
                   SUM(total_likes) as total_likes,
                   SUM(total_shares) as total_shares
            FROM channel_stats
            GROUP BY channel_id
        ) cs ON cc.id = cs.channel_id
        WHERE c.id = ?
        GROUP BY c.id
        ''', (client_id,))
        
        stats = cursor.fetchone()
        
        # Детали по каналам
        cursor.execute('''
        SELECT 
            cc.id,
            cc.platform,
            cc.channel_name,
            cc.is_active,
            cs.posts_published,
            cs.total_views,
            cs.total_likes
        FROM client_channels cc
        LEFT JOIN (
            SELECT channel_id, 
                   SUM(posts_published) as posts_published,
                   SUM(total_views) as total_views,
                   SUM(total_likes) as total_likes
            FROM channel_stats
            GROUP BY channel_id
        ) cs ON cc.id = cs.channel_id
        WHERE cc.client_id = ?
        ORDER BY cc.created_at DESC
        ''', (client_id,))
        
        channels = cursor.fetchall()
        
        return {
            'overall_stats': stats,
            'channels': channels
        }
    
    def close(self):
        """Закрывает соединение с БД"""
        self.conn.close()
        logger.info("✅ Соединение с Channels DB закрыто")


# Создаем глобальный экземпляр
channels_db = ChannelsDatabase()

# Тест
if __name__ == "__main__":
    print("🧪 Тест системы управления каналами")
    print("=" * 60)
    
    db = ChannelsDatabase("test_channels.db")
    
    # Тест 1: Добавление клиента
    print("1. Добавляем тестового клиента...")
    client_id = db.add_client(
        name="Тестовый Клиент",
        email="test@example.com",
        telegram_id=123456789,
        plan="premium"
    )
    
    if client_id:
        print(f"   ✅ Клиент добавлен, ID: {client_id}")
        
        # Тест 2: Добавление каналов
        print("2. Добавляем тестовые каналы...")
        
        # Telegram канал
        tg_channel_id = db.add_channel(
            client_id=client_id,
            platform="telegram",
            channel_id="@test_channel",
            channel_name="Мой Тестовый Канал"
        )
        
        # VK группа
        vk_channel_id = db.add_channel(
            client_id=client_id,
            platform="vk",
            channel_id="-12345678",
            channel_name="Группа ВКонтакте"
        )
        
        if tg_channel_id and vk_channel_id:
            print(f"   ✅ Каналы добавлены: TG ID:{tg_channel_id}, VK ID:{vk_channel_id}")
            
            # Тест 3: Добавление тем
            print("3. Добавляем темы для каналов...")
            
            db.add_topic_to_channel(
                channel_id=tg_channel_id,
                topic="Новости технологий",
                keywords=["технологии", "гаджеты", "инновации"],
                priority=5
            )
            
            db.add_topic_to_channel(
                channel_id=tg_channel_id,
                topic="Обзоры смартфонов",
                keywords=["смартфон", "обзор", "характеристики"],
                priority=3
            )
            
            print("   ✅ Темы добавлены")
            
            # Тест 4: Настройки каналов
            print("4. Настраиваем каналы...")
            
            db.update_channel_settings(
                channel_id=tg_channel_id,
                publish_hour=14,
                publish_frequency="daily",
                topics=["технологии", "гаджеты"],
                hashtags=["#технологии", "#гаджеты", "#обзор"],
                max_posts_per_day=2
            )
            
            # Тест 5: Получение каналов для публикации
            print("5. Получаем каналы для публикации в 14:00...")
            channels = db.get_channels_for_publishing(hour=14)
            print(f"   ✅ Найдено каналов: {len(channels)}")
            
            # Тест 6: Статистика
            print("6. Получаем статистику клиента...")
            stats = db.get_client_statistics(client_id)
            if stats['overall_stats']:
                total_channels, active_channels, total_posts, total_views, total_likes, total_shares = stats['overall_stats']
                print(f"   📊 Каналы: {total_channels} всего, {active_channels} активных")
                print(f"   📊 Посты: {total_posts or 0}")
                print(f"   👁️ Просмотры: {total_views or 0}")
    
    db.close()
    print("\n" + "=" * 60)
    print("✅ Тест системы каналов завершен успешно!")