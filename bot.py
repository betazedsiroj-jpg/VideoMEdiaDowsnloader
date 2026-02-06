print("BOT FILE STARTED")

import os
import subprocess
from config import BOT_TOKEN
from aiogram import Bot, Dispatcher, types

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)


DOWNLOAD_DIR = "downloads"

if not os.path.exists(DOWNLOAD_DIR):
    os.mkdir(DOWNLOAD_DIR)


def is_youtube_long(url: str):
    return "youtube.com/watch" in url or "youtu.be/" in url


def is_short_platform(url: str):
    url = url.lower()
    return (
        "instagram.com" in url or
        "facebook.com" in url or
        "pinterest.com" in url or
        "youtube.com/shorts" in url
    )


@dp.message_handler(commands=["start"])
async def start_cmd(message: types.Message):
    await message.answer(
        "👋 Отправь ссылку.\n\n"
        "• Shorts / Reels / Pinterest / Facebook → получишь видео\n"
        "• Обычный YouTube → получишь ссылку на скачивание"
    )


@dp.message_handler(lambda message: message.text.startswith("http"))
async def downloader(message: types.Message):
    url = message.text.strip()

    # Обычный YouTube
    if is_youtube_long(url):
        await message.answer(
            "📥 Это длинное YouTube видео.\n"
            "Telegram не позволяет отправлять такие большие файлы.\n\n"
            f"Скачай напрямую:\n{url}"
        )
        return

    # Shorts / Reels
    if not is_short_platform(url):
        await message.answer("❌ Платформа не поддерживается.")
        return

    await message.answer("⏳ Скачиваю видео...")

    # очистка папки
    for f in os.listdir(DOWNLOAD_DIR):
        os.remove(os.path.join(DOWNLOAD_DIR, f))

    subprocess.run([
        "yt-dlp",
        "-f", "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/best",
        "--merge-output-format", "mp4",
        "-o", f"{DOWNLOAD_DIR}/video.mp4",
        url
    ])

    file_path = f"{DOWNLOAD_DIR}/video.mp4"

    if not os.path.exists(file_path):
        await message.answer("❌ Ошибка скачивания.")
        return

    size_mb = os.path.getsize(file_path) / (1024 * 1024)

    if size_mb > 45:
        await message.answer(
            "❌ Видео слишком большое для Telegram.\n"
            f"Скачай напрямую:\n{url}"
        )
        os.remove(file_path)
        return

    with open(file_path, "rb") as f:
        await message.answer_do_



