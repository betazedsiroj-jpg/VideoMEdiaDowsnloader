import os
import subprocess
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

print("BOT FILE STARTED")

# ===== TOKEN =====
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ===== /start =====
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer("👋 Пришли ссылку на видео")

# ===== Downloader =====
@dp.message_handler()
async def downloader(message: types.Message):
    url = message.text.strip()
    await message.answer("⏳ Скачиваю...")

    output_path = f"{DOWNLOAD_DIR}/video.mp4"

    cmd = [
        "python",
        "-m",
        "yt_dlp",
        "-f",
        "bestvideo+bestaudio/best",
        "--merge-output-format",
        "mp4",
        "-o",
        output_path,
        url
    ]

    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        await message.answer("❌ Ошибка скачивания")
        print(e)
        return

    if not os.path.exists(output_path):
        await message.answer("❌ Видео не найдено после скачивания")
        return

    size_mb = os.path.getsize(output_path) / (1024 * 1024)

    if size_mb > 45:
        await message.answer(
            "❌ Видео больше 45MB\n"
            f"Скачай вручную:\n{url}"
        )
        os.remove(output_path)
        return

    with open(output_path, "rb") as video:
        await message.answer_video(video)

    os.remove(output_path)

# ===== START BOT =====
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
