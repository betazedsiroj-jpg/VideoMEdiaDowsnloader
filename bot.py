import os
import subprocess
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

# ===== НАСТРОЙКИ =====

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")

DOWNLOAD_DIR = "downloads"
MAX_SIZE_MB = 45

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ===== BOT =====

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# ===== START =====

@dp.message_handler(commands=["start"])
async def start_cmd(message: types.Message):
    await message.answer(
        "👋 Отправь ссылку на видео\n"
        "YouTube / Shorts / Instagram / TikTok / Facebook\n\n"
        "Видео до 45MB пришлю файлом\n"
        "Больше 45MB — дам ссылку"
    )

# ===== DOWNLOAD HANDLER =====

@dp.message_handler()
async def downloader(message: types.Message):

    url = message.text.strip()
    await message.answer("⏳ Скачиваю...")

    output_path = f"{DOWNLOAD_DIR}/video.mp4"

    cmd = [
        "yt-dlp",
        "-f", "bv*[height<=720]+ba/best",
        "--merge-output-format", "mp4",
        "-o", output_path,
        url
    ]

    try:
        subprocess.run(cmd, check=True)
    except Exception:
        await message.answer("❌ Ошибка при скачивании")
        return

    if not os.path.exists(output_path):
        await message.answer("❌ Видео не найдено")
        return

    size_mb = os.path.getsize(output_path) / (1024 * 1024)

    # если больше лимита
    if size_mb > MAX_SIZE_MB:
        await message.answer(
            "⚠️ Видео больше 45MB\n"
            "Скачай по ссылке:\n"
            f"{url}"
        )
        os.remove(output_path)
        return

    # если влазит
    with open(output_path, "rb") as video:
        await message.answer_document(video)

    os.remove(output_path)

# ===== RUN =====

if __name__ == "__main__":
    print("🚀 BOT STARTED")
    executor.start_polling(dp, skip_updates=True)
