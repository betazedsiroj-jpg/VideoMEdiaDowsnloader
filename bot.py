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
# НАСТРОЙКИ
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GDRIVE_JSON = os.getenv("GDRIVE_JSON")

TELEGRAM_VIDEO_LIMIT = 2000  # 2 GB
DOWNLOAD_DIR = "downloads"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
executor_pool = ThreadPoolExecutor(max_workers=3)

# =========================
# GOOGLE DRIVE
# =========================
drive = None
if GDRIVE_JSON:
    try:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(GDRIVE_JSON),
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        drive = build("drive", "v3", credentials=creds)
        print("✅ Google Drive включен")
    except Exception as e:
        print(f"⚠️ Google Drive отключен: {e}")

def upload_to_drive_sync(file_path):
    if not drive:
        raise Exception("Google Drive не настроен")
    
    file_metadata = {"name": os.path.basename(file_path)}
    media = MediaFileUpload(file_path, mimetype="video/mp4", resumable=True)
    
    file = drive.files().create(
        body=file_metadata,
        media_body=media,
        fields="id"
    ).execute()
    
    drive.permissions().create(
        fileId=file['id'],
        body={'type': 'anyone', 'role': 'reader'}
    ).execute()
    
    return f"https://drive.google.com/file/d/{file['id']}/view"

async def upload_to_drive(file_path):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor_pool, upload_to_drive_sync, file_path)

# =========================
# СЖАТИЕ ВИДЕО
# =========================
async def compress_video(input_path, output_path, target_mb):
    try:
        # Получаем длительность
        probe = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            input_path,
            stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await probe.communicate()
        duration = float(stdout.decode().strip())
        
        # Вычисляем битрейт
        target_bits = target_mb * 1024 * 1024 * 8 * 0.95
        bitrate = max(int(target_bits / duration) - 128000, 500000)
        
        # Сжимаем
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", input_path,
            "-c:v", "libx264",
            "-b:v", str(bitrate),
            "-preset", "medium",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y", output_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
        
        await process.communicate()
        return process.returncode == 0
    
    except Exception:
        return False

# =========================
# КОМАНДЫ
# =========================
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer(
        "👋 Привет! Отправь ссылку на видео\n\n"
        "📱 Поддержка:\n"
        "• YouTube / Shorts\n"
        "• Instagram / Reels\n"
        "• TikTok / Facebook\n\n"
        "🎬 До 2 GB — отправлю видео\n"
        "☁️ Больше 2 GB — загружу в Drive\n\n"
        "⚡ Качество сохраняется!"
    )

# =========================
# СКАЧИВАНИЕ
# =========================
@dp.message_handler()
async def download_video(message: types.Message):
    url = message.text.strip()
    user_id = message.from_user.id
    status = await message.answer("⏳ Скачиваю...")
    
    template = f"{DOWNLOAD_DIR}/{user_id}_%(id)s.%(ext)s"
    
    # Определяем платформу
    is_instagram = "instagram.com" in url.lower()
    is_shorts = "shorts" in url.lower() or "youtu.be" in url.lower()
    
    # Формируем команду
    if is_instagram:
        cmd = [
            "yt-dlp", "--no-playlist",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "-o", template, url
        ]
    elif is_shorts:
        cmd = ["yt-dlp", "-f", "best", "--no-playlist", "-o", template, url]
    else:
        cmd = [
            "yt-dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "--no-playlist",
            "-o", template, url
        ]
    
    try:
        # Скачиваем
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
        
        if process.returncode != 0:
            error = stderr.decode('utf-8', errors='ignore')
            print(f"Ошибка для {url}: {error[:500]}")
            
            if "private" in error.lower() or "login" in error.lower():
                await status.edit_text("❌ Видео приватное или требует авторизации")
            elif "unavailable" in error.lower():
                await status.edit_text("❌ Видео недоступно или удалено")
            else:
                await status.edit_text("❌ Не удалось скачать\nПроверьте ссылку")
            return
        
        # Ищем файл
        files = glob.glob(f"{DOWNLOAD_DIR}/{user_id}_*")
        if not files:
            await status.edit_text("❌ Файл не найден")
            return
        
        file_path = files[0]
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        
        # До 2 GB - отправляем как видео
        if size_mb <= TELEGRAM_VIDEO_LIMIT:
            await status.edit_text(f"📤 Отправляю ({size_mb:.1f} MB)...")
            
            with open(file_path, "rb") as video:
                await message.answer_video(
                    video,
                    caption=f"🎬 {size_mb:.1f} MB",
                    supports_streaming=True
                )
            
            await status.delete()
        
        # Больше 2 GB - сжимаем
        else:
            await status.edit_text(f"🗜️ Сжимаю ({size_mb:.1f} MB → 2 GB)...")
            
            compressed = f"{DOWNLOAD_DIR}/{user_id}_compressed.mp4"
            
            if await compress_video(file_path, compressed, TELEGRAM_VIDEO_LIMIT):
                comp_size = os.path.getsize(compressed) / (1024 * 1024)
                
                await status.edit_text(f"📤 Отправляю ({comp_size:.1f} MB)...")
                
                with open(compressed, "rb") as video:
                    await message.answer_video(
                        video,
                        caption=f"🎬 {comp_size:.1f} MB (сжато)",
                        supports_streaming=True
                    )
                
                await status.delete()
            
            # Если сжатие не помогло - Drive
            elif drive:
                await status.edit_text(f"☁️ Загружаю в Drive ({size_mb:.1f} MB)...")
                
                try:
                    link = await upload_to_drive(file_path)
                    await status.edit_text(
                        f"✅ Загружено!\n\n"
                        f"📦 {size_mb:.1f} MB\n"
                        f"🔗 {link}"
                    )
                except Exception:
                    await status.edit_text(
                        f"❌ Слишком большой файл\n"
                        f"Скачай напрямую: {url}"
                    )
            
            else:
                await status.edit_text(f"❌ Видео {size_mb:.1f} MB (лимит 2 GB)")
    
    except asyncio.TimeoutError:
        await status.edit_text("❌ Таймаут (10 мин)")
    
    except Exception as e:
        print(f"Ошибка: {e}")
        await status.edit_text(f"❌ Ошибка: {str(e)[:200]}")
    
    finally:
        # Удаляем файлы
        for f in glob.glob(f"{DOWNLOAD_DIR}/{user_id}_*"):
            try:
                os.remove(f)
            except:
                pass

# =========================
# ЗАПУСК
# =========================
if __name__ == "__main__":
    print("🚀 Бот запущен!")
    print(f"🎬 Лимит: {TELEGRAM_VIDEO_LIMIT} MB")
    print(f"☁️ Drive: {'Да' if drive else 'Нет'}")
    
    try:
        executor.start_polling(dp, skip_updates=True)
    finally:
        executor_pool.shutdown(wait=True)
