# SMI-platforma: чеклист развертывания на FastVPS (production)

Документ для запуска веб-части + планировщика с минимальным риском.

---

## 1) Базовая схема прода

- **Сервер:** Ubuntu 22.04/24.04 (FastVPS)
- **Процессы:**
  - `gunicorn` — веб-приложение Flask
  - `python run_monetization.py` — планировщик публикаций
- **Reverse proxy:** Nginx
- **SSL:** Let's Encrypt (certbot)
- **Логи:** `logs/system.log`, `logs/errors.log`, `logs/client_behavior.log`, journalctl
- **БД:** SQLite (на старте), бэкап по cron

---

## 2) Подготовка сервера

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install python3 python3-venv python3-pip nginx certbot python3-certbot-nginx git
sudo adduser --disabled-password --gecos "" smi
sudo mkdir -p /opt/smi-platforma
sudo chown -R smi:smi /opt/smi-platforma
```

---

## 3) Деплой приложения

```bash
sudo -u smi -H bash -lc '
cd /opt/smi-platforma &&
git clone https://github.com/Vitalin23/snoomi-platform.git app &&
cd app &&
python3 -m venv .venv &&
source .venv/bin/activate &&
pip install --upgrade pip &&
pip install -r requirements.txt &&
cp .env.example .env
'
```

Заполнить `/opt/smi-platforma/app/.env`:

- `APP_BRAND_NAME=SMI-platforma`
- `PUBLIC_BASE_URL=https://<ВАШ_ДОМЕН>`
- ключи Yandex/Telegram/VK
- SMTP (или `EMAIL_DELIVERY_MODE=stub` на этапе теста)
- `WEB_HOST=127.0.0.1`
- `WEB_PORT=5000`
- `ENABLE_EXPERT_AGENT=1`

---

## 4) systemd: web + scheduler

### `/etc/systemd/system/smi-web.service`

```ini
[Unit]
Description=SMI-platforma web (gunicorn)
After=network.target

[Service]
User=smi
Group=smi
WorkingDirectory=/opt/smi-platforma/app
Environment="PATH=/opt/smi-platforma/app/.venv/bin"
ExecStart=/opt/smi-platforma/app/.venv/bin/gunicorn -w 3 -b 127.0.0.1:5000 web.app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### `/etc/systemd/system/smi-scheduler.service`

```ini
[Unit]
Description=SMI-platforma monetization scheduler
After=network.target

[Service]
User=smi
Group=smi
WorkingDirectory=/opt/smi-platforma/app
Environment="PATH=/opt/smi-platforma/app/.venv/bin"
ExecStart=/opt/smi-platforma/app/.venv/bin/python run_monetization.py
Restart=always
RestartSec=8

[Install]
WantedBy=multi-user.target
```

Запуск:

```bash
sudo systemctl daemon-reload
sudo systemctl enable smi-web smi-scheduler
sudo systemctl start smi-web smi-scheduler
sudo systemctl status smi-web smi-scheduler
```

---

## 5) Nginx

### `/etc/nginx/sites-available/smi-platforma`

```nginx
server {
    listen 80;
    server_name <ВАШ_ДОМЕН>;

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/smi-platforma /etc/nginx/sites-enabled/smi-platforma
sudo nginx -t
sudo systemctl reload nginx
```

SSL:

```bash
sudo certbot --nginx -d <ВАШ_ДОМЕН>
```

---

## 6) Smoke-check перед открытием доступа

1. `https://<домен>/` открывается, title/бренд: **SMI-platforma**  
2. регистрация нового пользователя работает  
3. вход/выход работает  
4. подключение Telegram и VK каналов проходит  
5. Шаг 2 и Шаг 3 сохраняют данные и повторно открывают черновики  
6. ручная публикация отрабатывает минимум в 1 канал  
7. `/admin/clients` доступен администратору  
8. `/api/system/health` возвращает 200  
9. есть записи в `logs/system.log` и `logs/errors.log`

---

## 7) Резервные копии

Минимум:

- БД: `snoomi_channels.db`
- `.env`
- `logs/` (для расследований)

Пример nightly backup:

```bash
mkdir -p /opt/smi-backups
cp /opt/smi-platforma/app/snoomi_channels.db /opt/smi-backups/snoomi_channels_$(date +%F).db
find /opt/smi-backups -type f -mtime +14 -delete
```

---

## 8) Rollback (быстрый)

```bash
cd /opt/smi-platforma/app
git log --oneline -n 20
git checkout <PREVIOUS_COMMIT>
sudo systemctl restart smi-web smi-scheduler
```

---

## 9) Что улучшить после первого прод-запуска

1. Перейти с SQLite на PostgreSQL.  
2. Отдельный worker/очередь задач для тяжёлых AI операций.  
3. Мониторинг uptime + алерты (Uptime Kuma/Healthchecks).  
4. Ограничение доступа к `/admin/*` (IP allowlist + 2FA).  
5. WAF/Rate limiting на публичный периметр.
