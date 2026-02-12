# Snoomi Platform

Платформа для автопостинга и управления публикациями в соцсетях (Telegram/VK) с веб-интерфейсом,
планировщиком, аналитикой и онбордингом клиентов.

### Стратегический документ

- `CLIENT_EXPERT_AGENT_PRD.md` — PRD по клиентскому экспертному AI-агенту (семантика, RAG, quality-gate, roadmap).
- `FASTVPS_DEPLOY_CHECKLIST.md` — production чеклист развертывания SMI-platforma на FastVPS.
- `QA_PLAN_CHANNELS_AND_ADMIN.md` — подробный план тестирования каналов и админки перед запуском.
- `GO_TO_MARKET_SEO_PLAN.md` — портрет ЦА, каналы продвижения, семантическое ядро и SEO-план.

---

## 1) Обновить локальный проект

```bash
git fetch origin cursor/-bc-f477b4da-9d10-4f5f-9066-24192a0b661a-0bde
git pull origin cursor/-bc-f477b4da-9d10-4f5f-9066-24192a0b661a-0bde
```

---

## 2) Подготовка окружения

```bash
# Python dependencies
pip install -r requirements.txt
pip install -r Bot/requirements.txt
```

Скопируйте шаблон env и заполните своими ключами:

```bash
cp .env.example .env
```

---

## 3) Запуск "с нуля" (новая регистрация)

### Вариант A: полностью с чистой БД (рекомендуется для локального smoke-test)

```bash
# если хотите полностью новый старт, удалите локальную БД
rm -f snoomi_channels.db
```

Дополнительно:
- выйдите из аккаунта в браузере;
- очистите cookies/Local Storage для `localhost:5000` (если сессия кэшируется).

### Вариант B: отдельная тестовая БД без удаления основной

```bash
export WEB_DATABASE_URL=sqlite:////absolute/path/to/snoomi_channels_fresh.db
```

---

## 4) Локальная заглушка почты (без SMTP-провайдера)

Для локального теста без сервера/провайдера в `.env` достаточно:

```env
EMAIL_DELIVERY_MODE=stub
PUBLIC_BASE_URL=http://localhost:5000
```

При регистрации письмо будет **не отправляться в интернет**, а сохраняться локально:
- `logs/dev_outbox/*.eml` — само письмо,
- `logs/dev_outbox.log` — индекс писем.

### Когда будете подключать реальный SMTP

```env
EMAIL_DELIVERY_MODE=smtp
SMTP_HOST=smtp.your-provider.com
SMTP_PORT=587
SMTP_USER=your-login
SMTP_PASSWORD=your-password-or-app-password
SMTP_FROM_EMAIL=no-reply@your-domain.com
SMTP_FROM_NAME=Snoomi Platform
SMTP_USE_SSL=False
SMTP_USE_TLS=True
PUBLIC_BASE_URL=http://localhost:5000
```

> Если используете SSL-порт (обычно 465), выставьте:
> `SMTP_USE_SSL=True` и `SMTP_USE_TLS=False`.

---

## 5) Запуск веб-панели

```bash
python run_web.py
```

Откройте:
- `http://localhost:5000/register` — регистрация,
- `http://localhost:5000/login` — вход.

После регистрации:
- создается клиент + пользователь,
- активируется trial,
- письмо сохраняется в локальную заглушку (`logs/dev_outbox`) или отправляется через SMTP
  в зависимости от `EMAIL_DELIVERY_MODE`.

---

## 6) Быстрый чек проблем с email

Если используете `EMAIL_DELIVERY_MODE=stub`:
1. Проверьте, что появился файл в `logs/dev_outbox`.
2. Проверьте запись в `logs/dev_outbox.log`.

Если используете `EMAIL_DELIVERY_MODE=smtp`:
1. Проверьте `SMTP_HOST` и порт.
2. Проверьте `SMTP_USE_SSL` / `SMTP_USE_TLS` (не включайте оба сразу).
3. Проверьте лог ошибок: `logs/errors.log`.
4. Проверьте системный лог: `logs/system.log`.

---

## 7) Точки запуска компонентов

```bash
python run_site_bot.py        # только Telegram-бот сайта
python run_monetization.py    # только планировщик автопостинга
python run_web.py             # только веб-панель
```

---

## 7.1) Подключение каналов без ключей клиента (упрощенный режим)

Для Telegram можно работать без токена клиента:

1. Клиент добавляет сервисного бота в канал/группу как администратора.
2. В форме подключения указывает только ссылку/ник канала.
3. Сервис проверяет права бота и сохраняет канал.

Что нужно на сервере:

```env
TELEGRAM_BOT_TOKEN=...
# или TELEGRAM_CHANNEL_TOKEN=...
SERVICE_TELEGRAM_BOT_USERNAME=@your_bot_username   # опционально, для подсказок в UI
```

Для VK ручной ключ клиента тоже можно не запрашивать, если на сервере настроен сервисный доступ:

```env
VK_ACCESS_TOKEN=...
```

---

## 8) Expert Agent API (PRD implementation start)

Feature flag (по умолчанию включен):

```env
ENABLE_EXPERT_AGENT=1
```

Новые API-эндпоинты:

- `POST /api/agent/semantic-core/rebuild` — перестроить семантическое ядро канала, knowledge-docs и top questions.
- `POST /api/agent/research/update` — обновить web-research и вопросы аудитории.
- `POST /api/agent/draft` — собрать platform-aware черновик + quality report.
- `POST /api/agent/quality/evaluate` — переоценить quality-gate для run или произвольного текста.
- `POST /api/agent/publish` — опубликовать run (по quality gate или с `force=true`).
- `GET /api/agent/runs` — история запусков агента с quality-статусом.

Базовый сценарий:
1. Подключите канал (Шаг 1), сохраните темы (Шаг 2), календарь (Шаг 3).
2. Вызовите `semantic-core/rebuild` для канала.
3. Вызовите `draft`, получите `run_id`.
4. При необходимости повторно вызовите `quality/evaluate`.
5. Публикуйте через `publish`.

UI-консоль для этого потока доступна в вебе по адресу:
- `/agent` (пункт меню **AI Агент** после входа в систему).