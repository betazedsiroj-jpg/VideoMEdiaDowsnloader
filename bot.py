import os
import subprocess
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# обновляем yt-dlp при старте
subprocess.run(["yt-dlp", "-U"])


@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer("👋 Пришли ссылку на видео")


@dp.message_handler()
async def downloader(message: types.Message):
    url = message.text.strip()
    await message.answer("⏳ Скачиваю...")

    output = f"{DOWNLOAD_DIR}/video.mp4"

    cmd = [
        "yt-dlp",
        "-f", "bv*[ext=mp4]+ba[ext=m4a]/best",
        "-o", output,
        url
    ]

    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        await message.answer("❌ Ошибка скачивания")
        print(e)
        return

    if not os.path.exists(output):
        await message.answer("❌ Файл не найден")
        return

    size_mb = os.path.getsize(output) / 1024 / 1024

    if size_mb > 45:
        await message.answer(f"⚠️ Видео слишком большое ({round(size_mb)} MB)\nВот ссылка:\n{url}")
        os.remove(output)
        return

    with open(output, "rb") as f:
        await message.answer_document(f)

    os.remove(output)


if __name__ == "__main__":
    print("BOT FILE STARTED")
    executor.start_polling(dp, skip_updates=True)
