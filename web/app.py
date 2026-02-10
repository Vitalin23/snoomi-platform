"""
Основной файл веб-приложения Snoomi Platform.

Сфокусирован на админ-контуре для управления:
1) аккаунтами клиентов (web users)
2) клиентами (карточки клиентов)
3) подключениями клиентов (каналы/группы и токены)
"""

import math
import os
import re
import sys
import json
import uuid
import smtplib
import ssl
import logging
from collections import Counter
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps
from html import unescape
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse

import requests

from flask import (
    Flask,
    abort,
    flash,
    g,
    has_request_context,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
    got_request_exception,
)
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
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

# Настройка путей
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "ai"))
sys.path.insert(0, str(PROJECT_ROOT / "posting"))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "WEB_DATABASE_URL",
    f"sqlite:///{(PROJECT_ROOT / 'snoomi_channels.db').as_posix()}",
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
DEV_OUTBOX_DIR = LOGS_DIR / "dev_outbox"
DEV_OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
DEV_OUTBOX_INDEX_FILE = LOGS_DIR / "dev_outbox.log"

SYSTEM_LOG_FILE = LOGS_DIR / "system.log"
ERROR_LOG_FILE = LOGS_DIR / "errors.log"
CLIENT_BEHAVIOR_LOG_FILE = LOGS_DIR / "client_behavior.log"


def _build_rotating_file_handler(log_file, level):
    handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5MB per file
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    return handler


def _attach_file_handler(logger_obj, log_file, level):
    log_file_str = str(log_file)
    for handler in logger_obj.handlers:
        if isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", "") == log_file_str:
            return
    logger_obj.addHandler(_build_rotating_file_handler(log_file, level))


system_logger = logging.getLogger("snoomi.system")
system_logger.setLevel(logging.INFO)
system_logger.propagate = False
_attach_file_handler(system_logger, SYSTEM_LOG_FILE, logging.INFO)

error_logger = logging.getLogger("snoomi.error")
error_logger.setLevel(logging.ERROR)
error_logger.propagate = False
_attach_file_handler(error_logger, ERROR_LOG_FILE, logging.ERROR)

behavior_logger = logging.getLogger("snoomi.behavior")
behavior_logger.setLevel(logging.INFO)
behavior_logger.propagate = False
_attach_file_handler(behavior_logger, CLIENT_BEHAVIOR_LOG_FILE, logging.INFO)

logger.info(f"📝 Web logging enabled in: {LOGS_DIR}")

# Временное in-memory хранилище планирования из UI /channels
SCHEDULED_POSTS = []

SUPPORTED_PLATFORMS = {"telegram", "vk"}
SUPPORTED_PUBLISH_FREQUENCIES = {"daily", "every_other_day", "every_two_days"}
TRIAL_OPTIONS_DAYS = {7, 14, 30}
SUPPORT_DEFAULT_TELEGRAM_LINK = "https://t.me/snoomi_support"


class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=True)
    telegram_id = db.Column(db.String(50), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    notification_telegram = db.Column(db.String(100), nullable=True)
    plan = db.Column(db.String(20), default="basic")
    status = db.Column(db.String(20), default="active")
    trial_days = db.Column(db.Integer, default=14)
    trial_started_at = db.Column(db.DateTime, nullable=True)
    trial_ends_at = db.Column(db.DateTime, nullable=True)
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
    additional_config = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    client = db.relationship("Client", backref=db.backref("channels", lazy=True))


class ChannelSetting(db.Model):
    __tablename__ = "channel_settings"

    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey("client_channels.id"), nullable=False)
    publish_hour = db.Column(db.Integer, default=10)
    publish_frequency = db.Column(db.String(30), default="daily")
    topics = db.Column(db.Text, nullable=True)
    hashtags = db.Column(db.Text, nullable=True)
    max_posts_per_day = db.Column(db.Integer, default=1)
    is_auto_generate = db.Column(db.Boolean, default=True)
    use_ai_images = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ChannelTopic(db.Model):
    __tablename__ = "channel_topics"

    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey("client_channels.id"), nullable=False)
    topic = db.Column(db.Text, nullable=False)
    keywords = db.Column(db.Text, nullable=True)
    priority = db.Column(db.Integer, default=5)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


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


def _request_user_context():
    if not has_request_context():
        return {"user_id": None, "username": None, "client_id": None, "role": None}

    if current_user.is_authenticated:
        return {
            "user_id": current_user.id,
            "username": current_user.username,
            "client_id": current_user.client_id,
            "role": current_user.role,
        }

    return {"user_id": None, "username": "anonymous", "client_id": None, "role": None}


def _specialist_telegram_link():
    explicit_link = (os.environ.get("SPECIALIST_TELEGRAM_LINK") or "").strip()
    if explicit_link:
        return explicit_link

    tg_admin = (os.environ.get("TG_ADMIN") or "").strip()
    if tg_admin.startswith("@") and len(tg_admin) > 1:
        return f"https://t.me/{tg_admin[1:]}"
    if tg_admin and tg_admin.isdigit():
        # Работает если у клиента установлен Telegram.
        return f"tg://user?id={tg_admin}"

    return SUPPORT_DEFAULT_TELEGRAM_LINK


def _token_help_links():
    default_help = "/help"
    return {
        "telegram": (os.environ.get("TELEGRAM_TOKEN_HELP_URL") or default_help).strip(),
        "vk": (os.environ.get("VK_TOKEN_HELP_URL") or default_help).strip(),
    }


@app.context_processor
def inject_common_template_context():
    return {
        "specialist_telegram_link": _specialist_telegram_link(),
        "token_help_links": _token_help_links(),
    }


@app.before_request
def _start_request_trace():
    g.request_id = uuid.uuid4().hex[:12]
    g.request_started_at = datetime.utcnow()


@app.after_request
def _finish_request_trace(response):
    if request.path.startswith("/static/"):
        return response

    started_at = getattr(g, "request_started_at", datetime.utcnow())
    elapsed_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
    user_ctx = _request_user_context()
    base_msg = (
        f"request_id={getattr(g, 'request_id', 'n/a')} method={request.method} "
        f"path={request.path} status={response.status_code} elapsed_ms={elapsed_ms} "
        f"user_id={user_ctx['user_id']} client_id={user_ctx['client_id']} ip={request.remote_addr}"
    )

    if response.status_code >= 500:
        error_logger.error(base_msg)
    elif response.status_code >= 400:
        system_logger.warning(base_msg)
    else:
        system_logger.info(base_msg)

    return response


def _log_flask_exception(sender, exception, **extra):
    if isinstance(exception, HTTPException):
        if exception.code and exception.code < 500:
            return

    user_ctx = _request_user_context()
    error_logger.exception(
        "Unhandled exception | request_id=%s method=%s path=%s user_id=%s client_id=%s ip=%s",
        getattr(g, "request_id", "n/a"),
        request.method if has_request_context() else "n/a",
        request.path if has_request_context() else "n/a",
        user_ctx.get("user_id"),
        user_ctx.get("client_id"),
        request.remote_addr if has_request_context() else "n/a",
        exc_info=exception,
    )


got_request_exception.connect(_log_flask_exception, app)


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


def _ensure_clients_schema():
    """Миграция legacy-таблицы clients под trial и уведомления."""
    with db.engine.begin() as conn:
        table_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='clients'")
        ).fetchone()
        if not table_exists:
            return

        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info('clients')")).fetchall()
        }
        additions = {
            "notification_telegram": "VARCHAR(100)",
            "trial_days": "INTEGER DEFAULT 14",
            "trial_started_at": "TIMESTAMP",
            "trial_ends_at": "TIMESTAMP",
        }
        for column_name, ddl in additions.items():
            if column_name not in columns:
                conn.execute(text(f"ALTER TABLE clients ADD COLUMN {column_name} {ddl}"))


def _ensure_client_channels_schema():
    """Миграция таблицы client_channels для хранения расширенной конфигурации канала."""
    with db.engine.begin() as conn:
        table_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='client_channels'")
        ).fetchone()
        if not table_exists:
            return

        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info('client_channels')")).fetchall()
        }
        if "additional_config" not in columns:
            conn.execute(text("ALTER TABLE client_channels ADD COLUMN additional_config TEXT"))


def _word_tokens(text_value):
    """Универсальный токенайзер: поддерживает кириллицу и латиницу."""
    return re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", text_value or "", flags=re.UNICODE)


def _count_words(text_value):
    return len(_word_tokens(text_value))


def _extract_keywords(text_value, limit=8):
    words = [w.lower() for w in _word_tokens(text_value)]
    stop_words = {
        "и", "в", "во", "на", "по", "к", "для", "с", "со", "о", "об", "это", "как",
        "что", "при", "или", "не", "а", "но", "до", "от", "из", "под", "над", "у",
    }
    filtered = []
    seen = set()
    for word in words:
        if len(word) < 4 or word in stop_words:
            continue
        if word in seen:
            continue
        seen.add(word)
        filtered.append(word)
        if len(filtered) >= limit:
            break
    return filtered


def _strip_html(text_value):
    if not text_value:
        return ""
    text_value = re.sub(r"<br\s*/?>", "\n", text_value, flags=re.IGNORECASE)
    text_value = re.sub(r"</p>", "\n", text_value, flags=re.IGNORECASE)
    text_value = re.sub(r"<[^>]+>", " ", text_value)
    text_value = unescape(text_value)
    text_value = re.sub(r"\s+", " ", text_value).strip()
    return text_value


def _extract_telegram_username(channel_reference):
    raw_reference = (channel_reference or "").strip()
    if not raw_reference:
        return None

    if raw_reference.startswith("@"):
        candidate = raw_reference[1:]
    else:
        # Поддерживаем только публичный формат ссылки https://t.me/<username>.
        if not raw_reference.startswith("https://"):
            return None
        parsed = urlparse(raw_reference)
        if parsed.netloc.lower() not in {"t.me", "www.t.me"}:
            return None

        path_parts = [part for part in parsed.path.split("/") if part]
        if not path_parts:
            return None
        if path_parts[0] == "s":
            # Нормализуем через прямой username-ссылочный формат без /s.
            return None
        candidate = path_parts[0]

    candidate = candidate.split("?")[0].split("#")[0].strip().lstrip("@")
    candidate = candidate.replace("-", "_")
    if not re.fullmatch(r"[A-Za-z0-9_]{4,64}", candidate):
        return None
    return candidate


def _extract_vk_identifier(channel_reference):
    raw_reference = (channel_reference or "").strip()
    if not raw_reference:
        return None

    if raw_reference.startswith("-") and raw_reference[1:].isdigit():
        return raw_reference[1:]
    if raw_reference.isdigit():
        return raw_reference
    if re.fullmatch(r"(club|public)\d+", raw_reference):
        return raw_reference

    if not raw_reference.startswith(("http://", "https://")):
        if "/" not in raw_reference and "." not in raw_reference:
            return raw_reference
        raw_reference = f"https://{raw_reference}"

    parsed = urlparse(raw_reference)
    if "vk.com" not in parsed.netloc:
        return None

    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        return None

    return path_parts[0]


def _extract_telegram_posts_from_html(page_html, limit=10):
    post_blocks = re.findall(
        r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>',
        page_html,
        flags=re.DOTALL,
    )
    posts = []
    for block in post_blocks:
        clean_text = _strip_html(block)
        if _count_words(clean_text) >= 5:
            posts.append(clean_text)
        if len(posts) >= limit:
            break
    return posts


def _fetch_telegram_channel_preview(channel_reference, access_token=None):
    username = _extract_telegram_username(channel_reference)
    if not username:
        return {
            "success": False,
            "error": "Для Telegram укажите ссылку вида https://t.me/channel или ник вида @channel",
        }

    source_url = f"https://t.me/{username}"
    channel_name = f"@{username}"
    channel_description = ""
    recent_posts = []
    verification_errors = []
    verified = False

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }

    def _absorb_page_data(page_html):
        nonlocal channel_name, channel_description, recent_posts, verified
        title_match = re.search(r'<meta property="og:title" content="([^"]+)"', page_html)
        desc_match = re.search(r'<meta property="og:description" content="([^"]*)"', page_html)

        page_channel_name = _strip_html(title_match.group(1)) if title_match else ""
        page_description = _strip_html(desc_match.group(1)) if desc_match else ""
        posts_from_page = _extract_telegram_posts_from_html(page_html, limit=10)

        if page_channel_name:
            channel_name = page_channel_name
            verified = True
        if page_description:
            channel_description = page_description
            verified = True
        if posts_from_page:
            recent_posts = posts_from_page
            verified = True

    def _try_public_url(url, label):
        nonlocal verified
        try:
            response = requests.get(url, timeout=(6, 12), headers=headers)
            if response.status_code == 200:
                # Доступность публичной ссылки уже считается успешной верификацией.
                verified = True
                _absorb_page_data(response.text)
                return True
            verification_errors.append(f"{label}: HTTP {response.status_code}")
        except Exception as request_error:
            verification_errors.append(f"{label}: {request_error}")
        return False

    # Сначала проверяем канонический адрес t.me.
    primary_ok = _try_public_url(source_url, "публичная ссылка")
    # Если t.me недоступен/не прошел, пробуем технический fallback tg.me.
    if not primary_ok:
        fallback_public_url = f"https://tg.me/{username}"
        fallback_ok = _try_public_url(fallback_public_url, "fallback tg.me")
        if fallback_ok:
            system_logger.warning(
                "telegram_public_verify_fallback_used username=%s canonical=%s fallback=%s",
                username,
                source_url,
                fallback_public_url,
            )

    # После успешной публичной проверки можно дополнить данные через Bot API.
    if verified and access_token and not channel_description:
        try:
            bot_resp = requests.get(
                f"https://api.telegram.org/bot{access_token}/getChat",
                params={"chat_id": f"@{username}"},
                timeout=(6, 12),
            )
            bot_payload = bot_resp.json()
            if bot_resp.status_code == 200 and bot_payload.get("ok"):
                chat_data = bot_payload.get("result") or {}
                chat_title = (chat_data.get("title") or chat_data.get("username") or "").strip()
                chat_description = (chat_data.get("description") or "").strip()
                if chat_title:
                    channel_name = chat_title
                if chat_description:
                    channel_description = chat_description
            else:
                bot_error = bot_payload.get("description") or f"HTTP {bot_resp.status_code}"
                verification_errors.append(f"Bot API: {bot_error}")
        except Exception as e:
            verification_errors.append(f"Bot API недоступен: {e}")

    if not verified:
        error_hint = (
            "Не удалось проверить публичную ссылку Telegram-канала. "
            "Проверьте адрес в формате https://t.me/channel или @channel и повторите попытку."
        )
        if verification_errors:
            error_hint += f" Детали: {' | '.join(verification_errors[:2])}"
        return {"success": False, "error": error_hint}

    if not recent_posts:
        if _count_words(channel_description) >= 5:
            recent_posts = [channel_description]
        else:
            recent_posts = [
                (
                    f"Канал @{username}. Для более точного стилистического анализа добавьте открытый доступ "
                    "к последним публикациям канала."
                )
            ]

    if not channel_name:
        channel_name = f"@{username}"
    if not channel_description:
        channel_description = ""

    return {
        "success": True,
        "platform": "telegram",
        "channel_id": f"@{username}",
        "channel_name": channel_name,
        "source_url": source_url,
        "channel_external_description": channel_description,
        "recent_posts": recent_posts[:10],
    }

def _fetch_vk_channel_preview(channel_reference, access_token):
    vk_identifier = _extract_vk_identifier(channel_reference)
    if not vk_identifier:
        return {"success": False, "error": "Укажите корректную ссылку VK-группы или идентификатор"}

    # Верификация VK выполняется публично (без VK API).
    _ = access_token
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
    raw_reference = (channel_reference or "").strip()
    verification_errors = []

    def _build_candidate_urls():
        candidates = []

        if raw_reference.startswith(("http://", "https://")):
            parsed = urlparse(raw_reference)
            if "vk.com" in parsed.netloc.lower():
                path_parts = [part for part in parsed.path.split("/") if part]
                if path_parts:
                    candidates.append(f"https://vk.com/{path_parts[0]}")

        if re.fullmatch(r"(club|public|event)\d+", vk_identifier):
            candidates.append(f"https://vk.com/{vk_identifier}")
        elif vk_identifier.isdigit():
            candidates.append(f"https://vk.com/club{vk_identifier}")
            candidates.append(f"https://vk.com/public{vk_identifier}")
        else:
            candidates.append(f"https://vk.com/{vk_identifier}")

        unique_candidates = []
        seen = set()
        for candidate_url in candidates:
            normalized = candidate_url.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_candidates.append(normalized)
        return unique_candidates

    def _normalize_vk_source_url(url_value):
        parsed = urlparse(url_value)
        if "vk.com" not in parsed.netloc.lower():
            return ""
        path_parts = [part for part in parsed.path.split("/") if part]
        if not path_parts:
            return "https://vk.com"
        return f"https://vk.com/{path_parts[0]}"

    def _is_vk_missing_page(page_html, final_url):
        page_text = (page_html or "").lower()
        final_link = (final_url or "").lower()
        markers = (
            "такой страницы нет",
            "страница удалена",
            "page not found",
            "error 404",
            "cannot find page",
        )
        if any(marker in page_text for marker in markers):
            return True
        if "/404.php" in final_link:
            return True
        return False

    def _extract_vk_page_title(page_html):
        og_title_match = re.search(r'<meta property="og:title" content="([^"]+)"', page_html)
        title = _strip_html(og_title_match.group(1)) if og_title_match else ""
        if not title:
            title_match = re.search(r"<title>(.*?)</title>", page_html, flags=re.IGNORECASE | re.DOTALL)
            title = _strip_html(title_match.group(1)) if title_match else ""
        if title:
            title = re.sub(r"\s*\|\s*(вконтакте|vk)\s*$", "", title, flags=re.IGNORECASE).strip()
        return title

    candidate_urls = _build_candidate_urls()
    if not candidate_urls:
        return {"success": False, "error": "Не удалось сформировать публичный адрес VK для проверки"}

    for candidate_url in candidate_urls:
        try:
            response = requests.get(candidate_url, timeout=(6, 12), headers=headers, allow_redirects=True)
        except Exception as e:
            verification_errors.append(f"{candidate_url}: {e}")
            continue

        if response.status_code != 200:
            verification_errors.append(f"{candidate_url}: HTTP {response.status_code}")
            continue

        page_html = response.text or ""
        source_url = _normalize_vk_source_url(response.url or candidate_url) or candidate_url
        if _is_vk_missing_page(page_html, source_url):
            verification_errors.append(f"{candidate_url}: страница не найдена")
            continue

        channel_name = _extract_vk_page_title(page_html) or vk_identifier
        desc_match = re.search(r'<meta property="og:description" content="([^"]*)"', page_html)
        channel_description = _strip_html(desc_match.group(1)) if desc_match else ""

        source_slug = source_url.rstrip("/").split("/")[-1]
        numeric_source_match = re.fullmatch(r"(club|public|event)(\d+)", source_slug or "")
        if numeric_source_match:
            platform_channel_id = f"-{numeric_source_match.group(2)}"
        elif vk_identifier.startswith("-") and vk_identifier[1:].isdigit():
            platform_channel_id = vk_identifier
        elif vk_identifier.isdigit():
            platform_channel_id = f"-{vk_identifier}"
        else:
            platform_channel_id = source_slug or vk_identifier

        recent_posts = []
        if _count_words(channel_description) >= 5:
            recent_posts.append(channel_description)
        else:
            recent_posts.append(
                f"Публичная страница VK «{channel_name}». Для более точного анализа добавьте описание и открытые посты."
            )

        return {
            "success": True,
            "platform": "vk",
            "channel_id": platform_channel_id,
            "channel_name": channel_name,
            "source_url": source_url,
            "channel_external_description": channel_description,
            "recent_posts": recent_posts[:10],
        }

    error_hint = "Не удалось проверить публичную ссылку VK-сообщества. Проверьте адрес и повторите попытку."
    if verification_errors:
        error_hint += f" Детали: {' | '.join(verification_errors[:2])}"
    return {"success": False, "error": error_hint}


def _heuristic_style_profile(channel_name, platform, channel_description, recent_posts):
    posts = [p.strip() for p in (recent_posts or []) if p and p.strip()]
    joined_text = " ".join([channel_description or "", *posts]).strip()
    words = [w.lower() for w in _word_tokens(joined_text) if len(w) >= 4]
    top_keywords = [word for word, _ in Counter(words).most_common(8)]

    avg_post_length = 0
    if posts:
        avg_post_length = int(sum(len(p) for p in posts) / max(len(posts), 1))

    exclamation_count = joined_text.count("!")
    question_count = joined_text.count("?")
    emoji_count = len(re.findall(r"[\U0001F300-\U0001FAFF]", joined_text))

    tone = "экспертный и спокойный"
    if exclamation_count > question_count and exclamation_count >= 3:
        tone = "энергичный и вовлекающий"
    elif question_count >= 3:
        tone = "диалоговый и вовлекающий"
    elif emoji_count >= 3:
        tone = "дружелюбный и эмоциональный"

    summary = (
        f"Канал «{channel_name}» ({platform}) ведет коммуникацию в тоне «{tone}». "
        f"Средняя длина поста около {max(avg_post_length, 180)} символов. "
        f"Ключевые слова: {', '.join(top_keywords[:5]) if top_keywords else 'тематика канала'}."
    )

    return {
        "summary": summary,
        "tone": tone,
        "audience": "подписчики канала и заинтересованная целевая аудитория",
        "keywords": top_keywords,
        "dos": [
            "Сохранять структуру коротких абзацев и практический фокус",
            "Добавлять конкретику и действия для читателя",
            "Поддерживать тон и лексику, привычные аудитории канала",
        ],
        "donts": [
            "Не уходить в слишком формальный канцелярит",
            "Не делать длинные перегруженные абзацы",
            "Не менять резко голос бренда между публикациями",
        ],
        "recent_posts_count": len(posts),
    }


def _extract_json_object(raw_text):
    if not raw_text:
        return None
    match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _ai_style_profile(channel_name, platform, channel_description, recent_posts):
    try:
        from config import Config
    except Exception:
        return None

    if not (getattr(Config, "YANDEX_API_KEY", "") and getattr(Config, "YANDEX_FOLDER_ID", "")):
        return None

    posts_excerpt = []
    for idx, post in enumerate((recent_posts or [])[:10], start=1):
        posts_excerpt.append(f"{idx}. {post[:450]}")
    posts_text = "\n".join(posts_excerpt) or "Посты не обнаружены."

    prompt = f"""
Проанализируй стиль канала и верни СТРОГО JSON (без markdown и комментариев) с полями:
summary (string), tone (string), audience (string), keywords (array of strings),
dos (array of strings), donts (array of strings).

Платформа: {platform}
Название: {channel_name}
Описание канала: {channel_description or "нет описания"}
Последние 10 постов:
{posts_text}
"""

    payload = {
        "modelUri": f"gpt://{Config.YANDEX_FOLDER_ID}/yandexgpt",
        "completionOptions": {
            "stream": False,
            "temperature": 0.2,
            "maxTokens": 1500,
        },
        "messages": [
            {
                "role": "system",
                "text": "Ты редактор контента. Всегда отвечай только валидным JSON без дополнительного текста.",
            },
            {"role": "user", "text": prompt},
        ],
    }
    headers = {
        "Authorization": f"Api-Key {Config.YANDEX_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            headers=headers,
            json=payload,
            timeout=35,
        )
        if response.status_code != 200:
            return None
        text_result = (
            response.json()
            .get("result", {})
            .get("alternatives", [{}])[0]
            .get("message", {})
            .get("text", "")
        )
        parsed = _extract_json_object(text_result)
        if not isinstance(parsed, dict):
            return None

        return {
            "summary": str(parsed.get("summary", "")).strip(),
            "tone": str(parsed.get("tone", "")).strip(),
            "audience": str(parsed.get("audience", "")).strip(),
            "keywords": [str(x).strip() for x in (parsed.get("keywords") or []) if str(x).strip()][:10],
            "dos": [str(x).strip() for x in (parsed.get("dos") or []) if str(x).strip()][:6],
            "donts": [str(x).strip() for x in (parsed.get("donts") or []) if str(x).strip()][:6],
        }
    except Exception:
        return None


def _compose_auto_channel_description(channel_name, platform, channel_external_description, style_profile):
    platform_label = "Telegram" if platform == "telegram" else "VK"
    keyword_text = ", ".join((style_profile.get("keywords") or [])[:5])
    if not keyword_text:
        keyword_text = "экспертный контент, полезные рекомендации, регулярные публикации"

    base_description = (
        f"Канал «{channel_name}» на платформе {platform_label}. "
        f"Основная тематика и стиль: {style_profile.get('summary') or 'практические материалы для аудитории канала'}. "
        f"Ключевые направления контента: {keyword_text}. "
        f"Важно сохранять узнаваемый тон коммуникации и публиковать структурированные материалы с понятной пользой для подписчиков."
    )

    if channel_external_description:
        base_description += f" Дополнительно из описания канала: {channel_external_description[:300]}."

    if _count_words(base_description) < 20:
        base_description += (
            " Канал ориентирован на стабильную вовлеченность, прикладные советы, понятную структуру текстов "
            "и аккуратную адаптацию контента под ожидания аудитории."
        )
    return base_description


def _verify_channel_source(platform, channel_reference, access_token):
    if platform == "telegram":
        return _fetch_telegram_channel_preview(channel_reference, access_token=access_token)
    if platform == "vk":
        return _fetch_vk_channel_preview(channel_reference, access_token)
    return {"success": False, "error": "Поддерживаются только Telegram и VK"}


def _build_channel_intelligence(platform, channel_reference, access_token, run_ai_analysis=True):
    verification = _verify_channel_source(platform, channel_reference, access_token)
    if not verification.get("success"):
        return verification

    channel_name = verification.get("channel_name") or "Канал"
    channel_external_description = verification.get("channel_external_description") or ""
    recent_posts = verification.get("recent_posts") or []

    style_profile = None
    if run_ai_analysis:
        style_profile = _ai_style_profile(
            channel_name=channel_name,
            platform=platform,
            channel_description=channel_external_description,
            recent_posts=recent_posts,
        )
    if not style_profile:
        style_profile = _heuristic_style_profile(
            channel_name=channel_name,
            platform=platform,
            channel_description=channel_external_description,
            recent_posts=recent_posts,
        )

    verification["style_profile"] = style_profile
    verification["style_summary"] = style_profile.get("summary", "")
    verification["auto_description"] = _compose_auto_channel_description(
        channel_name=channel_name,
        platform=platform,
        channel_external_description=channel_external_description,
        style_profile=style_profile,
    )
    verification["recent_posts"] = recent_posts[:10]
    verification["verified_at"] = datetime.utcnow().isoformat()
    return verification


def _build_login_url_for_email():
    public_base_url = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if public_base_url:
        if not public_base_url.startswith(("http://", "https://")):
            public_base_url = f"http://{public_base_url}"
        return f"{public_base_url}/login"

    web_host = (os.environ.get("WEB_HOST") or "localhost").strip()
    if web_host in {"0.0.0.0", "::", "[::]"}:
        web_host = "localhost"
    web_port_raw = (os.environ.get("WEB_PORT") or "5000").strip()
    try:
        web_port = int(web_port_raw)
    except (TypeError, ValueError):
        web_port = 5000
    return f"http://{web_host}:{web_port}/login"


def _save_email_to_local_outbox(message, email_to):
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    safe_to = re.sub(r"[^A-Za-z0-9._-]+", "_", email_to or "unknown")[:80] or "unknown"
    eml_path = DEV_OUTBOX_DIR / f"{timestamp}_{safe_to}.eml"
    eml_path.write_bytes(message.as_bytes())

    with DEV_OUTBOX_INDEX_FILE.open("a", encoding="utf-8") as outbox_index:
        outbox_index.write(
            f"{datetime.utcnow().isoformat()} | to={email_to} | subject={message.get('Subject', '')} | file={eml_path}\n"
        )
    return str(eml_path)


def _send_registration_email(email_to, username, password, client_name, trial_days):
    if not email_to:
        return False, "email_empty"

    email_mode = (os.environ.get("EMAIL_DELIVERY_MODE") or "auto").strip().lower()
    if email_mode not in {"auto", "smtp", "stub"}:
        email_mode = "auto"

    smtp_host = (os.environ.get("SMTP_HOST") or "").strip()
    smtp_port_raw = (os.environ.get("SMTP_PORT") or "587").strip()
    try:
        smtp_port = int(smtp_port_raw)
    except (TypeError, ValueError):
        smtp_port = 587
    smtp_user = (os.environ.get("SMTP_USER") or "").strip()
    smtp_password = (os.environ.get("SMTP_PASSWORD") or "").strip()
    smtp_from = (os.environ.get("SMTP_FROM_EMAIL") or smtp_user or "noreply@snoomi.local").strip()
    smtp_from_name = (os.environ.get("SMTP_FROM_NAME") or "Snoomi Platform").strip()
    smtp_use_ssl = (os.environ.get("SMTP_USE_SSL", "False").strip().lower() == "true")
    smtp_use_tls = (os.environ.get("SMTP_USE_TLS", "True").strip().lower() == "true")

    subject = "Добро пожаловать в Snoomi Platform"
    login_url = _build_login_url_for_email()
    support_link = _specialist_telegram_link()

    plain_body = f"""
Здравствуйте!

Добро пожаловать в Snoomi Platform — сервис автопостинга и AI-генерации контента для Telegram и VK.

Ваши регистрационные данные:
Логин: {username}
Пароль: {password}
Клиент: {client_name}
Тестовый период: {trial_days} дней

Вход в систему:
{login_url}

Если нужна помощь с настройкой — свяжитесь со специалистом:
{support_link}

С уважением,
Команда Snoomi Platform
""".strip()

    html_body = f"""
<html>
  <body>
    <h2>Добро пожаловать в Snoomi Platform</h2>
    <p><b>Snoomi Platform</b> — сервис автопостинга и AI-генерации контента для Telegram и VK.</p>
    <p>Ваши регистрационные данные:</p>
    <ul>
      <li><b>Логин:</b> {username}</li>
      <li><b>Пароль:</b> {password}</li>
      <li><b>Клиент:</b> {client_name}</li>
      <li><b>Тестовый период:</b> {trial_days} дней</li>
    </ul>
    <p><a href="{login_url}">Войти в систему</a></p>
    <p>Нужна помощь с настройкой? <a href="{support_link}">Вызов специалиста в Telegram</a></p>
    <hr>
    <small>С уважением, команда Snoomi Platform</small>
  </body>
</html>
""".strip()

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{smtp_from_name} <{smtp_from}>"
    message["To"] = email_to
    message.set_content(plain_body)
    message.add_alternative(html_body, subtype="html")

    use_local_stub = email_mode == "stub" or (email_mode == "auto" and not smtp_host)
    if use_local_stub:
        try:
            eml_path = _save_email_to_local_outbox(message, email_to)
            system_logger.info(
                "Registration email stored in local outbox for %s: %s",
                email_to,
                eml_path,
            )
            return True, f"stub_saved:{eml_path}"
        except Exception as e:
            error_logger.error("Registration email stub save failed for %s: %s", email_to, e)
            return False, f"stub_error:{e}"

    if not smtp_host:
        system_logger.warning("SMTP is not configured, registration email skipped")
        return False, "smtp_not_configured"

    ssl_context = ssl.create_default_context()
    try:
        if smtp_use_ssl:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20, context=ssl_context) as smtp:
                if smtp_user and smtp_password:
                    smtp.login(smtp_user, smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
                if smtp_use_tls:
                    smtp.starttls(context=ssl_context)
                if smtp_user and smtp_password:
                    smtp.login(smtp_user, smtp_password)
                smtp.send_message(message)
        return True, "sent"
    except Exception as e:
        error_logger.error("Registration email send failed for %s: %s", email_to, e)
        return False, str(e)


def _frequency_to_human(freq):
    mapping = {
        "daily": "каждый день",
        "every_other_day": "через день",
        "every_two_days": "через 2 дня",
    }
    return mapping.get(freq, freq or "daily")


def _normalize_frequency(freq):
    if not freq:
        return "daily"
    normalized = str(freq).strip().lower()
    aliases = {
        "через день": "every_other_day",
        "через 2 дня": "every_two_days",
        "every_2_days": "every_two_days",
        "every_3_days": "every_two_days",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in SUPPORTED_PUBLISH_FREQUENCIES:
        return None
    return normalized


def _channel_extra_config(channel):
    if not channel.additional_config:
        return {}
    try:
        return json.loads(channel.additional_config)
    except Exception:
        return {}


def _is_trial_active(client):
    if not client:
        return False
    if client.plan != "trial":
        return True
    if not client.trial_ends_at:
        return True
    return datetime.utcnow() <= client.trial_ends_at


def _ensure_channel_runtime_setup(channel_id, channel_description, publish_frequency, publish_hour=10):
    """Создает/обновляет настройки и базовые темы канала для планировщика."""
    if not channel_description or _count_words(channel_description) < 20:
        channel_description = (
            "Канал клиента для автопостинга с регулярными экспертными публикациями, ориентированными "
            "на практическую пользу аудитории, вовлечение подписчиков и развитие бренда клиента."
        )

    publish_frequency = _normalize_frequency(publish_frequency) or "daily"
    try:
        publish_hour = int(publish_hour)
    except (TypeError, ValueError):
        publish_hour = 10
    publish_hour = min(max(publish_hour, 0), 23)

    settings = ChannelSetting.query.filter_by(channel_id=channel_id).first()
    topics_json = json.dumps([channel_description], ensure_ascii=False)
    hashtags_json = json.dumps([], ensure_ascii=False)
    if not settings:
        settings = ChannelSetting(
            channel_id=channel_id,
            publish_hour=publish_hour,
            publish_frequency=publish_frequency,
            topics=topics_json,
            hashtags=hashtags_json,
            max_posts_per_day=1,
            is_auto_generate=True,
            use_ai_images=True,
        )
        db.session.add(settings)
    else:
        settings.publish_hour = publish_hour
        settings.publish_frequency = publish_frequency
        settings.topics = topics_json
        if not settings.hashtags:
            settings.hashtags = hashtags_json

    active_topics = ChannelTopic.query.filter_by(channel_id=channel_id, is_active=True).all()
    if not active_topics:
        words = _word_tokens(channel_description)
        short_topic = " ".join(words[:12]).strip()
        if not short_topic:
            short_topic = "Контент по тематике канала"

        topic = ChannelTopic(
            channel_id=channel_id,
            topic=short_topic,
            keywords=json.dumps(_extract_keywords(channel_description), ensure_ascii=False),
            priority=8,
            is_active=True,
        )
        db.session.add(topic)


def _serialize_channel(channel, include_client_name=True):
    extra = _channel_extra_config(channel)
    settings = ChannelSetting.query.filter_by(channel_id=channel.id).first()
    publish_frequency = (
        settings.publish_frequency
        if settings and settings.publish_frequency
        else extra.get("publish_frequency", "daily")
    )
    publish_hour = settings.publish_hour if settings and settings.publish_hour is not None else 10

    payload = {
        "id": channel.id,
        "client_id": channel.client_id,
        "platform": channel.platform,
        "channel_id": channel.channel_id,
        "channel_name": channel.channel_name,
        "access_token": channel.access_token,
        "is_active": bool(channel.is_active),
        "channel_description": extra.get("channel_description", ""),
        "channel_source_url": extra.get("source_url"),
        "style_summary": (extra.get("style_profile") or {}).get("summary", ""),
        "publish_frequency": publish_frequency,
        "publish_frequency_label": _frequency_to_human(publish_frequency),
        "publish_hour": publish_hour,
        "created_at": channel.created_at.isoformat() if channel.created_at else None,
    }
    if include_client_name:
        payload["client_name"] = channel.client.name if channel.client else None
    return payload


def _serialize_client(client, include_counts=False):
    trial_active = _is_trial_active(client)
    payload = {
        "id": client.id,
        "name": client.name,
        "email": client.email,
        "telegram_id": client.telegram_id,
        "notification_telegram": client.notification_telegram,
        "phone": client.phone,
        "plan": client.plan,
        "status": client.status,
        "trial_days": client.trial_days,
        "trial_started_at": client.trial_started_at.isoformat() if client.trial_started_at else None,
        "trial_ends_at": client.trial_ends_at.isoformat() if client.trial_ends_at else None,
        "trial_active": trial_active,
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


def _normalize_phrase_list(raw_items, limit=12):
    phrases = []
    seen = set()
    for item in raw_items or []:
        if isinstance(item, str):
            candidate = item
        elif isinstance(item, dict):
            candidate = (
                item.get("phrase")
                or item.get("title")
                or item.get("text")
                or item.get("keyword")
                or ""
            )
        else:
            candidate = ""
        candidate = re.sub(r"^[\-\d\)\.\s]+", "", str(candidate or "").strip())
        candidate = re.sub(r"\s+", " ", candidate).strip(" \n\t-.,;")
        if not candidate:
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        phrases.append(candidate)
        if len(phrases) >= limit:
            break
    return phrases


def _normalize_actual_questions(raw_items, limit=15):
    normalized = []
    seen = set()
    for item in raw_items or []:
        if isinstance(item, str):
            question = item.strip()
            intent = ""
            source_hint = ""
        elif isinstance(item, dict):
            question = str(item.get("question") or item.get("q") or item.get("title") or "").strip()
            intent = str(item.get("intent") or "").strip()
            source_hint = str(item.get("source_hint") or item.get("source") or "").strip()
        else:
            continue

        if not question:
            continue
        if not question.endswith("?"):
            question = question.rstrip(".!") + "?"

        key = question.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "question": question,
                "intent": intent,
                "source_hint": source_hint,
            }
        )
        if len(normalized) >= limit:
            break
    return normalized


def _normalize_topic_plan_items(raw_items, desired_count, semantic_core):
    topics = []
    seen = set()
    semantic_core = semantic_core or []
    for idx, item in enumerate(raw_items or []):
        if isinstance(item, str):
            title = item.strip()
            why = ""
            keyword = semantic_core[idx % len(semantic_core)] if semantic_core else ""
            questions = []
        elif isinstance(item, dict):
            title = str(item.get("title") or item.get("topic") or "").strip()
            why = str(item.get("why") or item.get("rationale") or "").strip()
            keyword = str(item.get("keyword") or item.get("cluster") or "").strip()
            questions = _normalize_phrase_list(item.get("questions") or item.get("audience_questions") or [], limit=4)
        else:
            continue

        if not title:
            continue
        dedupe_key = title.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        if not keyword and semantic_core:
            keyword = semantic_core[idx % len(semantic_core)]

        topics.append(
            {
                "id": len(topics) + 1,
                "title": title,
                "keyword": keyword,
                "questions": questions,
                "rationale": why,
            }
        )
        if len(topics) >= desired_count:
            break
    return topics


def _fetch_public_web_question_hints(query_text, limit=12):
    query_text = (query_text or "").strip()
    if not query_text:
        return []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
    try:
        response = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query_text, "kl": "ru-ru"},
            timeout=(6, 12),
            headers=headers,
        )
    except Exception:
        return []

    if response.status_code != 200:
        return []

    html_text = response.text or ""
    snippet_matches = re.findall(
        r'result__snippet[^>]*>(.*?)</(?:a|div)>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    title_matches = re.findall(
        r'result__a[^>]*>(.*?)</a>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    raw_questions = []
    for block in [*title_matches, *snippet_matches]:
        clean_text = _strip_html(block)
        if not clean_text:
            continue
        question_fragments = re.findall(r"[^?]{8,180}\?", clean_text)
        for fragment in question_fragments:
            fragment = re.sub(r"\s+", " ", fragment).strip()
            if fragment:
                raw_questions.append(fragment)

    return _normalize_actual_questions(raw_questions, limit=limit)


def _collect_top_web_questions(query_candidates, limit=5):
    merged_questions = []
    normalized_queries = _normalize_phrase_list(query_candidates, limit=12)
    current_year = datetime.utcnow().year

    for base_query in normalized_queries:
        # Приоритет актуальности: сначала запрос с текущим годом.
        query_variants = [
            f"{base_query} {current_year} вопросы аудитории",
            f"{base_query} актуальные вопросы аудитории",
            base_query,
        ]
        for query in query_variants:
            hints = _fetch_public_web_question_hints(query, limit=max(limit * 2, 10))
            merged_questions = _normalize_actual_questions(
                [*merged_questions, *hints],
                limit=limit,
            )
            if len(merged_questions) >= limit:
                return merged_questions[:limit]
    return merged_questions[:limit]


def _ai_topic_plan_with_web_search(
    channel_name,
    platform,
    channel_client_description,
    channel_external_description,
    recent_posts,
    style_summary,
    focus_text,
    desired_count,
):
    try:
        from config import Config
    except Exception:
        return None

    if not (getattr(Config, "YANDEX_API_KEY", "") and getattr(Config, "YANDEX_FOLDER_ID", "")):
        return None

    posts_block = []
    for idx, post in enumerate((recent_posts or [])[:10], start=1):
        post_text = str(post).strip()
        if post_text:
            posts_block.append(f"{idx}. {post_text[:450]}")
    posts_text = "\n".join(posts_block) if posts_block else "Посты недоступны."
    current_year = datetime.utcnow().year

    prompt = f"""
Сформируй контент-план для канала. Работай как стратег-контентолог.

ВАЖНО:
1) Сначала выдели ЕДИНУЮ тематику канала (ниша, ЦА, задачи), не распадай ее на отдельные несвязанные ключи.
2) Используй web search, чтобы найти актуальные вопросы аудитории по этой тематике.
3) Верни результат СТРОГО в JSON (без markdown и комментариев).
4) Приоритет по данным: актуальные материалы {current_year} года и последних 12 месяцев.
5) Устаревшие примеры (2024 и ранее) включай только если это базовая справка, а не тренд.

Формат JSON:
{{
  "semantic_core": ["фраза 1", "фраза 2"],
  "audience_profile": "краткое описание аудитории",
  "search_queries": ["поисковый запрос 1", "поисковый запрос 2"],
  "actual_questions": [
    {{"question":"...", "intent":"...", "source_hint":"..."}}
  ],
  "topic_plan": [
    {{
      "title":"...",
      "why":"почему это важно аудитории",
      "keyword":"кластер/вектор темы",
      "questions":["вопрос 1","вопрос 2"]
    }}
  ]
}}

Количество тем в topic_plan: ровно {desired_count}

КОНТЕКСТ КАНАЛА:
Платформа: {platform}
Название: {channel_name}
Описание от клиента: {channel_client_description or "нет"}
Публичное описание канала: {channel_external_description or "нет"}
Сводка стиля: {style_summary or "нет"}
Фокус пользователя на период: {focus_text or "не задан"}
Последние посты:
{posts_text}
""".strip()

    payload = {
        "modelUri": f"gpt://{Config.YANDEX_FOLDER_ID}/yandexgpt",
        "completionOptions": {
            "stream": False,
            "temperature": 0.2,
            "maxTokens": 3500,
            "useWebSearch": True,
            "searchRegion": "ru",
        },
        "messages": [
            {
                "role": "system",
                "text": (
                    "Ты senior контент-стратег. Отвечай только JSON, "
                    "без markdown, пояснений и служебного текста."
                ),
            },
            {"role": "user", "text": prompt},
        ],
    }
    headers = {
        "Authorization": f"Api-Key {Config.YANDEX_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            headers=headers,
            json=payload,
            timeout=70,
        )
        if response.status_code != 200:
            return None
        raw_text = (
            response.json()
            .get("result", {})
            .get("alternatives", [{}])[0]
            .get("message", {})
            .get("text", "")
        )
    except Exception:
        return None

    parsed = _extract_json_object(raw_text)
    if not isinstance(parsed, dict):
        return None

    semantic_core = _normalize_phrase_list(
        parsed.get("semantic_core") or parsed.get("semantic_vectors") or [],
        limit=12,
    )
    audience_profile = str(parsed.get("audience_profile") or "").strip()
    search_queries = _normalize_phrase_list(parsed.get("search_queries") or [], limit=10)
    actual_questions = _normalize_actual_questions(
        parsed.get("actual_questions") or parsed.get("audience_questions") or [],
        limit=max(desired_count + 4, 10),
    )
    topic_items = _normalize_topic_plan_items(
        parsed.get("topic_plan") or parsed.get("topics") or [],
        desired_count=desired_count,
        semantic_core=semantic_core,
    )

    if not topic_items:
        return None

    return {
        "semantic_core": semantic_core,
        "audience_profile": audience_profile,
        "search_queries": search_queries,
        "actual_questions": actual_questions,
        "topics": topic_items,
    }


def _build_topic_planner_payload(channel, focus_text="", desired_count=8):
    """Готовит идеи тем для шага 2 (настройка постинга)."""
    desired_count = min(max(int(desired_count or 8), 3), 20)
    focus_text = (focus_text or "").strip()
    extra = _channel_extra_config(channel)
    current_year = datetime.utcnow().year

    channel_client_description = (extra.get("channel_description") or "").strip()
    channel_external_description = (extra.get("channel_external_description") or "").strip()
    recent_posts_raw = extra.get("recent_posts_preview") or []
    if not isinstance(recent_posts_raw, list):
        recent_posts_raw = []
    recent_posts = [str(item).strip() for item in recent_posts_raw if str(item).strip()][:10]
    if not recent_posts and channel_external_description:
        recent_posts = [channel_external_description]

    style_profile = _ai_style_profile(
        channel_name=channel.channel_name,
        platform=channel.platform,
        channel_description=channel_external_description or channel_client_description,
        recent_posts=recent_posts,
    )
    if not style_profile:
        style_profile = _heuristic_style_profile(
            channel_name=channel.channel_name,
            platform=channel.platform,
            channel_description=channel_external_description or channel_client_description,
            recent_posts=recent_posts,
        )

    style_summary = (style_profile.get("summary") or "").strip()
    semantic_core = []
    actual_questions = []
    search_queries = []
    topic_items = []
    source_mode = "heuristic_fallback"

    ai_plan = _ai_topic_plan_with_web_search(
        channel_name=channel.channel_name,
        platform=channel.platform,
        channel_client_description=channel_client_description,
        channel_external_description=channel_external_description,
        recent_posts=recent_posts,
        style_summary=style_summary,
        focus_text=focus_text,
        desired_count=desired_count,
    )

    if ai_plan:
        source_mode = "yandexgpt_web_search"
        semantic_core = ai_plan.get("semantic_core") or []
        search_queries = ai_plan.get("search_queries") or []
        topic_items = ai_plan.get("topics") or []

        query_candidates = [
            *search_queries,
            *semantic_core,
            f"{channel.channel_name} {focus_text} {current_year}".strip(),
            f"{channel.channel_name} {current_year}".strip(),
            channel.channel_name,
        ]
        actual_questions = _collect_top_web_questions(query_candidates, limit=5)
    else:
        semantic_seed_text = " ".join(
            part
            for part in [
                focus_text,
                channel_client_description,
                channel_external_description,
                style_summary,
            ]
            if part
        )
        semantic_core = _normalize_phrase_list(
            [s.strip() for s in re.split(r"[.\n;:]+", semantic_seed_text) if _count_words(s) >= 3],
            limit=8,
        )
        if not semantic_core:
            fallback_keywords = _extract_keywords(
                f"{channel.channel_name} {semantic_seed_text} {' '.join(recent_posts)}",
                limit=8,
            )
            if fallback_keywords:
                semantic_core = [", ".join(fallback_keywords[:4])]
            else:
                semantic_core = [f"Контент по тематике канала «{channel.channel_name}»"]

        query_keywords = _extract_keywords(
            f"{channel.channel_name} {semantic_seed_text}",
            limit=7,
        )
        query_text = " ".join(query_keywords[:5]) or channel.channel_name
        search_queries = [
            f"{query_text} {current_year}",
            f"{query_text} актуальные вопросы аудитории",
            query_text,
        ]
        actual_questions = _collect_top_web_questions(
            [*search_queries, *semantic_core, channel.channel_name],
            limit=5,
        )

        for idx in range(desired_count):
            semantic_vector = semantic_core[idx % len(semantic_core)]
            base_question = actual_questions[idx % len(actual_questions)] if actual_questions else {}
            question_text = (base_question.get("question") or "").strip()
            if question_text:
                short_question = question_text.rstrip("?")
                title = f"{semantic_vector}: {short_question[:95]}"
                questions = [question_text]
            else:
                title = f"Практический разбор по теме «{semantic_vector}»"
                questions = []
            topic_items.append(
                {
                    "id": idx + 1,
                    "title": title,
                    "keyword": semantic_vector,
                    "questions": questions,
                    "rationale": "Тема сформирована на базе тематики канала и текущего спроса аудитории.",
                }
            )

    if not topic_items:
        semantic_stub = semantic_core[0] if semantic_core else channel.channel_name
        for idx in range(desired_count):
            topic_items.append(
                {
                    "id": idx + 1,
                    "title": f"{semantic_stub}: выпуск #{idx + 1}",
                    "keyword": semantic_stub,
                    "questions": [],
                    "rationale": "",
                }
            )

    keywords_for_ui = _normalize_phrase_list(
        [*(style_profile.get("keywords") or []), *semantic_core],
        limit=12,
    )

    return {
        "channel_id": channel.id,
        "channel_name": channel.channel_name,
        "platform": channel.platform,
        "style_summary": style_summary,
        "keywords": keywords_for_ui,
        "semantic_core": semantic_core[:12],
        "actual_questions": actual_questions[:5],
        "search_queries": search_queries[:10],
        "topics": topic_items[:desired_count],
        "source": source_mode,
    }


def _normalize_topic_items(raw_topics):
    normalized = []
    for item in raw_topics or []:
        if isinstance(item, str):
            title = item.strip()
        elif isinstance(item, dict):
            title = str(item.get("title") or item.get("topic") or "").strip()
        else:
            title = ""
        if not title:
            continue
        if title in normalized:
            continue
        normalized.append(title)
        if len(normalized) >= 30:
            break
    return normalized


def _frequency_to_interval_days(publish_frequency):
    normalized = _normalize_frequency(publish_frequency) or "daily"
    return {
        "daily": 1,
        "every_other_day": 2,
        "every_two_days": 3,
    }.get(normalized, 1)


def _extract_channel_topics_for_plan(channel):
    topics = []
    seen = set()

    active_topics = (
        ChannelTopic.query.filter_by(channel_id=channel.id, is_active=True)
        .order_by(ChannelTopic.priority.desc(), ChannelTopic.created_at.asc())
        .all()
    )
    for item in active_topics:
        topic_text = (item.topic or "").strip()
        if not topic_text:
            continue
        key = topic_text.lower()
        if key in seen:
            continue
        seen.add(key)
        topics.append(topic_text)

    if not topics:
        settings = ChannelSetting.query.filter_by(channel_id=channel.id).first()
        if settings and settings.topics:
            try:
                parsed_topics = json.loads(settings.topics)
            except Exception:
                parsed_topics = []
            for topic_text in _normalize_topic_items(parsed_topics):
                key = topic_text.lower()
                if key in seen:
                    continue
                seen.add(key)
                topics.append(topic_text)

    if not topics:
        extra = _channel_extra_config(channel)
        topic_plan = extra.get("topic_plan") or {}
        for topic_text in _normalize_topic_items(topic_plan.get("topics") or []):
            key = topic_text.lower()
            if key in seen:
                continue
            seen.add(key)
            topics.append(topic_text)

    if not topics:
        topics = [f"Контент-публикация для канала «{channel.channel_name}»"]

    return topics[:60]


def _build_posting_plan_preview_payload(
    channel,
    start_date=None,
    posts_count=14,
    publish_frequency=None,
    publish_hour=None,
):
    posts_count = min(max(int(posts_count or 14), 1), 60)
    settings = ChannelSetting.query.filter_by(channel_id=channel.id).first()
    extra = _channel_extra_config(channel)

    resolved_frequency = _normalize_frequency(
        publish_frequency
        or (settings.publish_frequency if settings else None)
        or extra.get("publish_frequency")
        or "daily"
    ) or "daily"

    if publish_hour is None:
        resolved_hour = settings.publish_hour if settings and settings.publish_hour is not None else extra.get("publish_hour", 10)
    else:
        resolved_hour = publish_hour
    try:
        resolved_hour = int(resolved_hour)
    except (TypeError, ValueError):
        resolved_hour = 10
    resolved_hour = min(max(resolved_hour, 0), 23)

    if start_date:
        try:
            start_day = datetime.fromisoformat(str(start_date)).date()
        except Exception:
            start_day = datetime.utcnow().date()
    else:
        start_day = datetime.utcnow().date()

    interval_days = _frequency_to_interval_days(resolved_frequency)
    topics = _extract_channel_topics_for_plan(channel)

    plan_items = []
    for idx in range(posts_count):
        publish_day = start_day + timedelta(days=idx * interval_days)
        topic_text = topics[idx % len(topics)]
        plan_items.append(
            {
                "index": idx + 1,
                "publish_date": publish_day.isoformat(),
                "publish_time": f"{resolved_hour:02d}:00",
                "topic": topic_text,
            }
        )

    return {
        "channel_id": channel.id,
        "channel_name": channel.channel_name,
        "platform": channel.platform,
        "publish_frequency": resolved_frequency,
        "publish_frequency_label": _frequency_to_human(resolved_frequency),
        "publish_hour": resolved_hour,
        "start_date": start_day.isoformat(),
        "interval_days": interval_days,
        "plan_items": plan_items,
    }


def _normalize_posting_plan_items_for_save(raw_items):
    normalized = []
    for item in raw_items or []:
        if not isinstance(item, dict):
            continue

        publish_date = str(item.get("publish_date") or "").strip()
        publish_time = str(item.get("publish_time") or "").strip()
        topic = str(item.get("topic") or "").strip()
        if not publish_date or not publish_time or not topic:
            continue

        try:
            datetime.fromisoformat(f"{publish_date}T{publish_time}")
        except Exception:
            continue

        normalized.append(
            {
                "publish_date": publish_date,
                "publish_time": publish_time,
                "topic": topic,
            }
        )
        if len(normalized) >= 120:
            break
    return normalized


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


# Импорт модулей Snoomi (fallback на заглушки если модулей нет/не настроены ключи)
try:
    from ai.text_generator import TextGenerator
    from ai.image_generator import ImageGenerator

    text_gen = TextGenerator()
    img_gen = ImageGenerator()
    logger.info("✅ AI-модули загружены")
except Exception as e:
    logger.warning(f"⚠️ AI-модули недоступны, используется fallback: {e}")

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
        client_name = request.form.get("client_name", "").strip() or username
        email = request.form.get("email", "").strip() or None
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        notification_telegram = request.form.get("notification_telegram", "").strip() or None
        trial_days_raw = request.form.get("trial_days", "14").strip()

        if not username:
            flash("Введите имя пользователя", "danger")
            return render_template("register.html")
        if not client_name:
            flash("Введите имя клиента/компании", "danger")
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

        try:
            trial_days = int(trial_days_raw)
        except ValueError:
            trial_days = 14
        if trial_days not in TRIAL_OPTIONS_DAYS:
            trial_days = 14

        now = datetime.utcnow()
        trial_ends_at = now + timedelta(days=trial_days)

        new_client = Client(
            name=client_name,
            email=email,
            notification_telegram=notification_telegram,
            plan="trial",
            status="active",
            trial_days=trial_days,
            trial_started_at=now,
            trial_ends_at=trial_ends_at,
        )
        db.session.add(new_client)
        db.session.flush()

        new_user = User(
            username=username,
            email=email,
            role="client",
            client_id=new_client.id,
            is_active=True,
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        email_sent = False
        email_status = "not_requested"
        if email:
            email_sent, email_status = _send_registration_email(
                email_to=email,
                username=username,
                password=password,
                client_name=client_name,
                trial_days=trial_days,
            )

        login_user(new_user)
        flash(
            f"Регистрация успешна! Вам активирован бесплатный тестовый период на {trial_days} дней.",
            "success",
        )
        if email and email_sent and str(email_status).startswith("stub_saved:"):
            stub_path = str(email_status).split(":", 1)[1].strip()
            stub_filename = Path(stub_path).name if stub_path else "registration_email.eml"
            flash(
                f"Письмо сохранено в локальную заглушку: logs/dev_outbox/{stub_filename}",
                "info",
            )
        elif email and email_sent:
            flash("Данные для входа отправлены на указанную почту.", "success")
        elif email and email_status == "smtp_not_configured":
            flash(
                "Регистрация выполнена, но почта не отправлена: SMTP пока не настроен в окружении.",
                "warning",
            )
        elif email and str(email_status).startswith("stub_error:"):
            flash(
                "Регистрация выполнена, но письмо не удалось сохранить в локальный outbox.",
                "warning",
            )
        elif email and not email_sent:
            flash(
                "Регистрация выполнена, но письмо не отправлено. Проверьте настройки SMTP.",
                "warning",
            )
        return redirect(url_for("channels"))

    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# -------------------- ОСНОВНЫЕ СТРАНИЦЫ --------------------
@app.route("/")
def index():
    try:
        total_posts = ChannelPost.query.count()
        active_clients = Client.query.filter_by(status="active").count()
        active_channels = ClientChannel.query.filter_by(is_active=True).count()
    except Exception as exc:
        system_logger.warning("index_metrics_fallback error=%s", exc)
        total_posts = 0
        active_clients = 0
        active_channels = 0

    supported_networks = []
    if "telegram" in SUPPORTED_PLATFORMS:
        supported_networks.append("Telegram")
    if "vk" in SUPPORTED_PLATFORMS:
        supported_networks.append("ВКонтакте")

    return render_template(
        "index.html",
        total_posts=total_posts,
        active_clients=active_clients,
        active_channels=active_channels,
        supported_networks=supported_networks,
        trial_days_default=14 if 14 in TRIAL_OPTIONS_DAYS else min(TRIAL_OPTIONS_DAYS),
    )


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

    # channels.html использует legacy-поля name/category, но расширяем payload новыми полями.
    channels_payload = []
    for ch in channels_data:
        serialized = _serialize_channel(ch, include_client_name=True)
        serialized["name"] = ch.channel_name
        serialized["category"] = ch.platform
        channels_payload.append(serialized)

    client_info = None
    if current_user.client_id:
        client = Client.query.get(current_user.client_id)
        client_info = _serialize_client(client) if client else None

    return render_template(
        "channels.html",
        channels=channels_payload,
        scheduled_posts=[],
        content_list=[],
        client_info=client_info,
    )


@app.route("/posting-setup")
@login_required
def posting_setup():
    if is_admin_user(current_user):
        channels_data = (
            ClientChannel.query.filter_by(is_active=True)
            .order_by(ClientChannel.created_at.desc())
            .all()
        )
    elif current_user.client_id:
        channels_data = (
            ClientChannel.query.filter_by(client_id=current_user.client_id, is_active=True)
            .order_by(ClientChannel.created_at.desc())
            .all()
        )
    else:
        channels_data = []

    channels_payload = [_serialize_channel(ch, include_client_name=True) for ch in channels_data]
    return render_template("posting_setup.html", channels=channels_payload, user=current_user)


@app.route("/posting-plan")
@login_required
def posting_plan():
    if is_admin_user(current_user):
        channels_data = (
            ClientChannel.query.filter_by(is_active=True)
            .order_by(ClientChannel.created_at.desc())
            .all()
        )
    elif current_user.client_id:
        channels_data = (
            ClientChannel.query.filter_by(client_id=current_user.client_id, is_active=True)
            .order_by(ClientChannel.created_at.desc())
            .all()
        )
    else:
        channels_data = []

    channels_payload = [_serialize_channel(ch, include_client_name=True) for ch in channels_data]
    return render_template("posting_plan.html", channels=channels_payload, user=current_user)


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


def _sanitize_behavior_payload(payload):
    if not isinstance(payload, dict):
        payload = {"value": str(payload)}

    sensitive_markers = ("token", "password", "secret", "key", "authorization")
    sanitized = {}
    for raw_key, raw_value in payload.items():
        key = str(raw_key)[:80]
        lower_key = key.lower()
        if any(marker in lower_key for marker in sensitive_markers):
            sanitized[key] = "***"
            continue

        if isinstance(raw_value, (dict, list)):
            value = json.dumps(raw_value, ensure_ascii=False)[:500]
        else:
            value = str(raw_value)[:500]
        sanitized[key] = value
    return sanitized


@app.route("/api/client-events", methods=["POST"])
def api_client_events():
    data = request.get_json(silent=True) or {}
    event_type = (data.get("event_type") or "").strip().lower()
    if not event_type:
        return jsonify({"success": False, "error": "event_type is required"}), 400

    payload = _sanitize_behavior_payload(data.get("payload") or {})
    user_ctx = _request_user_context()
    event_record = {
        "event_type": event_type[:80],
        "path": (data.get("path") or request.path)[:200],
        "user_id": user_ctx.get("user_id"),
        "username": user_ctx.get("username"),
        "client_id": user_ctx.get("client_id"),
        "ip": request.remote_addr,
        "user_agent": (request.headers.get("User-Agent") or "")[:300],
        "payload": payload,
        "timestamp": datetime.utcnow().isoformat(),
    }
    behavior_logger.info(json.dumps(event_record, ensure_ascii=False))
    return jsonify({"success": True})


# -------------------- API: ПРОВЕРКА КАНАЛОВ И СТИЛИСТИКА --------------------
@app.route("/api/public/channel-preview", methods=["POST"])
def api_public_channel_preview():
    data = request.get_json(silent=True) or {}
    platform = (data.get("platform") or "").strip().lower()
    channel_reference = (data.get("channel_reference") or "").strip()
    access_token = (data.get("access_token") or "").strip()

    if platform not in SUPPORTED_PLATFORMS:
        return jsonify({"success": False, "error": "Поддерживаются только Telegram и VK"}), 400
    if not channel_reference:
        return jsonify({"success": False, "error": "Укажите ссылку или ник канала"}), 400

    intelligence = _build_channel_intelligence(
        platform=platform,
        channel_reference=channel_reference,
        access_token=access_token,
        run_ai_analysis=True,
    )
    if not intelligence.get("success"):
        system_logger.warning(
            "channel_preview_failed platform=%s reference=%s error=%s",
            platform,
            channel_reference,
            intelligence.get("error"),
        )
        return jsonify({"success": False, "error": intelligence.get("error", "Канал не прошел проверку")}), 400

    return jsonify(
        {
            "success": True,
            "verified": True,
            "platform": intelligence.get("platform"),
            "channel_name": intelligence.get("channel_name"),
            "channel_id": intelligence.get("channel_id"),
            "source_url": intelligence.get("source_url"),
            "channel_external_description": intelligence.get("channel_external_description", ""),
            "recent_posts": intelligence.get("recent_posts", [])[:10],
            "style_profile": intelligence.get("style_profile", {}),
            "style_summary": intelligence.get("style_summary", ""),
            "auto_description": intelligence.get("auto_description", ""),
        }
    )


@app.route("/api/channels/verify", methods=["POST"])
@login_required
def api_verify_channel():
    data = request.get_json(silent=True) or {}
    platform = (data.get("platform") or "").strip().lower()
    channel_reference = (data.get("channel_reference") or "").strip()
    access_token = (data.get("access_token") or "").strip()

    if platform not in SUPPORTED_PLATFORMS:
        return jsonify({"success": False, "error": "Поддерживаются только Telegram и VK"}), 400
    if not channel_reference:
        return jsonify({"success": False, "error": "Укажите ссылку или ник канала"}), 400

    intelligence = _build_channel_intelligence(
        platform=platform,
        channel_reference=channel_reference,
        access_token=access_token,
        run_ai_analysis=True,
    )
    if not intelligence.get("success"):
        system_logger.warning(
            "channel_verify_failed user_id=%s platform=%s reference=%s error=%s",
            current_user.id if current_user.is_authenticated else None,
            platform,
            channel_reference,
            intelligence.get("error"),
        )
        return jsonify({"success": False, "error": intelligence.get("error", "Канал не прошел проверку")}), 400

    return jsonify(
        {
            "success": True,
            "verified": True,
            "platform": intelligence.get("platform"),
            "channel_name": intelligence.get("channel_name"),
            "channel_id": intelligence.get("channel_id"),
            "source_url": intelligence.get("source_url"),
            "channel_external_description": intelligence.get("channel_external_description", ""),
            "recent_posts": intelligence.get("recent_posts", [])[:10],
            "style_profile": intelligence.get("style_profile", {}),
            "style_summary": intelligence.get("style_summary", ""),
            "auto_description": intelligence.get("auto_description", ""),
        }
    )


@app.route("/api/posting-setup/plan", methods=["POST"])
@login_required
def api_posting_setup_plan():
    data = request.get_json(silent=True) or {}
    channel_id = data.get("channel_id")
    focus_text = (data.get("focus_text") or "").strip()
    desired_count = data.get("desired_count", 8)

    try:
        channel_id = int(channel_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Укажите корректный channel_id"}), 400

    try:
        desired_count = int(desired_count)
    except (TypeError, ValueError):
        desired_count = 8

    channel = _get_accessible_channel(channel_id)
    if not channel.is_active:
        return jsonify({"success": False, "error": "Канал отключен. Включите его перед настройкой постинга."}), 400

    planner_payload = _build_topic_planner_payload(
        channel=channel,
        focus_text=focus_text,
        desired_count=desired_count,
    )
    return jsonify(
        {
            "success": True,
            "channel_id": planner_payload.get("channel_id"),
            "channel_name": planner_payload.get("channel_name"),
            "platform": planner_payload.get("platform"),
            "style_summary": planner_payload.get("style_summary", ""),
            "semantic_core": planner_payload.get("semantic_core", [])[:8],
            "actual_questions": planner_payload.get("actual_questions", [])[:5],
            "topics": planner_payload.get("topics", []),
        }
    )


@app.route("/api/posting-setup/topics", methods=["POST"])
@login_required
def api_posting_setup_save_topics():
    data = request.get_json(silent=True) or {}
    channel_id = data.get("channel_id")
    raw_topics = data.get("topics") or []

    try:
        channel_id = int(channel_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Укажите корректный channel_id"}), 400

    normalized_topics = _normalize_topic_items(raw_topics)
    if not normalized_topics:
        return jsonify({"success": False, "error": "Добавьте хотя бы одну тему для сохранения"}), 400

    channel = _get_accessible_channel(channel_id)
    if not channel.is_active:
        return jsonify({"success": False, "error": "Канал отключен. Включите его перед сохранением тем."}), 400

    ChannelTopic.query.filter_by(channel_id=channel.id, is_active=True).update({"is_active": False})
    for idx, topic_title in enumerate(normalized_topics, start=1):
        topic_item = ChannelTopic(
            channel_id=channel.id,
            topic=topic_title,
            keywords=json.dumps(_extract_keywords(topic_title), ensure_ascii=False),
            priority=max(1, 10 - idx),
            is_active=True,
        )
        db.session.add(topic_item)

    settings = ChannelSetting.query.filter_by(channel_id=channel.id).first()
    if not settings:
        default_frequency = _normalize_frequency((_channel_extra_config(channel).get("publish_frequency") or "daily"))
        settings = ChannelSetting(
            channel_id=channel.id,
            publish_hour=10,
            publish_frequency=default_frequency or "daily",
            topics=json.dumps(normalized_topics, ensure_ascii=False),
            hashtags=json.dumps([], ensure_ascii=False),
            max_posts_per_day=1,
            is_auto_generate=True,
            use_ai_images=True,
        )
        db.session.add(settings)
    else:
        settings.topics = json.dumps(normalized_topics, ensure_ascii=False)

    extra = _channel_extra_config(channel)
    extra["topic_plan"] = {
        "updated_at": datetime.utcnow().isoformat(),
        "topics": normalized_topics,
    }
    channel.additional_config = json.dumps(extra, ensure_ascii=False)

    db.session.commit()
    return jsonify(
        {
            "success": True,
            "saved_topics": len(normalized_topics),
            "channel_id": channel.id,
            "channel_name": channel.channel_name,
        }
    )


@app.route("/api/posting-plan/preview", methods=["POST"])
@login_required
def api_posting_plan_preview():
    data = request.get_json(silent=True) or {}
    channel_id = data.get("channel_id")
    start_date = (data.get("start_date") or "").strip() or None
    posts_count = data.get("posts_count", 14)
    publish_frequency = data.get("publish_frequency")
    publish_hour = data.get("publish_hour")

    try:
        channel_id = int(channel_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Укажите корректный channel_id"}), 400

    try:
        posts_count = int(posts_count)
    except (TypeError, ValueError):
        posts_count = 14

    channel = _get_accessible_channel(channel_id)
    if not channel.is_active:
        return jsonify({"success": False, "error": "Канал отключен. Включите его перед шагом 3."}), 400

    preview_payload = _build_posting_plan_preview_payload(
        channel=channel,
        start_date=start_date,
        posts_count=posts_count,
        publish_frequency=publish_frequency,
        publish_hour=publish_hour,
    )
    return jsonify({"success": True, **preview_payload})


@app.route("/api/posting-plan/save", methods=["POST"])
@login_required
def api_posting_plan_save():
    data = request.get_json(silent=True) or {}
    channel_id = data.get("channel_id")
    raw_plan_items = data.get("plan_items") or []
    publish_frequency = data.get("publish_frequency")
    publish_hour = data.get("publish_hour")

    try:
        channel_id = int(channel_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Укажите корректный channel_id"}), 400

    channel = _get_accessible_channel(channel_id)
    if not channel.is_active:
        return jsonify({"success": False, "error": "Канал отключен. Включите его перед сохранением плана."}), 400

    normalized_items = _normalize_posting_plan_items_for_save(raw_plan_items)
    if not normalized_items:
        return jsonify({"success": False, "error": "Список публикаций пуст или содержит некорректные данные"}), 400

    normalized_frequency = _normalize_frequency(publish_frequency) or "daily"
    try:
        normalized_hour = int(publish_hour)
    except (TypeError, ValueError):
        normalized_hour = 10
    normalized_hour = min(max(normalized_hour, 0), 23)

    settings = ChannelSetting.query.filter_by(channel_id=channel.id).first()
    if not settings:
        settings = ChannelSetting(
            channel_id=channel.id,
            publish_hour=normalized_hour,
            publish_frequency=normalized_frequency,
            topics=json.dumps(_extract_channel_topics_for_plan(channel), ensure_ascii=False),
            hashtags=json.dumps([], ensure_ascii=False),
            max_posts_per_day=1,
            is_auto_generate=True,
            use_ai_images=True,
        )
        db.session.add(settings)
    else:
        settings.publish_hour = normalized_hour
        settings.publish_frequency = normalized_frequency

    extra = _channel_extra_config(channel)
    extra["posting_plan_draft"] = {
        "updated_at": datetime.utcnow().isoformat(),
        "publish_frequency": normalized_frequency,
        "publish_hour": normalized_hour,
        "plan_items": normalized_items,
    }
    channel.additional_config = json.dumps(extra, ensure_ascii=False)

    db.session.commit()
    return jsonify(
        {
            "success": True,
            "saved_items": len(normalized_items),
            "channel_id": channel.id,
            "channel_name": channel.channel_name,
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
    required_fields = [
        "platform",
        "channel_reference",
        "access_token",
        "channel_description",
        "publish_frequency",
    ]
    if not all(data.get(field) for field in required_fields):
        return jsonify({"success": False, "error": "Не все обязательные поля заполнены"}), 400

    platform = (data.get("platform") or "").strip().lower()
    if platform not in SUPPORTED_PLATFORMS:
        return jsonify({"success": False, "error": "Сейчас поддерживаются только Telegram и VK"}), 400

    channel_reference = (data.get("channel_reference") or "").strip()
    access_token = (data.get("access_token") or "").strip()
    if not channel_reference:
        return jsonify({"success": False, "error": "Укажите ссылку или ник канала"}), 400

    publish_frequency = _normalize_frequency(data.get("publish_frequency"))
    if not publish_frequency:
        return jsonify(
            {"success": False, "error": "Укажите корректную частоту: каждый день / через день / через 2 дня"}
        ), 400

    channel_description = (data.get("channel_description") or "").strip()
    if _count_words(channel_description) < 20:
        return jsonify(
            {
                "success": False,
                "error": "Опишите специфику канала минимум 20 словами для качественной генерации контента",
            }
        ), 400

    try:
        publish_hour = int(data.get("publish_hour", 10))
    except (TypeError, ValueError):
        publish_hour = 10
    publish_hour = min(max(publish_hour, 0), 23)

    if is_admin_user(current_user):
        client_id = data.get("client_id")
        if not client_id:
            return jsonify({"success": False, "error": "Для администратора укажите client_id"}), 400
        try:
            client_id = int(client_id)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Некорректный client_id"}), 400
    else:
        client_id = current_user.client_id
        if not client_id:
            return jsonify({"success": False, "error": "Ваш аккаунт не привязан к клиенту"}), 400

    client = Client.query.get(client_id)
    if not client:
        return jsonify({"success": False, "error": "Клиент не найден"}), 404
    if not is_admin_user(current_user) and not _is_trial_active(client):
        return jsonify(
            {
                "success": False,
                "error": "Тестовый период завершен. Обратитесь к администратору для продления/подключения тарифа.",
            }
        ), 403

    notification_telegram = (data.get("notification_telegram") or "").strip() or None
    if notification_telegram:
        client.notification_telegram = notification_telegram

    # Без успешной проверки ссылки канал не добавляется.
    intelligence = _build_channel_intelligence(
        platform=platform,
        channel_reference=channel_reference,
        access_token=access_token,
        run_ai_analysis=False,
    )
    if not intelligence.get("success"):
        return jsonify(
            {
                "success": False,
                "error": intelligence.get(
                    "error",
                    "Ссылка канала не подтверждена. Нажмите «Проверить канал» и попробуйте снова.",
                ),
            }
        ), 400

    verified_channel_name = intelligence.get("channel_name")
    verified_channel_id = intelligence.get("channel_id")
    source_url = intelligence.get("source_url")
    style_profile = intelligence.get("style_profile") or {}
    if not verified_channel_name or not verified_channel_id:
        return jsonify({"success": False, "error": "Не удалось определить имя или ID канала по ссылке"}), 400

    duplicate_channel = ClientChannel.query.filter_by(
        client_id=client_id,
        platform=platform,
        channel_id=verified_channel_id,
    ).first()
    if duplicate_channel:
        return jsonify(
            {
                "success": False,
                "error": "Этот канал уже добавлен в ваш список автопостинга",
            }
        ), 400

    additional_config = {
        "channel_description": channel_description,
        "publish_frequency": publish_frequency,
        "channel_reference": channel_reference,
        "source_url": source_url,
        "channel_external_description": intelligence.get("channel_external_description", ""),
        "recent_posts_preview": intelligence.get("recent_posts", [])[:10],
        "style_profile": style_profile,
        "source": "web_client_onboarding",
    }
    channel = ClientChannel(
        client_id=client_id,
        platform=platform,
        channel_id=verified_channel_id,
        channel_name=verified_channel_name,
        access_token=access_token,
        additional_config=json.dumps(additional_config, ensure_ascii=False),
        is_active=bool(data.get("is_active", True)),
    )
    db.session.add(channel)
    db.session.flush()

    _ensure_channel_runtime_setup(
        channel_id=channel.id,
        channel_description=channel_description,
        publish_frequency=publish_frequency,
        publish_hour=publish_hour,
    )

    db.session.commit()
    return jsonify(
        {
            "success": True,
            "channel_id": channel.id,
            "platform_channel_id": verified_channel_id,
            "channel_name": verified_channel_name,
            "source_url": source_url,
            "publish_frequency": publish_frequency,
            "publish_hour": publish_hour,
            "style_summary": style_profile.get("summary", ""),
        }
    )


@app.route("/api/channels/<int:channel_id>", methods=["GET"])
@login_required
def api_get_channel(channel_id):
    channel = _get_accessible_channel(channel_id)
    payload = _serialize_channel(channel, include_client_name=True)
    if channel.client:
        payload["notification_telegram"] = channel.client.notification_telegram
    return jsonify(payload)


@app.route("/api/channels/<int:channel_id>", methods=["PUT"])
@login_required
def api_update_channel(channel_id):
    channel = _get_accessible_channel(channel_id)
    data = request.get_json(silent=True) or {}

    if "publish_frequency" in data:
        normalized_frequency = _normalize_frequency(data.get("publish_frequency"))
        if not normalized_frequency:
            return jsonify({"success": False, "error": "Некорректная частотность автопостинга"}), 400
    else:
        normalized_frequency = None

    if "channel_description" in data:
        channel_description = (data.get("channel_description") or "").strip()
        if _count_words(channel_description) < 20:
            return jsonify(
                {
                    "success": False,
                    "error": "Описание канала должно содержать минимум 20 слов",
                }
            ), 400
    else:
        channel_description = None

    for field in ("channel_name", "access_token", "is_active"):
        if field in data:
            setattr(channel, field, data[field])

    if "platform" in data:
        platform = (data.get("platform") or "").strip().lower()
        if platform not in SUPPORTED_PLATFORMS:
            return jsonify({"success": False, "error": "Сейчас поддерживаются только Telegram и VK"}), 400
        channel.platform = platform

    if "channel_id" in data:
        channel.channel_id = (data.get("channel_id") or "").strip()

    extra = _channel_extra_config(channel)
    if channel_description is not None:
        extra["channel_description"] = channel_description
    if normalized_frequency is not None:
        extra["publish_frequency"] = normalized_frequency
    channel.additional_config = json.dumps(extra, ensure_ascii=False)

    if "publish_hour" in data:
        try:
            publish_hour = int(data.get("publish_hour", 10))
        except (TypeError, ValueError):
            publish_hour = 10
    else:
        publish_hour = None
    if publish_hour is not None:
        publish_hour = min(max(publish_hour, 0), 23)

    if channel_description is not None or normalized_frequency is not None or publish_hour is not None:
        current_setting = ChannelSetting.query.filter_by(channel_id=channel.id).first()
        resolved_publish_hour = (
            publish_hour
            if publish_hour is not None
            else (current_setting.publish_hour if current_setting and current_setting.publish_hour is not None else 10)
        )
        _ensure_channel_runtime_setup(
            channel_id=channel.id,
            channel_description=channel_description or extra.get("channel_description", ""),
            publish_frequency=normalized_frequency or extra.get("publish_frequency", "daily"),
            publish_hour=resolved_publish_hour,
        )

    if "notification_telegram" in data and channel.client:
        channel.client.notification_telegram = (data.get("notification_telegram") or "").strip() or None

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
        notification_telegram=(data.get("notification_telegram") or "").strip() or None,
        phone=(data.get("phone") or "").strip() or None,
        plan=(data.get("plan") or "basic").strip(),
        status=(data.get("status") or "active").strip(),
        trial_days=int(data.get("trial_days", 14)) if str(data.get("trial_days", "")).isdigit() else 14,
    )
    if client.plan == "trial":
        client.trial_started_at = datetime.utcnow()
        client.trial_ends_at = client.trial_started_at + timedelta(days=client.trial_days or 14)
    db.session.add(client)
    db.session.commit()
    return jsonify({"success": True, "client": _serialize_client(client, include_counts=True)})


@app.route("/api/admin/clients/<int:client_id>", methods=["PUT"])
@admin_required
def api_admin_update_client(client_id):
    client = Client.query.get_or_404(client_id)
    data = request.get_json(silent=True) or {}

    for field in ("name", "email", "telegram_id", "notification_telegram", "phone", "plan", "status"):
        if field in data:
            value = data[field]
            if isinstance(value, str):
                value = value.strip()
            setattr(client, field, value)

    if "trial_days" in data:
        try:
            client.trial_days = int(data.get("trial_days", 14))
        except (TypeError, ValueError):
            client.trial_days = 14

    if "trial_ends_at" in data:
        trial_ends_at = data.get("trial_ends_at")
        if trial_ends_at:
            try:
                client.trial_ends_at = datetime.fromisoformat(str(trial_ends_at))
            except Exception:
                pass
        else:
            client.trial_ends_at = None

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
    required_fields = [
        "client_id",
        "platform",
        "channel_id",
        "channel_name",
        "access_token",
        "channel_description",
        "publish_frequency",
    ]
    if not all(data.get(field) for field in required_fields):
        return jsonify({"success": False, "error": "Не все обязательные поля заполнены"}), 400

    platform = (data.get("platform") or "").strip().lower()
    if platform not in SUPPORTED_PLATFORMS:
        return jsonify({"success": False, "error": "Сейчас поддерживаются только Telegram и VK"}), 400

    admin_description = (data.get("channel_description") or "").strip()
    if _count_words(admin_description) < 20:
        return jsonify(
            {
                "success": False,
                "error": "Описание канала должно быть минимум 20 слов",
            }
        ), 400

    admin_frequency = _normalize_frequency(data.get("publish_frequency"))
    if not admin_frequency:
        return jsonify({"success": False, "error": "Некорректная частота публикаций"}), 400

    client = Client.query.get(data["client_id"])
    if not client:
        return jsonify({"success": False, "error": "Клиент не найден"}), 404

    channel = ClientChannel(
        client_id=data["client_id"],
        platform=platform,
        channel_id=(data["channel_id"] or "").strip(),
        channel_name=(data["channel_name"] or "").strip(),
        access_token=data.get("access_token"),
        additional_config=json.dumps(
            {
                "channel_description": admin_description,
                "publish_frequency": admin_frequency,
                "source": "admin_connection_form",
            },
            ensure_ascii=False,
        ),
        is_active=bool(data.get("is_active", True)),
    )
    db.session.add(channel)
    db.session.flush()

    _ensure_channel_runtime_setup(
        channel_id=channel.id,
        channel_description=admin_description,
        publish_frequency=admin_frequency,
        publish_hour=data.get("publish_hour", 10),
    )

    db.session.commit()
    return jsonify({"success": True, "connection": _serialize_channel(channel, include_client_name=True)})


@app.route("/api/admin/connections/<int:connection_id>", methods=["PUT"])
@admin_required
def api_admin_update_connection(connection_id):
    channel = ClientChannel.query.get_or_404(connection_id)
    data = request.get_json(silent=True) or {}

    for field in ("channel_id", "channel_name", "access_token", "is_active"):
        if field in data:
            setattr(channel, field, data[field])

    if "platform" in data:
        platform = (data.get("platform") or "").strip().lower()
        if platform not in SUPPORTED_PLATFORMS:
            return jsonify({"success": False, "error": "Сейчас поддерживаются только Telegram и VK"}), 400
        channel.platform = platform

    if "client_id" in data:
        client = Client.query.get(data["client_id"])
        if not client:
            return jsonify({"success": False, "error": "Клиент не найден"}), 404
        channel.client_id = client.id

    if "channel_description" in data or "publish_frequency" in data or "publish_hour" in data:
        extra = _channel_extra_config(channel)
        if "channel_description" in data:
            desc_value = (data.get("channel_description") or "").strip()
            if _count_words(desc_value) < 20:
                return jsonify({"success": False, "error": "Описание канала должно быть минимум 20 слов"}), 400
            extra["channel_description"] = desc_value
        if "publish_frequency" in data:
            normalized = _normalize_frequency(data.get("publish_frequency"))
            if not normalized:
                return jsonify({"success": False, "error": "Некорректная частота публикаций"}), 400
            extra["publish_frequency"] = normalized
        channel.additional_config = json.dumps(extra, ensure_ascii=False)

        publish_hour = data.get("publish_hour", 10)
        try:
            publish_hour = int(publish_hour)
        except (TypeError, ValueError):
            publish_hour = 10
        publish_hour = min(max(publish_hour, 0), 23)

        _ensure_channel_runtime_setup(
            channel_id=channel.id,
            channel_description=extra.get("channel_description", ""),
            publish_frequency=extra.get("publish_frequency", "daily"),
            publish_hour=publish_hour,
        )

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
    _ensure_clients_schema()
    _ensure_client_channels_schema()

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