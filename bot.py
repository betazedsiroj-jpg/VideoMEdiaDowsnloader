import os
import subprocess
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

print("BOT FILE STARTED")

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer("👋 Пришли ссылку на видео")


@dp.message_handler()
async def downloader(message: types.Message):
    url = message.text.strip()

    await message.answer("⏳ Скачиваю...")

    output_path = f"{DOWNLOAD_DIR}/video.mp4"

    cmd = [
        "yt-dlp",
        "-f", "bv*[ext=mp4][height<=1080]+ba/best",
        "--merge-output-format", "mp4",
        "-o", output_path,
        url
    ]

    subprocess.run(cmd)

    if not os.path.exists(output_path):
        await message.answer("❌ Ошибка скачивания")
        return

    size_mb = os.path.getsize(output_path) / (1024 * 1024)

    if size_mb > 45:
        await message.answer(
            "❌ Видео слишком большое для Telegram\n"
            f"Скачай напрямую:\n{url}"
        )
        os.remove(output_path)
        return

    with open(output_path, "rb") as f:
        await message.answer_document(f)

    os.remove(output_path)


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
