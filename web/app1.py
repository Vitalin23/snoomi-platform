"""
Основной файл веб-приложения Snoomi Platform
Интеграция с планировщиком публикаций
"""

# ========== НАСТРОЙКА ПУТЕЙ ИМПОРТА ==========
import sys
import os
from pathlib import Path

# Получаем абсолютный путь к корню проекта (Snoomi-platform)
PROJECT_ROOT = Path(__file__).parent.parent  # web/ -> Snoomi-platform/
# Добавляем корень проекта и его папки в пути Python
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'ai'))
sys.path.insert(0, str(PROJECT_ROOT / 'posting'))
# ============================================

# Импорт Flask и расширений
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import json
import logging

# Настройка логирования
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Создание приложения Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Конфигурация базы данных
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///snoomi.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Инициализация расширений
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите для доступа к этой странице.'
login_manager.login_message_category = 'info'

# ========== МОДЕЛИ БАЗЫ ДАННЫХ ==========
class User(db.Model, UserMixin):
    """Модель пользователя"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='user')  # user, admin
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    def set_password(self, password):
        """Установка хеша пароля"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Проверка пароля"""
        return check_password_hash(self.password_hash, password)

class Channel(db.Model):
    """Модель канала/тематики для публикаций"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    platform = db.Column(db.String(50), nullable=False)  # 'vk', 'telegram', 'multiple'
    channel_id = db.Column(db.String(100), nullable=False)
    access_token = db.Column(db.String(500))
    category = db.Column(db.String(100), default='general')
    is_active = db.Column(db.Boolean, default=True)
    settings = db.Column(db.Text, default='{}')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('channels', lazy=True))
    
    def get_settings(self):
        """Получение настроек канала в виде словаря"""
        try:
            return json.loads(self.settings) if self.settings else {}
        except:
            return {}

class GeneratedContent(db.Model):
    """Модель сгенерированного контента"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    text = db.Column(db.Text, nullable=False)
    image_path = db.Column(db.String(500))
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'))
    topic = db.Column(db.String(200))
    status = db.Column(db.String(50), default='draft')
    scheduled_time = db.Column(db.DateTime)
    published_time = db.Column(db.DateTime)
    platform = db.Column(db.String(50))
    engagement = db.Column(db.Integer, default=0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    channel = db.relationship('Channel', backref=db.backref('contents', lazy=True))
    user = db.relationship('User', backref=db.backref('contents', lazy=True))

class ScheduledPost(db.Model):
    """Модель запланированных публикаций"""
    id = db.Column(db.Integer, primary_key=True)
    content_id = db.Column(db.Integer, db.ForeignKey('generated_content.id'))
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=False)
    scheduled_time = db.Column(db.DateTime, nullable=False)
    published_time = db.Column(db.DateTime)
    task_id = db.Column(db.String(100))
    status = db.Column(db.String(50), default='scheduled')
    error_message = db.Column(db.Text)
    platform_data = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    content = db.relationship('GeneratedContent', backref=db.backref('schedules', lazy=True))
    channel = db.relationship('Channel', backref=db.backref('scheduled_posts', lazy=True))

# ========== ЗАГРУЗЧИК ПОЛЬЗОВАТЕЛЯ ==========
@login_manager.user_loader
def load_user(user_id):
    """Загрузка пользователя по ID"""
    return User.query.get(int(user_id))

# ========== ИНИЦИАЛИЗАЦИЯ МОДУЛЕЙ SNOOMI ==========
try:
    from ai.text_generator import TextGenerator
    from ai.image_generator import ImageGenerator
    from posting.scheduler import ContentScheduler
    from vk_publisher import VKPublisher
    from tg_poster import TelegramPoster
    logger.info("✅ Модули Snoomi успешно импортированы")
    
    text_generator = TextGenerator()
    image_generator = ImageGenerator()
    content_scheduler = ContentScheduler()
    vk_publisher = VKPublisher()
    tg_poster = TelegramPoster()
try:
    # Получаем данные из конфига
    from config import Config
    tg_poster = TelegramPoster(
        bot_token=Config.TELEGRAM_BOT_TOKEN,
        channel_id=Config.TELEGRAM_CHANNEL_ID
    )
    logger.info(f"✅ Telegram Poster загружен: {Config.TELEGRAM_CHANNEL_ID}")
except Exception as e:
    logger.warning(f"⚠️ Telegram Poster не настроен: {e}")
    # Создаем заглушку
    class TelegramPosterStub:
        def post(self, text, image_path=None):
            return {"success": True, "message": "Заглушка Telegram"}
    
    tg_poster = TelegramPoster
    
except ImportError as e:
    logger.error(f"❌ Ошибка импорта модулей: {e}")
    # Заглушки для разработки
    class TextGenerator:
        def generate_for_topic(self, topic):
            return f"Сгенерированная статья по теме: {topic}"
    
    class ImageGenerator:
        def create_image_for_article(self, text, topic):
            return f"/static/placeholder_{hash(topic) % 10}.jpg"
    
    class ContentScheduler:
        def add_post(self, **kwargs):
            return f"task_{datetime.now().timestamp()}"
        
        def get_scheduled_posts(self):
            return []
    
    text_generator = TextGenerator()
    image_generator = ImageGenerator()
    content_scheduler = ContentScheduler()

# ========== МАРШРУТЫ АУТЕНТИФИКАЦИИ ==========
@app.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user, remember=True)
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            flash('Вы успешно вошли в систему!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        
        flash('Неверное имя пользователя или пароль', 'danger')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Страница регистрации"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Валидация
        errors = []
        if not username or len(username) < 3:
            errors.append('Имя пользователя должно быть не менее 3 символов')
        if not email or '@' not in email:
            errors.append('Введите корректный email')
        if not password or len(password) < 6:
            errors.append('Пароль должен быть не менее 6 символов')
        if password != confirm_password:
            errors.append('Пароли не совпадают')
        
        # Проверка существующего пользователя
        if User.query.filter_by(username=username).first():
            errors.append('Это имя пользователя уже занято')
        if User.query.filter_by(email=email).first():
            errors.append('Этот email уже используется')
        
        if errors:
            for error in errors:
                flash(error, 'danger')
        else:
            # Создание пользователя
            new_user = User(username=username, email=email)
            new_user.set_password(password)
            
            db.session.add(new_user)
            db.session.commit()
            
            flash('Регистрация успешна! Теперь вы можете войти.', 'success')
            return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    """Выход из системы"""
    logout_user()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))

# ========== ОСНОВНЫЕ МАРШРУТЫ ==========
@app.route('/')
def index():
    """Главная страница - дашборд"""
    stats = {
        'total_channels': 0,
        'total_content': 0,
        'published_content': 0,
        'scheduled_content': 0
    }
    
    recent_content = []
    upcoming_posts = []
    
    if current_user.is_authenticated:
        # Статистика для текущего пользователя
        stats['total_channels'] = Channel.query.filter_by(user_id=current_user.id).count()
        stats['total_content'] = GeneratedContent.query.filter_by(user_id=current_user.id).count()
        stats['published_content'] = GeneratedContent.query.filter_by(
            user_id=current_user.id, status='published').count()
        stats['scheduled_content'] = ScheduledPost.query.join(Channel).filter(
            Channel.user_id == current_user.id, 
            ScheduledPost.status == 'scheduled'
        ).count()
        
        # Последний контент
        recent_content = GeneratedContent.query.filter_by(
            user_id=current_user.id
        ).order_by(GeneratedContent.created_at.desc()).limit(5).all()
        
        # Предстоящие публикации
        upcoming_posts = ScheduledPost.query.join(Channel).filter(
            Channel.user_id == current_user.id,
            ScheduledPost.status == 'scheduled',
            ScheduledPost.scheduled_time >= datetime.utcnow()
        ).order_by(ScheduledPost.scheduled_time.asc()).limit(5).all()
    
    return render_template('index.html',
                         stats=stats,
                         recent_content=recent_content,
                         upcoming_posts=upcoming_posts,
                         user=current_user)

@app.route('/content')
@login_required
def content_management():
    """Управление контентом"""
    all_content = GeneratedContent.query.filter_by(
        user_id=current_user.id
    ).order_by(GeneratedContent.created_at.desc()).all()
    
    channels = Channel.query.filter_by(
        user_id=current_user.id, is_active=True
    ).all()
    
    scheduled_posts = []
    try:
        scheduled_posts = content_scheduler.get_scheduled_posts()
    except Exception as e:
        logger.error(f"Ошибка получения запланированных постов: {e}")
    
    return render_template('content.html',
                         content_list=all_content,
                         channels=channels,
                         scheduled_posts=scheduled_posts,
                         user=current_user)

@app.route('/channels')
@login_required
def channel_management():
    """Управление каналами/тематиками"""
    channels = Channel.query.filter_by(
        user_id=current_user.id
    ).order_by(Channel.created_at.desc()).all()
    
    categories = {}
    for channel in channels:
        if channel.category not in categories:
            categories[channel.category] = []
        categories[channel.category].append(channel)
    
    return render_template('channels.html',
                         channels=channels,
                         categories=categories,
                         user=current_user)

@app.route('/analytics')
@login_required
def analytics():
    """Аналитика и отчеты"""
    content_by_channel = db.session.query(
        Channel.name,
        db.func.count(GeneratedContent.id).label('content_count')
    ).join(GeneratedContent).filter(
        Channel.user_id == current_user.id
    ).group_by(Channel.name).all()
    
    last_7_days = [(datetime.utcnow() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
    
    return render_template('analytics.html',
                         content_by_channel=content_by_channel,
                         last_7_days=last_7_days,
                         user=current_user)

@app.route('/profile')
@login_required
def profile():
    """Профиль пользователя"""
    return render_template('profile.html', user=current_user)

# ========== API МАРШРУТЫ ==========
@app.route('/api/generate_text', methods=['POST'])
@login_required
def api_generate_text():
    """API для генерации текста"""
    try:
        data = request.json if request.is_json else request.form
        topic = data.get('topic', '')
        channel_id = data.get('channel_id')
        
        if not topic:
            return jsonify({'error': 'Тема не указана'}), 400
        
        channel = None
        if channel_id:
            channel = Channel.query.filter_by(
                id=channel_id, user_id=current_user.id
            ).first()
            if not channel:
                return jsonify({'error': 'Канал не найден'}), 404
        
        if channel and channel.category:
            enhanced_topic = f"{topic} в контексте {channel.category}"
            generated_text = text_generator.generate_for_topic(enhanced_topic)
        else:
            generated_text = text_generator.generate_for_topic(topic)
        
        new_content = GeneratedContent(
            title=f"Статья: {topic[:50]}...",
            text=generated_text,
            topic=topic,
            channel_id=channel_id,
            user_id=current_user.id,
            status='draft'
        )
        
        db.session.add(new_content)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'text': generated_text,
            'content_id': new_content.id
        })
        
    except Exception as e:
        logger.error(f"Ошибка генерации текста: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate_image', methods=['POST'])
@login_required
def api_generate_image():
    """API для генерации изображения"""
    try:
        data = request.json if request.is_json else request.form
        topic = data.get('topic', '')
        content_id = data.get('content_id')
        
        if not topic:
            return jsonify({'error': 'Тема не указана'}), 400
        
        if content_id:
            content = GeneratedContent.query.filter_by(
                id=content_id, user_id=current_user.id
            ).first()
            if not content:
                return jsonify({'error': 'Контент не найден'}), 404
        
        image_path = image_generator.create_image_for_article("", topic)
        
        if content_id and content:
            content.image_path = image_path
            db.session.commit()
        
        return jsonify({
            'success': True,
            'image_path': image_path
        })
        
    except Exception as e:
        logger.error(f"Ошибка генерации изображения: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/schedule_post', methods=['POST'])
@login_required
def api_schedule_post():
    """API для планирования публикации"""
    try:
        data = request.json if request.is_json else request.form
        
        required_fields = ['text', 'channel_id', 'publish_time']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'error': f'Поле {field} обязательно'}), 400
        
        channel = Channel.query.filter_by(
            id=data['channel_id'], user_id=current_user.id
        ).first()
        if not channel:
            return jsonify({'error': 'Канал не найден'}), 404
        
        try:
            publish_time = datetime.fromisoformat(data['publish_time'].replace('Z', '+00:00'))
        except ValueError:
            try:
                publish_time = datetime.strptime(data['publish_time'], '%Y-%m-%dT%H:%M')
            except:
                return jsonify({'error': 'Неверный формат времени'}), 400
        
        content_id = data.get('content_id')
        if not content_id:
            new_content = GeneratedContent(
                title=f"Запланировано: {publish_time.strftime('%d.%m')}",
                text=data['text'],
                channel_id=channel.id,
                user_id=current_user.id,
                status='scheduled',
                scheduled_time=publish_time,
                platform=channel.platform
            )
            db.session.add(new_content)
            db.session.commit()
            content_id = new_content.id
        
        platform_data = {
            'text': data['text'],
            'platform': channel.platform,
            'channel_id': channel.channel_id,
            'access_token': channel.access_token,
            'publish_time': publish_time.isoformat(),
            'category': channel.category
        }
        
        if data.get('image_path'):
            platform_data['image_path'] = data['image_path']
        
        try:
            task_id = content_scheduler.add_post(**platform_data)
        except Exception as scheduler_error:
            logger.error(f"Ошибка планировщика: {scheduler_error}")
            task_id = f"local_{content_id}_{int(publish_time.timestamp())}"
        
        scheduled_post = ScheduledPost(
            content_id=content_id,
            channel_id=channel.id,
            scheduled_time=publish_time,
            task_id=task_id,
            status='scheduled',
            platform_data=json.dumps(platform_data, ensure_ascii=False)
        )
        
        db.session.add(scheduled_post)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Публикация запланирована на {publish_time.strftime("%d.%m.%Y %H:%M")}',
            'task_id': task_id,
            'content_id': content_id,
            'schedule_id': scheduled_post.id
        })
        
    except Exception as e:
        logger.error(f"Ошибка планирования: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/channels', methods=['GET', 'POST'])
@login_required
def api_channels():
    """API для управления каналами"""
    if request.method == 'GET':
        channels = Channel.query.filter_by(
            user_id=current_user.id, is_active=True
        ).all()
        return jsonify({
            'channels': [{
                'id': c.id,
                'name': c.name,
                'platform': c.platform,
                'category': c.category,
                'channel_id': c.channel_id
            } for c in channels]
        })
    
    elif request.method == 'POST':
        try:
            data = request.json if request.is_json else request.form
            
            new_channel = Channel(
                name=data['name'],
                platform=data['platform'],
                channel_id=data['channel_id'],
                category=data.get('category', 'general'),
                description=data.get('description', ''),
                access_token=data.get('access_token', ''),
                is_active=data.get('is_active', True),
                user_id=current_user.id
            )
            
            db.session.add(new_channel)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'channel_id': new_channel.id,
                'message': 'Канал успешно добавлен'
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/scheduled_posts', methods=['GET'])
@login_required
def api_scheduled_posts():
    """API для получения запланированных публикаций"""
    try:
        scheduled = ScheduledPost.query.join(Channel).filter(
            Channel.user_id == current_user.id,
            ScheduledPost.status == 'scheduled'
        ).all()
        
        posts = []
        for post in scheduled:
            posts.append({
                'id': post.id,
                'content_id': post.content_id,
                'channel_id': post.channel_id,
                'scheduled_time': post.scheduled_time.isoformat() if post.scheduled_time else None,
                'status': post.status,
                'task_id': post.task_id
            })
        
        return jsonify({'scheduled_posts': posts})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health_check():
    """Проверка здоровья системы"""
    modules_status = {
        'database': False,
        'text_generator': False,
        'image_generator': False,
        'scheduler': False,
        'authentication': current_user.is_authenticated
    }
    
    try:
        db.session.execute('SELECT 1')
        modules_status['database'] = True
    except:
        pass
    
    modules_status['text_generator'] = text_generator is not None
    modules_status['image_generator'] = image_generator is not None
    modules_status['scheduler'] = content_scheduler is not None
    
    all_healthy = all(modules_status.values())
    
    return jsonify({
        'status': 'healthy' if all_healthy else 'degraded',
        'modules': modules_status,
        'timestamp': datetime.utcnow().isoformat()
    })

# ========== ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ==========
def init_database():
    """Инициализация базы данных"""
    with app.app_context():
        db.create_all()
        
        # Создание администратора по умолчанию если нет пользователей
        if User.query.count() == 0:
            admin = User(
                username='admin',
                email='admin@snoomi.local',
                role='admin'
            )
            admin.set_password('admin123')
            db.session.add(admin)
            
            # Тестовый пользователь
            test_user = User(
                username='demo',
                email='demo@snoomi.local',
                role='user'
            )
            test_user.set_password('demo123')
            db.session.add(test_user)
            
            db.session.commit()
            logger.info("✅ Созданы пользователи по умолчанию: admin/admin123, demo/demo123")
        
        # Тестовый канал если нет каналов
        if Channel.query.count() == 0 and current_user.is_authenticated:
            test_channel = Channel(
                name='Основной канал VK',
                platform='vk',
                channel_id='club123456',
                category='матрасы',
                description='Основной канал о матрасах и здоровом сне',
                user_id=current_user.id if current_user.is_authenticated else 1
            )
            db.session.add(test_channel)
            db.session.commit()
            logger.info("Создан тестовый канал")

# Инициализируем базу данных при запуске
init_database()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)