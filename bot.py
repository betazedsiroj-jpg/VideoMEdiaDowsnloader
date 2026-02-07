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

# Лимиты размеров (в MB)
TELEGRAM_VIDEO_LIMIT = 2000  # 2 GB для видео
TELEGRAM_DOC_LIMIT = 50      # 50 MB для документа

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# ThreadPoolExecutor для блокирующих операций
executor_pool = ThreadPoolExecutor(max_workers=3)

# =========================
# GOOGLE DRIVE (опционально)
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
    """Синхронная загрузка в Google Drive"""
    if not drive:
        raise Exception("Google Drive не настроен")
    
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
        
        # Делаем файл публичным
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
# СЖАТИЕ ВИДЕО
# =========================
async def compress_video(input_path, output_path, target_size_mb):
    """
    Сжимает видео до нужного размера с минимальной потерей качества
    """
    try:
        # Получаем длительность видео
        probe_cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            input_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *probe_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        duration = float(stdout.decode().strip())
        
        # Вычисляем битрейт (с запасом 5%)
        target_size_bits = target_size_mb * 1024 * 1024 * 8 * 0.95
        target_bitrate = int(target_size_bits / duration)
        
        # Ограничиваем битрейт
        video_bitrate = max(target_bitrate - 128000, 500000)
        
        # Команда сжатия
        compress_cmd = [
            "ffmpeg",
            "-i", input_path,
            "-c:v", "libx264",
            "-b:v", str(video_bitrate),
            "-maxrate", str(video_bitrate),
            "-bufsize", str(video_bitrate * 2),
            "-preset", "medium",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y",
            output_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *compress_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
        
        await process.communicate()
        
        if process.returncode != 0:
            raise Exception("Ошибка сжатия видео")
        
        return True
    
    except Exception as e:
        raise Exception(f"Не удалось сжать видео: {str(e)}")

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
        "🎬 До 2 GB — пришлю видео в Telegram\n"
        "☁️ Больше 2 GB — загружу в Google Drive\n\n"
        "⚡ Качество максимально сохраняется!"
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
    
    # Определяем платформу
    is_instagram = "instagram.com" in url.lower()
    is_youtube_shorts = "shorts" in url.lower() or "youtu.be" in url.lower()
    
    # Команда для yt-dlp в зависимости от платформы
    if is_instagram:
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "-o", filename_template,
            url
        ]
    elif is_youtube_shorts:
        # Для Shorts используем простой формат
        cmd = [
            "yt-dlp",
            "-f", "best",
            "--no-playlist",
            "--no-check-certificate",
            "-o", filename_template,
            url
        ]
    else:
        # Для обычных видео
        cmd = [
            "yt-dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "--no-playlist",
            "-o", filename_template,
            url
        ]
    
    file_path = None
    compressed_path = None
    
    try:
        # Скачиваем видео
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=600  # 10 минут
        )
        
        if process.returncode != 0:
            error_text = stderr.decode('utf-8', errors='ignore')
            
            # Логируем ошибку для отладки
            print(f"yt-dlp error for {url}: {error_text[:500]}")
            
            if "login" in error_text.lower() or "private" in error_text.lower():
                await status.edit_text("❌ Аккаунт приватный или требует авторизации")
            elif "unavailable" in error_text.lower():
                await status.edit_text("❌ Видео недоступно или удалено")
            elif "not found" in error_text.lower():
                await status.edit_text("❌ Видео не найдено\nПроверьте ссылку")
            else:
                await status.edit_text(
                    "❌ Не удалось скачать видео\n\n"
                    "Попробуйте:\n"
                    "• Проверить ссылку\n"
                    "• Убедиться что видео публичное\n"
                    "• Попробовать другое видео"
                )
            return
        
        # Ищем скачанный файл
        files = glob.glob(f"{DOWNLOAD_DIR}/{user_id}_*")
        if not files:
            await status.edit_text("❌ Видео не найдено после скачивания")
            return
        
        file_path = files[0]
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        
        # СЦЕНАРИЙ 1: Видео до 2 GB - отправляем видео
        if size_mb <= TELEGRAM_VIDEO_LIMIT:
            await status.edit_text(f"🎬 Отправляю видео ({size_mb:.1f} MB)...")
            
            with open(file_path, "rb") as video:
                await message.answer_video(
                    video,
                    caption=f"🎬 {size_mb:.1f} MB | Оригинальное качество",
                    supports_streaming=True
                )
            
            await status.delete()
            return
        
        # СЦЕНАРИЙ 3: Большое видео (больше 2 GB) - сжимаем
        else:
            await status.edit_text(
                f"🗜️ Видео большое ({size_mb:.1f} MB)\n"
                f"Сжимаю до 2 GB с сохранением качества...\n"
                f"Это может занять несколько минут ⏳"
            )
            
            compressed_path = f"{DOWNLOAD_DIR}/{user_id}_compressed.mp4"
            
            try:
                await compress_video(file_path, compressed_path, TELEGRAM_VIDEO_LIMIT)
                
                compressed_size_mb = os.path.getsize(compressed_path) / (1024 * 1024)
                
                await status.edit_text(f"🎬 Отправляю видео ({compressed_size_mb:.1f} MB)...")
                
                with open(compressed_path, "rb") as video:
                    await message.answer_video(
                        video,
                        caption=f"🎬 {compressed_size_mb:.1f} MB | Сжато из {size_mb:.1f} MB",
                        supports_streaming=True
                    )
                
                await status.delete()
                return
            
            except Exception as compress_error:
                # Если сжатие не удалось - пробуем Google Drive
                if drive:
                    await status.edit_text(
                        f"☁️ Загружаю в Google Drive ({size_mb:.1f} MB)..."
                    )
                    
                    try:
                        drive_link = await upload_to_drive(file_path)
                        
                        await status.edit_text(
                            f"✅ Видео загружено в Google Drive!\n\n"
                            f"📦 Размер: {size_mb:.1f} MB\n"
                            f"🔗 Ссылка:\n{drive_link}\n\n"
                            f"💡 Оригинальное качество"
                        )
                        return
                    
                    except Exception:
                        await status.edit_text(
                            f"❌ Не удалось обработать видео\n\n"
                            f"Размер: {size_mb:.1f} MB (слишком большой)\n"
                            f"Скачай напрямую:\n{url}"
                        )
                        return
                else:
                    await status.edit_text(
                        f"❌ Видео слишком большое: {size_mb:.1f} MB\n\n"
                        f"Telegram поддерживает до 2 GB\n"
                        f"Скачай напрямую:\n{url}"
                    )
                    return
    
    except asyncio.TimeoutError:
        await status.edit_text("❌ Превышено время ожидания (10 мин)")
    
    except Exception as e:
        error_msg = str(e)[:300]
        print(f"Error downloading {url}: {error_msg}")
        await status.edit_text(f"❌ Произошла ошибка:\n{error_msg}")
    
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
    print("🚀 Бот запущен!")
    print(f"📦 Лимит документа: {TELEGRAM_DOC_LIMIT} MB")
    print(f"🎬 Лимит видео: {TELEGRAM_VIDEO_LIMIT} MB")
    print(f"☁️ Google Drive: {'включен' if drive else 'отключен'}")
    
    try:
        executor.start_polling(dp, skip_updates=True)
    finally:
        executor_pool.shutdown(wait=True)
