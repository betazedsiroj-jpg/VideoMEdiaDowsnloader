import os
import asyncio
import glob
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

# === TOKEN ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# === SETTINGS ===
DOWNLOAD_DIR = "downloads"
MAX_SIZE_MB = 45
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# === START ===
@dp.message_handler(commands=["start"])
async def start_cmd(message: types.Message):
    await message.answer(
        "👋 Отправь ссылку на видео\n\n"
        "YouTube / Shorts / Instagram / TikTok / Facebook\n"
        "До 45MB — пришлю файлом\n"
        "Больше 45MB — дам ссылку"
    )


# === DOWNLOADER ===
@dp.message_handler()
async def downloader(message: types.Message):
    url = message.text.strip()
    user_id = message.from_user.id

    status = await message.answer("⏳ Скачиваю...")

    filename = f"{DOWNLOAD_DIR}/{user_id}_video.mp4"

    cmd = [
        "yt-dlp",
        "-f", "best[ext=mp4]/best",
        "--no-playlist",
        "-o", filename,
        url
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )

        _, stderr = await process.communicate()

        if process.returncode != 0:
            await status.edit_text(
                "❌ Ошибка при скачивании\n"
                "Возможно ссылка приватная или защищена"
            )
            return

        if not os.path.exists(filename):
            await status.edit_text("❌ Видео не найдено")
            return

        size_mb = os.path.getsize(filename) / (1024 * 1024)

        if size_mb > MAX_SIZE_MB:
            await status.edit_text(
                f"❌ Видео слишком большое: {size_mb:.1f} MB\n\n"
                f"Вот ссылка для скачивания:\n{url}"
            )
            os.remove(filename)
            return

        await status.edit_text("📤 Отправляю видео...")

        with open(filename, "rb") as video:
            await message.answer_document(video)

        os.remove(filename)
        await status.delete()

    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {str(e)[:200]}")


# === RUN ===
if __name__ == "__main__":
    print("🚀 BOT STARTED")
    executor.start_polling(dp, skip_updates=True)
