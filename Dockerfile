FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg curl

RUN pip install --upgrade pip
RUN pip install yt-dlp aiogram==2.25.1

WORKDIR /app
COPY . .

CMD ["python", "bot.py"]
