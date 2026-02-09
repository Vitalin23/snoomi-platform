"""
Основной файл веб-приложения Snoomi Platform
"""

import sys
import os
from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import json
import logging

# Настройка путей
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'ai'))
sys.path.insert(0, str(PROJECT_ROOT / 'posting'))

# Настройка приложения
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///snoomi.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Модели
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Загрузчик пользователя
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Импорт модулей Snoomi
try:
    from ai.text_generator import TextGenerator
    from ai.image_generator import ImageGenerator
    text_gen = TextGenerator()
    img_gen = ImageGenerator()
    logger.info("✅ Модули Snoomi загружены")
except ImportError as e:
    logger.warning(f"⚠️ Модули не найдены: {e}")
    
    class TextGenerator:
        def generate_for_topic(self, topic):
            return f"Текст о {topic}"
    
    class ImageGenerator:
        def create_image_for_article(self, text, topic):
            return f"/static/placeholder.jpg"
    
    text_gen = TextGenerator()
    img_gen = ImageGenerator()

# Маршруты аутентификации
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        
        flash('Неверный логин или пароль')
    
    return render_template('login.html')
@app.route('/register', methods=['GET', 'POST'])
def register():
    """Регистрация нового пользователя"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Проверка
        if password != confirm_password:
            flash('Пароли не совпадают')
            return render_template('register.html')
        
        if len(password) < 3:
            flash('Пароль слишком короткий')
            return render_template('register.html')
        
        # Проверка существующего пользователя
        if User.query.filter_by(username=username).first():
            flash('Имя пользователя уже занято')
            return render_template('register.html')
        
        # Создание пользователя
        new_user = User(username=username)
        new_user.set_password(password)
        
        db.session.add(new_user)
        db.session.commit()
        
        flash('Регистрация успешна! Теперь войдите.')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# Основные маршруты
@app.route('/')
def index():
    return render_template('index.html')
    
@app.route('/dashboard')
@login_required
def dashboard():
    """Панель управления"""
    # Временные данные для теста
    # В реальном приложении эти данные будут из базы данных
    
    if current_user.username == 'admin':
        # Статистика для администратора
        stats = {
            'total_clients': 5,
            'active_channels': 12,
            'posts_today': 8,
            'total_users': 3
        }
    else:
        # Статистика для обычного пользователя
        stats = {
            'total_channels': 3,
            'active_channels': 2,
            'total_posts': 15,
            'total_views': 1250,
            'total_likes': 87
        }
    
    return render_template('dashboard.html', 
                         stats=stats, 
                         user=current_user)

@app.route('/content')
@login_required
def content():
    return render_template('content.html')

@app.route('/channels')
@login_required
def channels():
    return render_template('channels.html')

# API маршруты
@app.route('/api/generate', methods=['POST'])
@login_required
def generate_text():
    data = request.json
    topic = data.get('topic', '')
    
    if not topic:
        return jsonify({'error': 'Укажите тему'}), 400
    
    text = text_gen.generate_for_topic(topic)
    return jsonify({'text': text})

@app.route('/api/generate_image', methods=['POST'])
@login_required
def generate_image():
    data = request.json
    topic = data.get('topic', '')
    
    if not topic:
        return jsonify({'error': 'Укажите тему'}), 400
    
    image_path = img_gen.create_image_for_article("", topic)
    return jsonify({'image_path': image_path})
    
@app.route('/statistics')
@login_required
def statistics():
    """Страница статистики"""
    # Временные данные для теста
    return render_template('statistics.html', user=current_user)

@app.route('/billing')
@login_required
def billing():
    """Страница биллинга"""
    # Временная страница
    return render_template('billing.html', user=current_user)

# Если нужны заглушки для остальных ссылок:
@app.route('/profile')
@login_required
def profile():
    return "Страница профиля (в разработке)"

@app.route('/help')
@login_required
def help_page():
    return "Страница помощи (в разработке)"

# Создание администратора
with app.app_context():
    db.create_all()
    
    if User.query.count() == 0:
        admin = User(username='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        logger.info("✅ Создан администратор: admin/admin123")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)