"""
Основной файл веб-приложения Snoomi Platform.

Сфокусирован на админ-контуре для управления:
1) аккаунтами клиентов (web users)
2) клиентами (карточки клиентов)
3) подключениями клиентов (каналы/группы и токены)
"""

import math
import os
import sys
import logging
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash

# Настройка путей
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "ai"))
sys.path.insert(0, str(PROJECT_ROOT / "posting"))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///snoomi.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Временное in-memory хранилище планирования из UI /channels
SCHEDULED_POSTS = []


class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=True)
    telegram_id = db.Column(db.String(50), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    plan = db.Column(db.String(20), default="basic")
    status = db.Column(db.String(20), default="active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class User(db.Model, UserMixin):
    __tablename__ = "user"  # сохраняем legacy-таблицу

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default="client")
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    client = db.relationship("Client", backref=db.backref("users", lazy=True))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class ClientChannel(db.Model):
    __tablename__ = "client_channels"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    platform = db.Column(db.String(20), nullable=False)  # telegram, vk, ok, dzen
    channel_id = db.Column(db.String(120), nullable=False)
    channel_name = db.Column(db.String(150), nullable=False)
    access_token = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    client = db.relationship("Client", backref=db.backref("channels", lazy=True))


class ChannelPost(db.Model):
    __tablename__ = "channel_posts"

    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey("client_channels.id"), nullable=False)
    topic = db.Column(db.String(300), nullable=True)
    content = db.Column(db.Text, nullable=True)
    success = db.Column(db.Boolean, default=True)
    views = db.Column(db.Integer, default=0)
    likes = db.Column(db.Integer, default=0)
    shares = db.Column(db.Integer, default=0)
    comments = db.Column(db.Integer, default=0)
    published_at = db.Column(db.DateTime, default=datetime.utcnow)
    error_message = db.Column(db.Text, nullable=True)

    channel = db.relationship("ClientChannel", backref=db.backref("posts", lazy=True))


def is_admin_user(user):
    return bool(user and (getattr(user, "role", None) == "admin" or user.username == "admin"))


def admin_required(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not is_admin_user(current_user):
            abort(403)
        return func(*args, **kwargs)

    return wrapped


def _ensure_user_schema():
    """
    Легкая миграция без Alembic для legacy-таблицы user:
    добавляем колонки, которые появились после рефакторинга.
    """
    with db.engine.begin() as conn:
        table_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='user'")
        ).fetchone()
        if not table_exists:
            return

        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info('user')")).fetchall()
        }

        additions = {
            "email": "VARCHAR(120)",
            "role": "VARCHAR(20) DEFAULT 'client'",
            "client_id": "INTEGER",
            "is_active": "BOOLEAN DEFAULT 1",
        }
        for column_name, ddl in additions.items():
            if column_name not in columns:
                conn.execute(text(f'ALTER TABLE "user" ADD COLUMN {column_name} {ddl}'))

        conn.execute(
            text(
                """
                UPDATE "user"
                SET role='admin'
                WHERE username='admin' AND (role IS NULL OR role='')
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE "user"
                SET role='client'
                WHERE role IS NULL OR role=''
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE "user"
                SET is_active=1
                WHERE is_active IS NULL
                """
            )
        )


def _serialize_channel(channel, include_client_name=True):
    payload = {
        "id": channel.id,
        "client_id": channel.client_id,
        "platform": channel.platform,
        "channel_id": channel.channel_id,
        "channel_name": channel.channel_name,
        "access_token": channel.access_token,
        "is_active": bool(channel.is_active),
        "created_at": channel.created_at.isoformat() if channel.created_at else None,
    }
    if include_client_name:
        payload["client_name"] = channel.client.name if channel.client else None
    return payload


def _serialize_client(client, include_counts=False):
    payload = {
        "id": client.id,
        "name": client.name,
        "email": client.email,
        "telegram_id": client.telegram_id,
        "phone": client.phone,
        "plan": client.plan,
        "status": client.status,
        "created_at": client.created_at.isoformat() if client.created_at else None,
    }
    if include_counts:
        payload["channels_count"] = len(client.channels)
        payload["users_count"] = len(client.users)
    return payload


def _serialize_user(user):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "client_id": user.client_id,
        "client_name": user.client.name if user.client else None,
        "is_active": bool(user.is_active),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _get_accessible_channel(channel_id):
    channel = ClientChannel.query.get_or_404(channel_id)
    if is_admin_user(current_user):
        return channel
    if not current_user.client_id or channel.client_id != current_user.client_id:
        abort(403)
    return channel


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# Импорт модулей Snoomi (fallback на заглушки если модулей нет)
try:
    from ai.text_generator import TextGenerator
    from ai.image_generator import ImageGenerator

    text_gen = TextGenerator()
    img_gen = ImageGenerator()
    logger.info("✅ AI-модули загружены")
except ImportError as e:
    logger.warning(f"⚠️ AI-модули не найдены: {e}")

    class TextGenerator:
        def generate_for_topic(self, topic):
            return f"Текст о теме: {topic}"

    class ImageGenerator:
        def create_image_for_article(self, text, topic):
            return "/static/placeholder.jpg"

    text_gen = TextGenerator()
    img_gen = ImageGenerator()


# -------------------- АУТЕНТИФИКАЦИЯ --------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password) and user.is_active:
            login_user(user)
            return redirect(url_for("dashboard"))

        flash("Неверный логин или пароль", "danger")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip() or None
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username:
            flash("Введите имя пользователя", "danger")
            return render_template("register.html")
        if password != confirm_password:
            flash("Пароли не совпадают", "danger")
            return render_template("register.html")
        if len(password) < 6:
            flash("Пароль должен быть не менее 6 символов", "danger")
            return render_template("register.html")
        if User.query.filter_by(username=username).first():
            flash("Имя пользователя уже занято", "danger")
            return render_template("register.html")
        if email and User.query.filter_by(email=email).first():
            flash("Пользователь с таким email уже существует", "danger")
            return render_template("register.html")

        new_user = User(username=username, email=email, role="client", is_active=True)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash("Регистрация успешна! Теперь войдите.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# -------------------- ОСНОВНЫЕ СТРАНИЦЫ --------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
@login_required
def dashboard():
    if is_admin_user(current_user):
        stats = {
            "total_clients": Client.query.count(),
            "active_channels": ClientChannel.query.filter_by(is_active=True).count(),
            "posts_today": ChannelPost.query.filter(
                ChannelPost.published_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            ).count(),
            "total_users": User.query.filter(User.role != "admin").count(),
        }
    else:
        if current_user.client_id:
            total_channels = ClientChannel.query.filter_by(client_id=current_user.client_id).count()
            active_channels = ClientChannel.query.filter_by(
                client_id=current_user.client_id, is_active=True
            ).count()
            total_posts = (
                db.session.query(ChannelPost)
                .join(ClientChannel, ChannelPost.channel_id == ClientChannel.id)
                .filter(ClientChannel.client_id == current_user.client_id)
                .count()
            )
            totals = (
                db.session.query(
                    db.func.coalesce(db.func.sum(ChannelPost.views), 0),
                    db.func.coalesce(db.func.sum(ChannelPost.likes), 0),
                )
                .join(ClientChannel, ChannelPost.channel_id == ClientChannel.id)
                .filter(ClientChannel.client_id == current_user.client_id)
                .first()
            )
            total_views, total_likes = totals
        else:
            total_channels = active_channels = total_posts = total_views = total_likes = 0

        stats = {
            "total_channels": total_channels,
            "active_channels": active_channels,
            "total_posts": total_posts,
            "total_views": total_views or 0,
            "total_likes": total_likes or 0,
        }

    return render_template("dashboard.html", stats=stats, user=current_user)


@app.route("/channels")
@login_required
def channels():
    if is_admin_user(current_user):
        channels_data = (
            ClientChannel.query.order_by(ClientChannel.created_at.desc()).all()
        )
    elif current_user.client_id:
        channels_data = (
            ClientChannel.query.filter_by(client_id=current_user.client_id)
            .order_by(ClientChannel.created_at.desc())
            .all()
        )
    else:
        channels_data = []

    # channels.html использует legacy-поля name/category
    channels_payload = [
        {
            "id": ch.id,
            "name": ch.channel_name,
            "category": ch.platform,
            "platform": ch.platform,
            "is_active": bool(ch.is_active),
        }
        for ch in channels_data
    ]
    return render_template(
        "channels.html",
        channels=channels_payload,
        scheduled_posts=[],
        content_list=[],
    )


@app.route("/content")
@login_required
def content():
    # Legacy URL старой веб-структуры
    return redirect(url_for("channels"))


@app.route("/analytics")
@login_required
def analytics():
    # Legacy URL старой веб-структуры
    return redirect(url_for("statistics"))


@app.route("/admin/clients")
@admin_required
def admin_clients():
    return render_template("admin_clients.html")


@app.route("/statistics")
@login_required
def statistics():
    stats = {"top_clients": []}
    if is_admin_user(current_user):
        top_clients = (
            db.session.query(
                Client.name.label("client_name"),
                db.func.count(db.distinct(ClientChannel.id)).label("channels"),
                db.func.count(ChannelPost.id).label("posts"),
                db.func.coalesce(db.func.sum(ChannelPost.views), 0).label("views"),
            )
            .outerjoin(ClientChannel, Client.id == ClientChannel.client_id)
            .outerjoin(ChannelPost, ClientChannel.id == ChannelPost.channel_id)
            .group_by(Client.id)
            .order_by(db.desc("posts"))
            .limit(10)
            .all()
        )
        stats["top_clients"] = top_clients

    return render_template("statistics.html", user=current_user, time_range="30days", stats=stats)


@app.route("/billing")
@login_required
def billing():
    return render_template("billing.html", user=current_user)


@app.route("/profile")
@login_required
def profile():
    return "Страница профиля (в разработке)"


@app.route("/help")
@login_required
def help_page():
    return "Страница помощи (в разработке)"


# -------------------- API: БАЗОВЫЕ --------------------
@app.route("/api/generate", methods=["POST"])
@login_required
def generate_text():
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"error": "Укажите тему"}), 400
    return jsonify({"text": text_gen.generate_for_topic(topic)})


@app.route("/api/generate_text", methods=["POST"])
@login_required
def generate_text_legacy():
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"success": False, "error": "Укажите тему"}), 400
    generated = text_gen.generate_for_topic(topic)
    return jsonify({"success": True, "text": generated, "content_id": None})


@app.route("/api/generate_image", methods=["POST"])
@login_required
def generate_image():
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"success": False, "error": "Укажите тему"}), 400
    image_path = img_gen.create_image_for_article("", topic)
    return jsonify({"success": True, "image_path": image_path})


@app.route("/api/schedule_post", methods=["POST"])
@login_required
def schedule_post_legacy():
    data = request.get_json(silent=True) or {}
    required = ["text", "channel_id", "publish_time"]
    if not all(data.get(field) for field in required):
        return jsonify({"success": False, "error": "Не все обязательные поля заполнены"}), 400

    task_id = f"task-{int(datetime.utcnow().timestamp())}"
    scheduled_item = {
        "id": task_id,
        "topic": (data.get("text") or "Без темы")[:70],
        "channel": data.get("channel_id"),
        "scheduled_time": data.get("publish_time"),
        "status": "scheduled",
    }
    SCHEDULED_POSTS.append(scheduled_item)
    return jsonify(
        {
            "success": True,
            "task_id": task_id,
            "content_id": data.get("content_id"),
            "message": f"Публикация запланирована на {data.get('publish_time')}",
        }
    )


@app.route("/api/scheduled_posts", methods=["GET"])
@login_required
def scheduled_posts_legacy():
    return jsonify({"scheduled_posts": SCHEDULED_POSTS})


@app.route("/api/system/health")
@login_required
def api_system_health():
    if not is_admin_user(current_user):
        return jsonify({"success": False, "error": "Доступ запрещен"}), 403
    return jsonify(
        {
            "success": True,
            "database": True,
            "clients": Client.query.count(),
            "channels": ClientChannel.query.count(),
            "users": User.query.count(),
        }
    )


# -------------------- API: КАНАЛЫ/ПОДКЛЮЧЕНИЯ --------------------
@app.route("/api/clients", methods=["GET"])
@login_required
def api_clients():
    if is_admin_user(current_user):
        clients = Client.query.order_by(Client.created_at.desc()).all()
    elif current_user.client_id:
        clients = Client.query.filter_by(id=current_user.client_id).all()
    else:
        clients = []
    return jsonify([_serialize_client(c) for c in clients])


@app.route("/api/channels", methods=["POST"])
@login_required
def api_add_channel():
    data = request.get_json(silent=True) or {}
    required_fields = ["platform", "channel_id", "channel_name"]
    if not all(data.get(field) for field in required_fields):
        return jsonify({"success": False, "error": "Не все обязательные поля заполнены"}), 400

    if is_admin_user(current_user):
        client_id = data.get("client_id")
        if not client_id:
            return jsonify({"success": False, "error": "Для администратора укажите client_id"}), 400
    else:
        client_id = current_user.client_id
        if not client_id:
            return jsonify({"success": False, "error": "Ваш аккаунт не привязан к клиенту"}), 400

    client = Client.query.get(client_id)
    if not client:
        return jsonify({"success": False, "error": "Клиент не найден"}), 404

    channel = ClientChannel(
        client_id=client_id,
        platform=data["platform"].strip(),
        channel_id=data["channel_id"].strip(),
        channel_name=data["channel_name"].strip(),
        access_token=data.get("access_token"),
        is_active=bool(data.get("is_active", True)),
    )
    db.session.add(channel)
    db.session.commit()
    return jsonify({"success": True, "channel_id": channel.id})


@app.route("/api/channels/<int:channel_id>", methods=["GET"])
@login_required
def api_get_channel(channel_id):
    channel = _get_accessible_channel(channel_id)
    return jsonify(_serialize_channel(channel, include_client_name=True))


@app.route("/api/channels/<int:channel_id>", methods=["PUT"])
@login_required
def api_update_channel(channel_id):
    channel = _get_accessible_channel(channel_id)
    data = request.get_json(silent=True) or {}

    for field in ("channel_name", "access_token", "is_active"):
        if field in data:
            setattr(channel, field, data[field])

    db.session.commit()
    return jsonify({"success": True})


@app.route("/api/channels/<int:channel_id>", methods=["DELETE"])
@login_required
def api_delete_channel(channel_id):
    channel = _get_accessible_channel(channel_id)
    db.session.delete(channel)
    db.session.commit()
    return jsonify({"success": True})


@app.route("/api/channels/<int:channel_id>/test", methods=["GET"])
@login_required
def api_test_channel(channel_id):
    channel = _get_accessible_channel(channel_id)
    connected = bool(channel.access_token)
    error = None
    if not connected:
        error = "Не задан access_token для проверки подключения"

    return jsonify(
        {
            "connected": connected,
            "channel_id": channel.channel_id,
            "channel_name": channel.channel_name,
            "platform": channel.platform,
            "error": error,
        }
    )


# -------------------- API: АДМИН-КОНТУР (АККАУНТЫ + КЛИЕНТЫ + ПОДКЛЮЧЕНИЯ) --------------------
@app.route("/api/admin/clients", methods=["GET"])
@admin_required
def api_admin_get_clients():
    clients = Client.query.order_by(Client.created_at.desc()).all()
    return jsonify([_serialize_client(c, include_counts=True) for c in clients])


@app.route("/api/admin/clients", methods=["POST"])
@admin_required
def api_admin_create_client():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "Укажите имя клиента"}), 400

    client = Client(
        name=name,
        email=(data.get("email") or "").strip() or None,
        telegram_id=(data.get("telegram_id") or "").strip() or None,
        phone=(data.get("phone") or "").strip() or None,
        plan=(data.get("plan") or "basic").strip(),
        status=(data.get("status") or "active").strip(),
    )
    db.session.add(client)
    db.session.commit()
    return jsonify({"success": True, "client": _serialize_client(client, include_counts=True)})


@app.route("/api/admin/clients/<int:client_id>", methods=["PUT"])
@admin_required
def api_admin_update_client(client_id):
    client = Client.query.get_or_404(client_id)
    data = request.get_json(silent=True) or {}

    for field in ("name", "email", "telegram_id", "phone", "plan", "status"):
        if field in data:
            value = data[field]
            if isinstance(value, str):
                value = value.strip()
            setattr(client, field, value)

    db.session.commit()
    return jsonify({"success": True, "client": _serialize_client(client, include_counts=True)})


@app.route("/api/admin/users", methods=["GET"])
@admin_required
def api_admin_get_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify([_serialize_user(u) for u in users])


@app.route("/api/admin/users", methods=["POST"])
@admin_required
def api_admin_create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or "client").strip()
    email = (data.get("email") or "").strip() or None
    client_id = data.get("client_id")

    if not username or not password:
        return jsonify({"success": False, "error": "Укажите username и password"}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"success": False, "error": "Пользователь с таким username уже существует"}), 400
    if email and User.query.filter_by(email=email).first():
        return jsonify({"success": False, "error": "Пользователь с таким email уже существует"}), 400

    if role != "admin" and client_id:
        if not Client.query.get(client_id):
            return jsonify({"success": False, "error": "Клиент не найден"}), 404
    elif role == "admin":
        client_id = None

    user = User(
        username=username,
        email=email,
        role=role,
        client_id=client_id,
        is_active=bool(data.get("is_active", True)),
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({"success": True, "user": _serialize_user(user)})


@app.route("/api/admin/users/<int:user_id>", methods=["PUT"])
@admin_required
def api_admin_update_user(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}

    if "username" in data:
        username = (data["username"] or "").strip()
        if not username:
            return jsonify({"success": False, "error": "Username не может быть пустым"}), 400
        duplicate = User.query.filter(User.username == username, User.id != user.id).first()
        if duplicate:
            return jsonify({"success": False, "error": "Username уже используется"}), 400
        user.username = username

    if "email" in data:
        email = (data["email"] or "").strip() or None
        if email:
            duplicate = User.query.filter(User.email == email, User.id != user.id).first()
            if duplicate:
                return jsonify({"success": False, "error": "Email уже используется"}), 400
        user.email = email

    if "role" in data:
        role = (data["role"] or "client").strip()
        user.role = role
        if role == "admin":
            user.client_id = None

    if "client_id" in data and user.role != "admin":
        client_id = data["client_id"] or None
        if client_id and not Client.query.get(client_id):
            return jsonify({"success": False, "error": "Клиент не найден"}), 404
        user.client_id = client_id

    if "is_active" in data:
        user.is_active = bool(data["is_active"])

    new_password = data.get("password")
    if new_password:
        user.set_password(new_password)

    db.session.commit()
    return jsonify({"success": True, "user": _serialize_user(user)})


@app.route("/api/admin/connections", methods=["GET"])
@admin_required
def api_admin_get_connections():
    client_id = request.args.get("client_id", type=int)
    query = ClientChannel.query
    if client_id:
        query = query.filter_by(client_id=client_id)
    channels = query.order_by(ClientChannel.created_at.desc()).all()
    return jsonify([_serialize_channel(ch, include_client_name=True) for ch in channels])


@app.route("/api/admin/connections", methods=["POST"])
@admin_required
def api_admin_create_connection():
    data = request.get_json(silent=True) or {}
    required_fields = ["client_id", "platform", "channel_id", "channel_name"]
    if not all(data.get(field) for field in required_fields):
        return jsonify({"success": False, "error": "Не все обязательные поля заполнены"}), 400

    client = Client.query.get(data["client_id"])
    if not client:
        return jsonify({"success": False, "error": "Клиент не найден"}), 404

    channel = ClientChannel(
        client_id=data["client_id"],
        platform=(data["platform"] or "").strip(),
        channel_id=(data["channel_id"] or "").strip(),
        channel_name=(data["channel_name"] or "").strip(),
        access_token=data.get("access_token"),
        is_active=bool(data.get("is_active", True)),
    )
    db.session.add(channel)
    db.session.commit()
    return jsonify({"success": True, "connection": _serialize_channel(channel, include_client_name=True)})


@app.route("/api/admin/connections/<int:connection_id>", methods=["PUT"])
@admin_required
def api_admin_update_connection(connection_id):
    channel = ClientChannel.query.get_or_404(connection_id)
    data = request.get_json(silent=True) or {}

    for field in ("platform", "channel_id", "channel_name", "access_token", "is_active"):
        if field in data:
            setattr(channel, field, data[field])

    if "client_id" in data:
        client = Client.query.get(data["client_id"])
        if not client:
            return jsonify({"success": False, "error": "Клиент не найден"}), 404
        channel.client_id = client.id

    db.session.commit()
    return jsonify({"success": True, "connection": _serialize_channel(channel, include_client_name=True)})


@app.route("/api/admin/connections/<int:connection_id>", methods=["DELETE"])
@admin_required
def api_admin_delete_connection(connection_id):
    channel = ClientChannel.query.get_or_404(connection_id)
    db.session.delete(channel)
    db.session.commit()
    return jsonify({"success": True})


# -------------------- API: ДАШБОРД --------------------
@app.route("/api/statistics/daily")
@login_required
def api_daily_stats():
    days = request.args.get("days", 30, type=int)
    since_dt = datetime.utcnow() - timedelta(days=days - 1)

    posts_query = ChannelPost.query.join(ClientChannel, ChannelPost.channel_id == ClientChannel.id)
    if not is_admin_user(current_user):
        if not current_user.client_id:
            return jsonify({"dates": [], "posts": [], "views": [], "likes": []})
        posts_query = posts_query.filter(ClientChannel.client_id == current_user.client_id)

    rows = (
        posts_query.filter(ChannelPost.published_at >= since_dt)
        .with_entities(
            db.func.date(ChannelPost.published_at).label("day"),
            db.func.count(ChannelPost.id),
            db.func.coalesce(db.func.sum(ChannelPost.views), 0),
            db.func.coalesce(db.func.sum(ChannelPost.likes), 0),
        )
        .group_by("day")
        .all()
    )
    day_map = {str(r[0]): r for r in rows}

    dates, posts, views, likes = [], [], [], []
    for i in range(days):
        day = (since_dt + timedelta(days=i)).date().isoformat()
        dates.append(day)
        if day in day_map:
            _, cnt, vws, lks = day_map[day]
            posts.append(int(cnt or 0))
            views.append(int(vws or 0))
            likes.append(int(lks or 0))
        else:
            posts.append(0)
            views.append(0)
            likes.append(0)

    return jsonify({"dates": dates, "posts": posts, "views": views, "likes": likes})


@app.route("/api/publications/recent")
@login_required
def api_recent_publications():
    query = ChannelPost.query.join(ClientChannel, ChannelPost.channel_id == ClientChannel.id)
    if not is_admin_user(current_user):
        if not current_user.client_id:
            return jsonify([])
        query = query.filter(ClientChannel.client_id == current_user.client_id)

    posts = query.order_by(ChannelPost.published_at.desc()).limit(20).all()
    payload = []
    for post in posts:
        payload.append(
            {
                "id": post.id,
                "published_at": post.published_at.isoformat() if post.published_at else None,
                "channel_name": post.channel.channel_name if post.channel else "—",
                "topic": post.topic or "Без темы",
                "platform": post.channel.platform if post.channel else "unknown",
                "success": bool(post.success),
            }
        )
    return jsonify(payload)


@app.route("/api/topics", methods=["POST"])
@login_required
def api_topics_stub():
    # Заглушка для текущего UI: сохранение тем будет вынесено в отдельную сущность.
    return jsonify({"success": True})


@app.route("/api/publish_now", methods=["POST"])
@login_required
def api_publish_now_stub():
    return jsonify(
        {
            "success": False,
            "error": "Публикация из веб-панели пока не подключена. Используйте планировщик монетизации.",
        }
    )


@app.route("/api/billing/cancel", methods=["POST"])
@login_required
def api_billing_cancel_stub():
    return jsonify({"success": True})


def _range_to_days(range_value):
    mapping = {"7days": 7, "30days": 30, "90days": 90}
    return mapping.get(range_value, 30)


def _posts_query_for_current_user():
    query = ChannelPost.query.join(ClientChannel, ChannelPost.channel_id == ClientChannel.id)
    if is_admin_user(current_user):
        return query
    if not current_user.client_id:
        return query.filter(text("1=0"))
    return query.filter(ClientChannel.client_id == current_user.client_id)


@app.route("/api/statistics/overview")
@login_required
def api_statistics_overview():
    days = _range_to_days(request.args.get("range", "30days"))
    since_dt = datetime.utcnow() - timedelta(days=days - 1)

    query = _posts_query_for_current_user().filter(ChannelPost.published_at >= since_dt)
    posts = query.all()
    total_posts = len(posts)
    successful = sum(1 for p in posts if p.success)
    total_views = sum((p.views or 0) for p in posts)
    total_reactions = sum((p.likes or 0) + (p.shares or 0) + (p.comments or 0) for p in posts)
    success_rate = round((successful / total_posts) * 100, 1) if total_posts else 0
    avg_views = round(total_views / total_posts, 1) if total_posts else 0
    engagement_rate = round((total_reactions / total_views) * 100, 1) if total_views else 0

    daily = (
        query.with_entities(
            db.func.date(ChannelPost.published_at).label("day"),
            db.func.count(ChannelPost.id),
            db.func.coalesce(db.func.sum(ChannelPost.views), 0),
        )
        .group_by("day")
        .all()
    )
    chart_dates = [str(row[0]) for row in daily]
    chart_posts = [int(row[1] or 0) for row in daily]
    chart_views = [int(row[2] or 0) for row in daily]

    platforms = (
        query.with_entities(ClientChannel.platform, db.func.count(ChannelPost.id))
        .group_by(ClientChannel.platform)
        .all()
    )
    platforms_data = [{"platform": row[0] or "unknown", "count": int(row[1] or 0)} for row in platforms]

    return jsonify(
        {
            "total_posts": total_posts,
            "success_rate": success_rate,
            "avg_views": avg_views,
            "engagement_rate": engagement_rate,
            "chart_data": {"dates": chart_dates, "posts": chart_posts, "views": chart_views},
            "platforms_data": platforms_data,
        }
    )


@app.route("/api/statistics/top-publications")
@login_required
def api_statistics_top_publications():
    limit = request.args.get("limit", 10, type=int)
    posts = (
        _posts_query_for_current_user()
        .order_by(ChannelPost.views.desc(), ChannelPost.published_at.desc())
        .limit(limit)
        .all()
    )
    payload = []
    for post in posts:
        payload.append(
            {
                "id": post.id,
                "topic": post.topic or "Без темы",
                "channel_name": post.channel.channel_name if post.channel else "—",
                "views": int(post.views or 0),
                "likes": int(post.likes or 0),
                "shares": int(post.shares or 0),
                "comments": int(post.comments or 0),
            }
        )
    return jsonify(payload)


@app.route("/api/statistics/publications")
@login_required
def api_statistics_publications():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 25, type=int)
    platform = request.args.get("platform")
    status = request.args.get("status")
    search = request.args.get("search", "").strip().lower()

    query = _posts_query_for_current_user()
    if platform:
        query = query.filter(ClientChannel.platform == platform)
    if status == "success":
        query = query.filter(ChannelPost.success.is_(True))
    elif status == "failed":
        query = query.filter(ChannelPost.success.is_(False))
    if search:
        query = query.filter(db.func.lower(db.func.coalesce(ChannelPost.topic, "")).like(f"%{search}%"))

    total = query.count()
    total_pages = max(1, math.ceil(total / per_page)) if per_page else 1
    items = (
        query.order_by(ChannelPost.published_at.desc())
        .offset((max(page, 1) - 1) * per_page)
        .limit(per_page)
        .all()
    )
    publications = []
    for post in items:
        publications.append(
            {
                "id": post.id,
                "published_at": post.published_at.isoformat() if post.published_at else None,
                "channel_name": post.channel.channel_name if post.channel else "—",
                "topic": post.topic or "Без темы",
                "platform": post.channel.platform if post.channel else "unknown",
                "success": bool(post.success),
                "views": int(post.views or 0),
                "likes": int(post.likes or 0),
                "shares": int(post.shares or 0),
                "comments": int(post.comments or 0),
            }
        )

    return jsonify(
        {
            "publications": publications,
            "page": max(page, 1),
            "total_pages": total_pages,
            "total": total,
        }
    )


@app.route("/api/publications/<int:publication_id>")
@login_required
def api_publication_detail(publication_id):
    post = _posts_query_for_current_user().filter(ChannelPost.id == publication_id).first_or_404()
    views = int(post.views or 0)
    reactions = int(post.likes or 0) + int(post.shares or 0) + int(post.comments or 0)
    er = round((reactions / views) * 100, 2) if views else 0
    return jsonify(
        {
            "id": post.id,
            "published_at": post.published_at.isoformat() if post.published_at else None,
            "channel_name": post.channel.channel_name if post.channel else "—",
            "platform": post.channel.platform if post.channel else "unknown",
            "topic": post.topic or "Без темы",
            "content": post.content or "",
            "success": bool(post.success),
            "views": views,
            "likes": int(post.likes or 0),
            "shares": int(post.shares or 0),
            "comments": int(post.comments or 0),
            "er": er,
            "error_message": post.error_message,
        }
    )


@app.route("/api/statistics/engagement")
@login_required
def api_statistics_engagement():
    days = _range_to_days(request.args.get("range", "30days"))
    since_dt = datetime.utcnow() - timedelta(days=days - 1)
    posts = _posts_query_for_current_user().filter(ChannelPost.published_at >= since_dt).all()

    total_posts = len(posts) or 1
    avg_likes = round(sum((p.likes or 0) for p in posts) / total_posts, 1) if posts else 0
    avg_shares = round(sum((p.shares or 0) for p in posts) / total_posts, 1) if posts else 0
    avg_comments = round(sum((p.comments or 0) for p in posts) / total_posts, 1) if posts else 0

    total_views = sum((p.views or 0) for p in posts)
    total_reactions = sum((p.likes or 0) + (p.shares or 0) + (p.comments or 0) for p in posts)
    avg_ctr = round((total_reactions / total_views) * 100, 1) if total_views else 0

    return jsonify(
        {
            "avg_likes": avg_likes,
            "avg_shares": avg_shares,
            "avg_comments": avg_comments,
            "avg_ctr": avg_ctr,
            "time_data": {
                "hours": [str(i) for i in range(24)],
                "likes": [0] * 24,
                "shares": [0] * 24,
                "comments": [0] * 24,
            },
            "content_data": {"types": ["Статьи"], "er": [avg_ctr]},
        }
    )


@app.route("/api/statistics/channels")
@login_required
def api_statistics_channels():
    channels = (
        ClientChannel.query.all()
        if is_admin_user(current_user)
        else ClientChannel.query.filter_by(client_id=current_user.client_id).all()
    )
    performance = []
    ranking = []
    for channel in channels:
        posts = ChannelPost.query.filter_by(channel_id=channel.id).all()
        views = sum((p.views or 0) for p in posts)
        likes = sum((p.likes or 0) for p in posts)
        shares = sum((p.shares or 0) for p in posts)
        comments = sum((p.comments or 0) for p in posts)
        reactions = likes + shares + comments
        er = round((reactions / views) * 100, 2) if views else 0
        performance.append({"channel_name": channel.channel_name, "er": er, "views": views})
        ranking.append(
            {
                "channel_name": channel.channel_name,
                "platform": channel.platform,
                "posts": len(posts),
                "views": views,
                "likes": likes,
                "shares": shares,
                "er": er,
                "growth": 0,
            }
        )
    ranking.sort(key=lambda x: x["views"], reverse=True)
    return jsonify({"performance": performance, "ranking": ranking})


@app.route("/api/statistics/clients")
@admin_required
def api_statistics_clients():
    rows = (
        db.session.query(Client.plan, db.func.count(Client.id))
        .group_by(Client.plan)
        .all()
    )
    labels = [row[0] or "unknown" for row in rows]
    data = [int(row[1] or 0) for row in rows]
    return jsonify({"distribution": {"labels": labels, "data": data}})


@app.route("/api/statistics/export")
@login_required
def api_statistics_export():
    posts = _posts_query_for_current_user().order_by(ChannelPost.published_at.desc()).all()
    lines = ["id,published_at,channel,platform,topic,success,views,likes,shares,comments"]
    for post in posts:
        lines.append(
            ",".join(
                [
                    str(post.id),
                    (post.published_at.isoformat() if post.published_at else ""),
                    (post.channel.channel_name if post.channel else "").replace(",", " "),
                    (post.channel.platform if post.channel else ""),
                    (post.topic or "").replace(",", " "),
                    str(bool(post.success)),
                    str(int(post.views or 0)),
                    str(int(post.likes or 0)),
                    str(int(post.shares or 0)),
                    str(int(post.comments or 0)),
                ]
            )
        )
    csv_payload = "\n".join(lines)
    filename = f"snoomi_statistics_{datetime.utcnow().date().isoformat()}.csv"
    return (
        csv_payload,
        200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


with app.app_context():
    db.create_all()
    _ensure_user_schema()

    admin = User.query.filter_by(username="admin").first()
    if not admin:
        admin = User(username="admin", role="admin", is_active=True)
        admin.set_password("admin123")
        db.session.add(admin)
        db.session.commit()
        logger.info("✅ Создан администратор: admin/admin123")
    else:
        if admin.role != "admin":
            admin.role = "admin"
        if not admin.password_hash:
            admin.set_password("admin123")
        db.session.commit()


if __name__ == "__main__":
    host = os.environ.get("WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("WEB_PORT", "5000"))
    app.run(host=host, port=port, debug=True)