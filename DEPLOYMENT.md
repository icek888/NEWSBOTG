# Продакшен-деплой: Инструкция

## Обновлённые файлы

| Файл | Изменения |
|------|-----------|
| `.gitignore` | Добавлены все ненужные файлы (кэш, БД, сессии, docs) |
| `Dockerfile` | Добавлен `libpq-dev` для PostgreSQL |
| `docker-compose.yml` | **Локальная разработка**: PostgreSQL + app |
| `docker-compose.prod.yml` | **Продакшен**: использует образ из GHCR |
| `requirements.txt` | Добавлен `asyncpg>=0.29.0` |
| `.env.example` | Добавлены переменные PostgreSQL |
| `.github/workflows/deploy.yml` | GitHub Actions: build → push → deploy |

---

## GitHub Secrets

Нужно добавить в репозиторий (Settings → Secrets and variables → Actions):

| Secret | Описание | Пример |
|--------|----------|--------|
| `SERVER_HOST` | IP или домен сервера | `192.168.1.100` или `example.com` |
| `SERVER_USER` | Пользователь SSH | `root` или `ubuntu` |
| `SERVER_SSH_KEY` | Приватный SSH ключ | `-----BEGIN OPENSSH PRIVATE KEY-----...` |
| `SERVER_PORT` | Порт SSH (опционально) | `22` |

---

## Схема деплоя

```
Git Push → GitHub Actions:
                     |
                     ├─→ Build Docker image
                     ├─→ Push to ghcr.io (GitHub Container Registry)
                     └─→ SSH to server:
                          ├─ docker pull ghcr.io/...:latest
                          └─ docker-compose -f docker-compose.prod.yml up -d
```

---

## Подготовка сервера

### 1. Установить Docker и Docker Compose

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
usermod -aG docker ubuntu  # или ваш пользователь
```

### 2. Создать директорию проекта

```bash
mkdir -p /opt/newsautotg
cd /opt/newsautotg

# Клонировать репозиторий
git clone https://github.com/твой-юзернейм/NewsAutoTG.git .
```

### 3. Создать `.env` файл

```bash
cp .env.example .env
nano .env
```

Заполнить:
```bash
API_ID=твой_api_id
API_HASH=твой_api_hash
TELEGRAM_BOT_TOKEN=твой_токен
TELEGRAM_CHANNEL_ID=твой_канал
TELEGRAM_ADMIN_CHAT_ID=твой_админ_чат

OPENROUTER_API_KEY=твой_ключ

POSTGRES_USER=newsuser
POSTGRES_PASSWORD=сложный_пароль
POSTGRES_DB=newsdb
```

### 4. Создать SSH ключи (если нет)

```bash
ssh-keygen -t ed25519 -C "github-actions"
# Добавить публичный ключ на сервер
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
```

Приватный ключ (`id_ed25519`) добавить в GitHub Secrets.

---

## Первая установка на сервере

```bash
cd /opt/newsautotg

# Создаём docker-compose.prod.yml (уже есть в репо)
# Либо копируем из docker-compose.yml и меняем image

# Запускаем
docker-compose -f docker-compose.prod.yml up -d

# Применяем миграции
docker-compose -f docker-compose.prod.yml exec app alembic upgrade head

# Инициализируем источники (если есть в main.py)
docker-compose -f docker-compose.prod.yml exec app python -c "from app.main import init_db_data; import asyncio; asyncio.run(init_db_data())"

# Проверяем логи
docker-compose -f docker-compose.prod.yml logs -f
```

---

## Последующие деплои

После каждого пуша в `main` ветку GitHub Actions автоматически:
1. Соберёт Docker образ
2. Запушит в `ghcr.io`
3. Подключится к серверу по SSH
4. Выполнит `docker pull` и `docker-compose up -d`

---

## Команды для управления

```bash
# Логи
docker-compose -f docker-compose.prod.yml logs -f app

# Статус
docker-compose -f docker-compose.prod.yml ps

# Перезапуск
docker-compose -f docker-compose.prod.yml restart

# Остановка
docker-compose -f docker-compose.prod.yml down

# Обновить вручную (без GitHub Actions)
git pull
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml up -d --build
```

---

## Локальный запуск (с PostgreSQL)

```bash
# Разработка
docker-compose up -d

# Применить миграции
docker-compose exec app alembic upgrade head

# Логи
docker-compose logs -f
```

---

## Локальный запуск (с SQLite)

```bash
# Просто запуск без Docker
python -m app.main

# Или с venv
source venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

---

## Структура БД

- **Локально**: SQLite (`ai_news.db`)
- **Docker**: PostgreSQL (`newsdb`)

Миграции Alembic работают с обеими БД!

---

## Мониторинг

### Проверка здоровья

```bash
# Внутри контейнера
docker-compose exec app curl http://localhost:8000/health

# Или проверить статус контейнера
docker-compose ps
```

### Резервное копирование

```bash
# PostgreSQL dump
docker-compose exec db pg_dump -U newsuser newsdb > backup.sql

# Или автоматический бэкап (cron)
0 2 * * * docker-compose exec -T db pg_dump -U newsuser newsdb > /backups/news_$(date +\%Y\%m\%d).sql
```

---

## Траблшутинг

### Контейнер не стартует

```bash
# Логи
docker-compose logs app

# Проверить переменные
docker-compose config

# Войти в контейнер
docker-compose exec app bash
```

### PostgreSQL не подключается

```bash
# Проверить статус БД
docker-compose logs db

# Проверить подключение
docker-compose exec app python -c "from app.database import engine; print(engine.url)"
```

### Telegram бот не отвечает

```bash
# Проверить токен в .env
docker-compose exec app python -c "from app.config import settings; print(settings.telegram_bot_token)"

# Проверить логи
docker-compose logs app | grep -i telegram
```

---

## Следующие шаги

1. ✅ Добавить GitHub Secrets
2. ✅ Первая установка на сервере
3. ✅ Тестовый пуш в main
4. ✅ Проверить автоматический деплой
5. ➕ Настроить автоматические бэкапы
6. ➕ Добавить мониторинг (Prometheus/Grafana)
7. ➕ Настроить SSL (Let's Encrypt) для домена

---

## Контакты для проблем

GitHub Issues: https://github.com/твой-юзернейм/NewsAutoTG/issues
