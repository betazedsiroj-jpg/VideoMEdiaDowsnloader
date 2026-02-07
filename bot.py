import os
import json
import asyncio
import subprocess
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# =========================
# CONFIG
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GDRIVE_JSON = os.getenv("GDRIVE_JSON")

MAX_SIZE_MB = 45
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")

if not GDRIVE_JSON:
    raise ValueError("GDRIVE_JSON is not set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# =========================
# GOOGLE DRIVE
# =========================

creds = service_account.Credentials.from_service_account_info(
    json.loads(GDRIVE_JSON),
    scopes=["https://www.googleapis.com/auth/drive"]
)

drive = build("drive", "v3", credentials=creds)

def upload_to_drive(file_path):
    file_metadata = {"name": os.path.basename(file_path)}
    media = MediaFileUpload(file_path, resumable=True)
    file = drive.files().create(
        body=file_metadata,
        media_body=media,
        fields="id"
    ).execute()

    return f"https://drive.google.com/file/d/{file['id']}/view"

# =========================
# COMMANDS
# =========================

@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer(
        "👋 Отправь ссылку на видео\n\n"
        "Видео до 45MB — пришлю файлом\n"
        "Больше 45MB — загружу в Google Drive"
    )

# =========================
# DOWNLOADER
# =========================

@dp.message_handler()
async def downloader(message: types.Message):
    url = message.text.strip()
    await message.answer("⏳ Скачиваю...")

    filename = f"{DOWNLOAD_DIR}/{message.from_user.id}.mp4"

    cmd = [
        "yt-dlp",
        "-f", "bv*+ba/best",
        "--merge-output-format", "mp4",
        "-o", filename,
        url
    ]

    process = await asyncio.create_subprocess_exec(*cmd)
    await process.wait()

    if not os.path.exists(filename):
        await message.answer("❌ Ошибка при скачивании")
        return

    size_mb = os.path.getsize(filename) / (1024 * 1024)

    # SMALL FILE
    if size_mb <= MAX_SIZE_MB:
        with open(filename, "rb") as f:
            await message.answer_document(f)
        os.remove(filename)
        return

    # BIG FILE → DRIVE
    await message.answer(f"☁ Видео большое ({size_mb:.1f}MB)\nЗагружаю в Google Drive...")

    link = upload_to_drive(filename)
    os.remove(filename)

    await message.answer(
        f"❌ Видео слишком большое для Telegram\n\n"
        f"☁ Вот ссылка на Google Drive:\n{link}"
    )

# =========================
# START
# =========================

if __name__ == "__main__":
    print("🚀 Bot started")
    executor.start_polling(dp, skip_updates=True)
