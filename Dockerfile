FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем Python зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем приложение
COPY . .

# Создаём директорию для кэша изображений
RUN mkdir -p images/cache

# Переменные окружения (по умолчанию)
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Запуск
CMD ["python", "-m", "app.main"]
