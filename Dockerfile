FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Обновляем pip и устанавливаем Python пакеты
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    yt-dlp \
    aiogram==2.25.1 \
    google-auth \
    google-auth-oauthlib \
    google-auth-httplib2 \
    google-api-python-client

# Рабочая директория
WORKDIR /app

# Копируем бота
COPY bot.py .

# Создаем папку для скачивания
RUN mkdir -p downloads

# Запускаем бота
CMD ["python", "-u", "bot.py"]
