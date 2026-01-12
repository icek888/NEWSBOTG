# Продакшен-деплой: Инструкция (Docker Hub)

## Схема работы

```
Git Push → github.com/icek888/NEWSBOTG
                     |
                     └─→ GitHub Actions: Build & Push to Docker Hub
                         (публичный образ - можно качать без токена)

Ты руками на сервере:
  docker pull icewind777/newsbotg:latest
  docker-compose -f docker-compose.prod.yml up -d
```

---

## GitHub Actions (автоматически)

При пуше в `main`:
1. Собирает Docker образ
2. Пушит в `docker.io/icewind777/newsbotg:latest` (Docker Hub)
3. Показывает команду для pull в Summary

---

## Необходимые настройки

### 1. Docker Hub токен

1. Зарегистрируйся на https://hub.docker.com (если нет)
2. Перейди в Account Settings → Security
3. Создай Access Token
4. Добавь токен в GitHub Secrets:

**GitHub Repo → Settings → Secrets and variables → Actions → New repository secret:**

| Name | Secret |
|------|--------|
| `DOCKERHUB_TOKEN` | твой_dockerhub_token |

### 2. Сделай Docker Hub образ публичным

1. Перейди на https://hub.docker.com/u/icewind777/
2. Найди репозиторий `newsbotg`
3. Settings → Visibility → **Public**

Теперь образ можно скачивать без авторизации!

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

## Ручной деплой

### На сервере (deploy.sh)

```bash
#!/bin/bash
cd /opt/newsbotg

echo "Pulling new image..."
docker pull icewind777/newsbotg:latest

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

Деплой одной командой:
```bash
./deploy.sh
```

---

## Команды управления

```bash
# Логи
docker-compose -f docker-compose.prod.yml logs -f

# Статус
docker-compose -f docker-compose.prod.yml ps

# Перезапуск
docker-compose -f docker-compose.prod.yml restart

# Остановка
docker-compose -f docker-compose.prod.yml down
```

---

## Проверка Docker Hub

```bash
# На сервере проверь доступность образа
docker pull icewind777/newsbotg:latest

# Если не работает - проверь публичность:
# https://hub.docker.com/u/icewind777/
```

---

## Полезные ссылки

- Docker Hub: https://hub.docker.com/u/icewind777/
- GitHub Actions: https://github.com/icek888/NEWSBOTG/actions
- GitHub Issues: https://github.com/icek888/NEWSBOTG/issues
