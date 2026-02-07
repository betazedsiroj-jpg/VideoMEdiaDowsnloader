# Соберите образ
docker build -f Dockerfile_drive -t video-bot-drive .

# Запустите
docker run -d \
  --name video-bot \
  -e BOT_TOKEN="ваш_токен" \
  -e GDRIVE_JSON='{"type":"service_account"...}' \
  --restart unless-stopped \
  video-bot-drive
