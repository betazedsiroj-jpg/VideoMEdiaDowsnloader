import os
import json
import asyncio
import glob
from concurrent.futures import ThreadPoolExecutor
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

# ThreadPoolExecutor для блокирующих операций с Drive
executor_pool = ThreadPoolExecutor(max_workers=3)

# =========================
# GOOGLE DRIVE
# =========================
creds = service_account.Credentials.from_service_account_info(
    json.loads(GDRIVE_JSON),
    scopes=["https://www.googleapis.com/auth/drive"]
)
drive = build("drive", "v3", credentials=creds)

def upload_to_drive_sync(file_path):
    """Синхронная загрузка в Google Drive"""
    try:
        file_metadata = {
            "name": os.path.basename(file_path),
            "mimeType": "video/mp4"
        }
        media = MediaFileUpload(
            file_path,
            mimetype="video/mp4",
            resumable=True
        )
        
        file = drive.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink"
        ).execute()
        
        # Делаем файл доступным по ссылке
        drive.permissions().create(
            fileId=file['id'],
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
        
        return file.get('webViewLink') or f"https://drive.google.com/file/d/{file['id']}/view"
    
    except Exception as e:
        raise Exception(f"Ошибка загрузки в Drive: {str(e)}")

async def upload_to_drive(file_path):
    """Асинхронная обертка для загрузки в Drive"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        executor_pool,
        upload_to_drive_sync,
        file_path
    )

# =========================
# COMMANDS
# =========================
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer(
        "👋 Привет! Отправь ссылку на видео\n\n"
        "📱 Поддерживаю:\n"
        "• YouTube / Shorts\n"
        "• Instagram / Reels\n"
        "• TikTok\n"
        "• Facebook\n\n"
        "📦 До 45 MB — пришлю файлом\n"
        "☁️ Больше 45 MB — загружу в Google Drive"
    )

# =========================
# DOWNLOADER
# =========================
@dp.message_handler()
async def downloader(message: types.Message):
    url = message.text.strip()
    user_id = message.from_user.id
    status = await message.answer("⏳ Скачиваю...")
    
    filename_template = f"{DOWNLOAD_DIR}/{user_id}_%(id)s.%(ext)s"
    
    # Проверяем тип платформы
    is_instagram = "instagram.com" in url.lower()
    
    # Команда для yt-dlp
    if is_instagram:
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "-o", filename_template,
            url
        ]
    else:
        cmd = [
            "yt-dlp",
            "-f", "best[ext=mp4]/bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "--no-playlist",
            "-o", filename_template,
            url
        ]
    
    file_path = None
    
    try:
        # Скачиваем видео
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
        
        _, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=300  # 5 минут
        )
        
        if process.returncode != 0:
            error = stderr.decode('utf-8', errors='ignore')
            
            if "login" in error.lower() or "private" in error.lower():
                await status.edit_text(
                    "❌ Аккаунт приватный или требует авторизации"
                )
            else:
                await status.edit_text(
                    "❌ Не удалось скачать видео\n"
                    "Проверьте ссылку"
                )
            return
        
        # Ищем скачанный файл
        files = glob.glob(f"{DOWNLOAD_DIR}/{user_id}_*")
        if not files:
            await status.edit_text("❌ Видео не найдено после скачивания")
            return
        
        file_path = files[0]
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        
        # Маленький файл - отправляем напрямую
        if size_mb <= MAX_SIZE_MB:
            await status.edit_text(f"📤 Отправляю ({size_mb:.1f} MB)...")
            
            with open(file_path, "rb") as video:
                await message.answer_video(video)
            
            await status.delete()
            return
        
        # Большой файл - загружаем в Google Drive
        await status.edit_text(
            f"☁️ Видео большое ({size_mb:.1f} MB)\n"
            f"Загружаю в Google Drive..."
        )
        
        try:
            drive_link = await upload_to_drive(file_path)
            
            await status.edit_text(
                f"✅ Видео загружено в Google Drive!\n\n"
                f"📦 Размер: {size_mb:.1f} MB\n"
                f"🔗 Ссылка:\n{drive_link}\n\n"
                f"💡 Можешь скачать или посмотреть онлайн"
            )
        
        except Exception as e:
            await status.edit_text(
                f"❌ Ошибка загрузки в Google Drive\n\n"
                f"Видео слишком большое ({size_mb:.1f} MB)\n"
                f"Скачай напрямую:\n{url}"
            )
    
    except asyncio.TimeoutError:
        await status.edit_text(
            "❌ Превышено время ожидания (5 мин)"
        )
    
    except Exception as e:
        await status.edit_text(
            f"❌ Произошла ошибка:\n{str(e)[:300]}"
        )
    
    finally:
        # Всегда очищаем файлы пользователя
        for f in glob.glob(f"{DOWNLOAD_DIR}/{user_id}_*"):
            try:
                os.remove(f)
            except:
                pass

# =========================
# START
# =========================
if __name__ == "__main__":
    print("🚀 Бот запущен с поддержкой Google Drive!")
    try:
        executor.start_polling(dp, skip_updates=True)
    finally:
        executor_pool.shutdown(wait=True)
