# web/app.py
"""
Flask веб-панель для управления системой монетизации Snoomi Platform
"""
import os
import sys
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime, timedelta
import json

# Добавляем пути для импорта модулей проекта
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

app = Flask(__name__)
app.secret_key = os.environ.get('SESSION_SECRET', 'snoomi-platform-secret-key-2024')

# Настройка Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Модель пользователя
class User(UserMixin):
    def __init__(self, id, username, email, role='client'):
        self.id = id
        self.username = username
        self.email = email
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, email, role FROM users WHERE id = ?', (user_id,))
    user_data = cursor.fetchone()
    conn.close()
    
    if user_data:
        return User(user_data[0], user_data[1], user_data[2], user_data[3])
    return None

def get_db_connection(db_name='snoomi_channels.db'):
    """Создает соединение с базой данных"""
    db_path = os.path.join(project_root, db_name)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Инициализирует базу данных для веб-панели"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Таблица пользователей веб-панели
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'client',  -- client, admin
        telegram_id INTEGER,
        client_id INTEGER,  -- ссылка на clients.id
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP
    )
    ''')
    
    # Добавляем администратора по умолчанию если нет
    cursor.execute('SELECT COUNT(*) FROM users WHERE role = "admin"')
    if cursor.fetchone()[0] == 0:
        admin_hash = generate_password_hash('admin123')
        cursor.execute('''
        INSERT INTO users (username, email, password_hash, role)
        VALUES (?, ?, ?, ?)
        ''', ('admin', 'admin@snoomi.ru', admin_hash, 'admin'))
        print("✅ Создан администратор: admin / admin123")
    
    conn.commit()
    conn.close()

# Инициализируем БД при запуске
with app.app_context():
    init_database()

# ===================== РОУТЫ =====================

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        user_data = cursor.fetchone()
        conn.close()
        
        if user_data and check_password_hash(user_data['password_hash'], password):
            user = User(user_data['id'], user_data['username'], user_data['email'], user_data['role'])
            login_user(user)
            
            # Обновляем время последнего входа
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET last_login = ? WHERE id = ?', 
                         (datetime.now(), user.id))
            conn.commit()
            conn.close()
            
            return redirect(url_for('dashboard'))
        
        flash('Неверное имя пользователя или пароль', 'danger')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Регистрация нового пользователя"""
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Валидация
        if password != confirm_password:
            flash('Пароли не совпадают', 'danger')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('Пароль должен быть не менее 6 символов', 'danger')
            return render_template('register.html')
        
        # Проверяем, есть ли такой пользователь
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE username = ? OR email = ?', (username, email))
        if cursor.fetchone():
            flash('Пользователь с таким именем или email уже существует', 'danger')
            conn.close()
            return render_template('register.html')
        
        # Создаем пользователя
        password_hash = generate_password_hash(password)
        cursor.execute('''
        INSERT INTO users (username, email, password_hash, role)
        VALUES (?, ?, ?, 'client')
        ''', (username, email, password_hash))
        conn.commit()
        conn.close()
        
        flash('Регистрация успешна! Теперь войдите в систему.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    """Выход из системы"""
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    """Панель управления"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Получаем статистику в зависимости от роли
    if current_user.role == 'admin':
        # Статистика для администратора
        cursor.execute('SELECT COUNT(*) FROM clients')
        total_clients = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM client_channels WHERE is_active = 1')
        active_channels = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM channel_posts WHERE DATE(published_at) = DATE("now")')
        posts_today = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE role = "client"')
        total_users = cursor.fetchone()[0]
        
        stats = {
            'total_clients': total_clients,
            'active_channels': active_channels,
            'posts_today': posts_today,
            'total_users': total_users
        }
    else:
        # Статистика для клиента
        # Ищем client_id для этого пользователя
        cursor.execute('SELECT client_id FROM users WHERE id = ?', (current_user.id,))
        user_data = cursor.fetchone()
        
        if user_data and user_data['client_id']:
            client_id = user_data['client_id']
            
            # Получаем статистику клиента
            from database.channels_db import channels_db
            client_stats = channels_db.get_client_statistics(client_id)
            
            if client_stats and client_stats['overall_stats']:
                total_channels, active_channels, total_posts, total_views, total_likes, _ = client_stats['overall_stats']
                stats = {
                    'total_channels': total_channels or 0,
                    'active_channels': active_channels or 0,
                    'total_posts': total_posts or 0,
                    'total_views': total_views or 0,
                    'total_likes': total_likes or 0
                }
            else:
                stats = {
                    'total_channels': 0,
                    'active_channels': 0,
                    'total_posts': 0,
                    'total_views': 0,
                    'total_likes': 0
                }
        else:
            stats = {}
    
    conn.close()
    
    return render_template('dashboard.html', stats=stats, user=current_user)

@app.route('/channels')
@login_required
def channels():
    """Управление каналами"""
    if current_user.role == 'admin':
        # Администратор видит все каналы
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
        SELECT cc.*, c.name as client_name 
        FROM client_channels cc
        JOIN clients c ON cc.client_id = c.id
        ORDER BY cc.created_at DESC
        ''')
        channels_data = cursor.fetchall()
        conn.close()
    else:
        # Клиент видит только свои каналы
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT client_id FROM users WHERE id = ?', (current_user.id,))
        user_data = cursor.fetchone()
        
        if user_data and user_data['client_id']:
            client_id = user_data['client_id']
            cursor.execute('''
            SELECT * FROM client_channels 
            WHERE client_id = ?
            ORDER BY created_at DESC
            ''', (client_id,))
            channels_data = cursor.fetchall()
        else:
            channels_data = []
        
        conn.close()
    
    return render_template('channels.html', channels=channels_data)

@app.route('/api/channels', methods=['POST'])
@login_required
def add_channel():
    """API: Добавление канала"""
    data = request.json
    
    required_fields = ['platform', 'channel_id', 'channel_name']
    if not all(field in data for field in required_fields):
        return jsonify({'success': False, 'error': 'Не все обязательные поля заполнены'}), 400
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Определяем client_id
        if current_user.role == 'admin':
            client_id = data.get('client_id')
            if not client_id:
                return jsonify({'success': False, 'error': 'Для администратора необходимо указать client_id'}), 400
        else:
            cursor.execute('SELECT client_id FROM users WHERE id = ?', (current_user.id,))
            user_data = cursor.fetchone()
            if not user_data or not user_data['client_id']:
                return jsonify({'success': False, 'error': 'Клиент не найден'}), 400
            client_id = user_data['client_id']
        
        # Добавляем канал
        cursor.execute('''
        INSERT INTO client_channels (client_id, platform, channel_id, channel_name, access_token, is_active)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            client_id,
            data['platform'],
            data['channel_id'],
            data['channel_name'],
            data.get('access_token'),
            data.get('is_active', True)
        ))
        
        channel_id = cursor.lastrowid
        
        # Добавляем настройки по умолчанию
        cursor.execute('''
        INSERT INTO channel_settings (channel_id) VALUES (?)
        ''', (channel_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'channel_id': channel_id})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/channels/<int:channel_id>', methods=['PUT'])
@login_required
def update_channel(channel_id):
    """API: Обновление канала"""
    data = request.json
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Проверяем права доступа
        if current_user.role != 'admin':
            cursor.execute('''
            SELECT cc.client_id 
            FROM client_channels cc
            JOIN users u ON cc.client_id = u.client_id
            WHERE cc.id = ? AND u.id = ?
            ''', (channel_id, current_user.id))
            
            if not cursor.fetchone():
                conn.close()
                return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
        
        # Обновляем канал
        update_fields = []
        params = []
        
        for field in ['channel_name', 'access_token', 'is_active']:
            if field in data:
                update_fields.append(f"{field} = ?")
                params.append(data[field])
        
        if update_fields:
            params.append(channel_id)
            query = f"UPDATE client_channels SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(query, params)
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/channels/<int:channel_id>/settings', methods=['PUT'])
@login_required
def update_channel_settings(channel_id):
    """API: Обновление настроек канала"""
    data = request.json
    
    try:
        # Используем нашу базу данных каналов
        from database.channels_db import channels_db
        
        # Проверяем права доступа
        if current_user.role != 'admin':
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
            SELECT cc.client_id 
            FROM client_channels cc
            JOIN users u ON cc.client_id = u.client_id
            WHERE cc.id = ? AND u.id = ?
            ''', (channel_id, current_user.id))
            
            if not cursor.fetchone():
                conn.close()
                return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
            conn.close()
        
        # Обновляем настройки
        success = channels_db.update_channel_settings(channel_id, **data)
        
        return jsonify({'success': success})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/statistics')
@login_required
def statistics():
    """Страница статистики"""
    time_range = request.args.get('range', '7days')
    
    # Определяем диапазон дат
    end_date = datetime.now()
    if time_range == '7days':
        start_date = end_date - timedelta(days=7)
    elif time_range == '30days':
        start_date = end_date - timedelta(days=30)
    else:
        start_date = end_date - timedelta(days=7)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if current_user.role == 'admin':
        # Статистика для администратора
        cursor.execute('''
        SELECT 
            DATE(published_at) as date,
            COUNT(*) as posts,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed
        FROM channel_posts
        WHERE published_at BETWEEN ? AND ?
        GROUP BY DATE(published_at)
        ORDER BY date
        ''', (start_date, end_date))
        
        daily_stats = cursor.fetchall()
        
        # Топ клиентов
        cursor.execute('''
        SELECT 
            c.name as client_name,
            COUNT(DISTINCT cc.id) as channels,
            COUNT(cp.id) as posts,
            SUM(cp.views) as views
        FROM clients c
        LEFT JOIN client_channels cc ON c.id = cc.client_id
        LEFT JOIN channel_posts cp ON cc.id = cp.channel_id
        WHERE cp.published_at BETWEEN ? AND ?
        GROUP BY c.id
        ORDER BY posts DESC
        LIMIT 10
        ''', (start_date, end_date))
        
        top_clients = cursor.fetchall()
        
        stats = {
            'daily_stats': daily_stats,
            'top_clients': top_clients,
            'total_posts': sum(day['posts'] for day in daily_stats),
            'success_rate': 0
        }
        
        if stats['total_posts'] > 0:
            total_successful = sum(day['successful'] for day in daily_stats)
            stats['success_rate'] = round((total_successful / stats['total_posts']) * 100, 1)
        
    else:
        # Статистика для клиента
        cursor.execute('SELECT client_id FROM users WHERE id = ?', (current_user.id,))
        user_data = cursor.fetchone()
        
        if user_data and user_data['client_id']:
            client_id = user_data['client_id']
            
            # Получаем статистику через channels_db
            from database.channels_db import channels_db
            channel_stats = []
            channels = channels_db.get_client_channels(client_id)
            
            for channel in channels:
                channel_id = channel[0]
                stats_data = channels_db.get_channel_stats(channel_id, days=int(time_range.replace('days', '')))
                for day_stats in stats_data:
                    date, posts, views, likes, shares, comments = day_stats
                    channel_stats.append({
                        'date': date,
                        'channel_name': channel[4],
                        'posts': posts,
                        'views': views,
                        'likes': likes,
                        'shares': shares,
                        'comments': comments
                    })
            
            stats = {
                'channel_stats': channel_stats,
                'time_range': time_range
            }
        else:
            stats = {}
    
    conn.close()
    
    return render_template('statistics.html', stats=stats, time_range=time_range)

@app.route('/api/statistics/daily')
@login_required
def api_daily_stats():
    """API: Ежедневная статистика"""
    days = request.args.get('days', 7, type=int)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if current_user.role == 'admin':
        cursor.execute('''
        SELECT 
            DATE(published_at) as date,
            COUNT(*) as posts,
            SUM(views) as views,
            SUM(likes) as likes,
            SUM(shares) as shares
        FROM channel_posts
        WHERE published_at >= date('now', ?)
        GROUP BY DATE(published_at)
        ORDER BY date
        ''', (f'-{days} days',))
    else:
        cursor.execute('SELECT client_id FROM users WHERE id = ?', (current_user.id,))
        user_data = cursor.fetchone()
        
        if user_data and user_data['client_id']:
            client_id = user_data['client_id']
            cursor.execute('''
            SELECT 
                DATE(cp.published_at) as date,
                COUNT(*) as posts,
                SUM(cp.views) as views,
                SUM(cp.likes) as likes,
                SUM(cp.shares) as shares
            FROM channel_posts cp
            JOIN client_channels cc ON cp.channel_id = cc.id
            WHERE cc.client_id = ? AND cp.published_at >= date('now', ?)
            GROUP BY DATE(cp.published_at)
            ORDER BY date
            ''', (client_id, f'-{days} days',))
        else:
            cursor.execute('SELECT NULL LIMIT 0')
    
    stats = cursor.fetchall()
    conn.close()
    
    # Форматируем для Chart.js
    dates = [stat['date'] for stat in stats]
    posts = [stat['posts'] for stat in stats]
    views = [stat['views'] or 0 for stat in stats]
    likes = [stat['likes'] or 0 for stat in stats]
    
    return jsonify({
        'dates': dates,
        'posts': posts,
        'views': views,
        'likes': likes
    })

@app.route('/billing')
@login_required
def billing():
    """Страница биллинга"""
    if current_user.role == 'admin':
        # Администратор видит все платежи
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
        SELECT 
            p.*,
            c.name as client_name,
            u.email as client_email
        FROM payments p
        JOIN clients c ON p.client_id = c.id
        JOIN users u ON c.id = u.client_id
        ORDER BY p.created_at DESC
        LIMIT 100
        ''')
        payments = cursor.fetchall()
        conn.close()
        
        return render_template('billing.html', payments=payments, is_admin=True)
    else:
        # Клиент видит свои платежи
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT client_id FROM users WHERE id = ?', (current_user.id,))
        user_data = cursor.fetchone()
        
        if user_data and user_data['client_id']:
            client_id = user_data['client_id']
            cursor.execute('''
            SELECT * FROM payments 
            WHERE client_id = ?
            ORDER BY created_at DESC
            ''', (client_id,))
            payments = cursor.fetchall()
        else:
            payments = []
        
        conn.close()
        
        return render_template('billing.html', payments=payments, is_admin=False)

@app.route('/api/publish_now', methods=['POST'])
@login_required
def api_publish_now():
    """API: Немедленная публикация"""
    try:
        from posting.multi_publisher import publish_to_client_channels
        
        if current_user.role == 'admin':
            client_id = request.json.get('client_id')
            if not client_id:
                return jsonify({'success': False, 'error': 'Укажите client_id'}), 400
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT client_id FROM users WHERE id = ?', (current_user.id,))
            user_data = cursor.fetchone()
            conn.close()
            
            if not user_data or not user_data['client_id']:
                return jsonify({'success': False, 'error': 'Клиент не найден'}), 400
            
            client_id = user_data['client_id']
        
        # Получаем тему для публикации
        from database.channels_db import channels_db
        channels = channels_db.get_client_channels(client_id, active_only=True)
        
        if not channels:
            return jsonify({'success': False, 'error': 'Нет активных каналов'}), 400
        
        channel_id = channels[0][0]
        topics = channels_db.get_channel_topics(channel_id)
        
        if not topics:
            return jsonify({'success': False, 'error': 'Нет тем для публикации'}), 400
        
        topic = topics[0]['topic']
        keywords = topics[0].get('keywords', [])
        
        # Запускаем публикацию
        result = publish_to_client_channels(client_id, topic, keywords)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/system/health')
@login_required
def api_system_health():
    """API: Проверка здоровья системы"""
    if current_user.role != 'admin':
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    
    health = {
        'database': False,
        'ai_writer': False,
        'ai_artist': False,
        'publishers': {}
    }
    
    try:
        # Проверка базы данных
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT 1')
        health['database'] = True
        conn.close()
    except:
        health['database'] = False
    
    try:
        # Проверка AI Writer
        from ai.yandex_research_writer import YandexResearchWriter
        health['ai_writer'] = True
    except:
        health['ai_writer'] = False
    
    try:
        # Проверка AI Artist
        from ai.yandex_art_final import YandexArtGenerator
        health['ai_artist'] = True
    except:
        health['ai_artist'] = False
    
    # Проверка публикаторов
    try:
        import vk_api
        health['publishers']['vk'] = True
    except:
        health['publishers']['vk'] = False
    
    try:
        import requests
        health['publishers']['telegram'] = True
    except:
        health['publishers']['telegram'] = False
    
    return jsonify(health)

# ===================== ЗАПУСК СЕРВЕРА =====================

if __name__ == '__main__':
    print("🚀 Запуск Snoomi Platform Web Panel...")
    print("=" * 60)
    print(f"📁 Проект: {project_root}")
    print("🌐 Ссылки:")
    print("   • Главная: http://localhost:5000")
    print("   • Вход: http://localhost:5000/login")
    print("   • Админ: admin / admin123")
    print("=" * 60)
    
    app.run(debug=True, host='0.0.0.0', port=5000)