# Продакшен-деплой: Инструкция

## Схема работы

```
Git Push → https://github.com/icek888/NEWSBOTG
                     |
                     └─→ GitHub Actions: Build & Push to ghcr.io
                         (тебё приходит уведомление с командой pull)

Ты руками на сервере:
  docker pull ghcr.io/icek888/newsbotg:latest
  docker-compose -f docker-compose.prod.yml up -d
```

---

## GitHub Actions (автоматически)

При пуше в `main`:
1. Собирает Docker образ
2. Пушит в `ghcr.io/icek888/newsbotg:latest`
3. Показывает команду для pull в Summary

**Secrets НЕ нужны!** Используется встроенный `GITHUB_TOKEN`.

---

## Подготовка сервера

### 1. Установить Docker и Docker Compose

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
usermod -aG docker ubuntu
```

### 2. Клонировать репозиторий

```bash
mkdir -p /opt/newsbotg
cd /opt/newsbotg

git clone https://github.com/icek888/NEWSBOTG.git .
```

### 3. Настроить `.env`

```bash
cp .env.example .env
nano .env
```

Обязательно заполнить:
```bash
# Telegram
API_ID=твой_api_id
API_HASH=твой_api_hash
TELEGRAM_BOT_TOKEN=твой_токен
TELEGRAM_CHANNEL_ID=твой_канал
TELEGRAM_ADMIN_CHAT_ID=твой_админ_чат

# OpenRouter
OPENROUTER_API_KEY=твой_ключ

# PostgreSQL
POSTGRES_USER=newsuser
POSTGRES_PASSWORD=сложный_пароль
POSTGRES_DB=newsdb
```

### 4. Первый запуск

```bash
cd /opt/newsbotg

# Запускаем
docker-compose -f docker-compose.prod.yml up -d

# Применяем миграции
docker-compose -f docker-compose.prod.yml exec app alembic upgrade head

# Инициализируем источники
docker-compose -f docker-compose.prod.yml exec app python -c "from app.main import init_db_data; import asyncio; asyncio.run(init_db_data())"

# Проверяем логи
docker-compose -f docker-compose.prod.yml logs -f app
```

---

## Ручной деплой (каждый раз)

### Способ 1: Из GitHub Summary

После пуша в main зайди в GitHub Actions → последний запуск → Summary

Там будет команда:
```bash
docker pull ghcr.io/icek888/newsbotg:latest
```

### Способ 2: Быстрый скрипт на сервере

Создай файл `deploy.sh` на сервере:

```bash
#!/bin/bash
cd /opt/newsbotg

echo "Pulling new image..."
docker pull ghcr.io/icek888/newsbotg:latest

echo "Restarting containers..."
docker-compose -f docker-compose.prod.yml up -d

echo "Running migrations..."
docker-compose -f docker-compose.prod.yml exec -T app alembic upgrade head

echo "Done! Logs:"
docker-compose -f docker-compose.prod.yml logs --tail=20 app
```

Сделай исполняемым:
```bash
chmod +x deploy.sh
```

Теперь деплой одной командой:
```bash
./deploy.sh
```

---

## Команды управления

```bash
# Логи (в реальном времени)
docker-compose -f docker-compose.prod.yml logs -f

# Статус контейнеров
docker-compose -f docker-compose.prod.yml ps

# Перезапуск
docker-compose -f docker-compose.prod.yml restart

# Полная остановка
docker-compose -f docker-compose.prod.yml down

# Войти в контейнер
docker-compose -f docker-compose.prod.yml exec app bash
```

---

## Локальный запуск

### С PostgreSQL (как в проде)

```bash
docker-compose up -d
```

### С SQLite (для разработки)

```bash
python -m app.main
```

---

## Резервное копирование

### PostgreSQL dump

```bash
# Одноразовый бэкап
docker-compose -f docker-compose.prod.yml exec db pg_dump -U newsuser newsdb > backup_$(date +%Y%m%d).sql

# Восстановление
cat backup_20250112.sql | docker-compose -f docker-compose.prod.yml exec -T db psql -U newsuser newsdb
```

### Автоматический бэкап (cron)

Добавь в crontab (`crontab -e`):

```bash
# Бэкап каждый день в 2 ночи
0 2 * * * cd /opt/newsbotg && docker-compose -f docker-compose.prod.yml exec -T db pg_dump -U newsuser newsdb > /backups/news_$(date +\%Y\%m\%d).sql
```

---

## Траблшутинг

### Контейнер не стартует

```bash
# Логи
docker-compose -f docker-compose.prod.yml logs app

# Статус
docker-compose -f docker-compose.prod.yml ps

# Проверить конфиг
docker-compose -f docker-compose.prod.yml config
```

### Бот не отвечает

```bash
# Проверить .env
docker-compose -f docker-compose.prod.yml exec app python -c "from app.config import settings; print(settings.telegram_bot_token)"

# Проверить логи
docker-compose -f docker-compose.prod.yml logs app | grep -i telegram
```

### PostgreSQL проблемы

```bash
# Логи БД
docker-compose -f docker-compose.prod.yml logs db

# Подключиться к БД
docker-compose -f docker-compose.prod.yml exec db psql -U newsuser newsdb

# Проверить подключение из app
docker-compose -f docker-compose.prod.yml exec app python -c "from app.database import engine; print(engine.url)"
```

---

## Структура файлов

```
/opt/newsbotg/
├── .env                    # твоя конфигурация
├── docker-compose.prod.yml # продакшен compose
├── bot_session.session     # telegram сессия
├── images/                 # кэш изображений
└── deploy.sh               # скрипт деплоя (опционально)
```

---

## Полезные ссылки

- GitHub Actions: https://github.com/icek888/NEWSBOTG/actions
- Container Registry: https://ghcr.io/icek888/newsbotg
- GitHub Issues: https://github.com/icek888/NEWSBOTG/issues
