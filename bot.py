import os
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
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")

DOWNLOAD_DIR = "downloads"
MAX_SIZE_MB = 45
GDRIVE_FILE = "gdrive.json"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# =========================
# GOOGLE DRIVE
# =========================

SCOPES = ["https://www.googleapis.com/auth/drive"]

creds = service_account.Credentials.from_service_account_file(
    GDRIVE_FILE,
    scopes=SCOPES
)

drive_service = build("drive", "v3", credentials=creds)

# =========================
# BOT
# =========================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# =========================
# START
# =========================

@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer(
        "👋 Отправь ссылку на видео\n\n"
        "YouTube / Shorts / Instagram / TikTok / Facebook\n"
        "До 45MB — пришлю файлом\n"
        "Больше 45MB — загружу на Google Drive"
    )

# =========================
# GOOGLE DRIVE UPLOAD
# =========================

def upload_to_drive(file_path):
    file_metadata = {"name": os.path.basename(file_path)}
    media = MediaFileUpload(file_path, resumable=True)
    file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id"
    ).execute()

    drive_service.permissions().create(
        fileId=file["id"],
        body={"type": "anyone", "role": "reader"}
    ).execute()

    return f"https://drive.google.com/file/d/{file['id']}/view"

# =========================
# DOWNLOADER
# =========================

@dp.message_handler()
async def downloader(message: types.Message):
    url = message.text.strip()
    await message.answer("⏳ Скачиваю...")

    output_path = f"{DOWNLOAD_DIR}/{message.from_user.id}.mp4"

    cmd = [
        "yt-dlp",
        "-f", "bv*+ba/best",
        "--merge-output-format", "mp4",
        "-o", output_path,
        url
    ]

    try:
        process = await asyncio.create_subprocess_exec(*cmd)
        await process.communicate()
    except:
        await message.answer("❌ Ошибка скачивания")
        return

    if not os.path.exists(output_path):
        await message.answer("❌ Видео не найдено")
        return

    size_mb = os.path.getsize(output_path) / (1024 * 1024)

    # SMALL VIDEO
    if size_mb <= MAX_SIZE_MB:
        with open(output_path, "rb") as f:
            await message.answer_document(f)

        os.remove(output_path)
        return

    # BIG VIDEO → GOOGLE DRIVE
    await message.answer("📤 Видео большое, загружаю на Google Drive...")

    link = upload_to_drive(output_path)
    os.remove(output_path)

    await message.answer(
        f"❌ Видео слишком большое: {size_mb:.1f} MB\n\n"
        f"Вот ссылка на Google Drive:\n{link}"
    )

# =========================
# RUN
# =========================

if __name__ == "__main__":
    print("🚀 Bot started")
    executor.start_polling(dp, skip_updates=True)
