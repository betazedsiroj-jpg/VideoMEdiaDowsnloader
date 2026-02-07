FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем requirements
COPY requirements.txt .

# Обновляем pip и устанавливаем зависимости
# ВАЖНО: обновляем yt-dlp до последней версии
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -U yt-dlp && \
    pip install --no-cache-dir -r requirements.txt

# Копируем бота
COPY bot.py .

# Создаем папку для скачивания
RUN mkdir -p downloads

# Запускаем бота
CMD ["python", "-u", "bot.py"]
