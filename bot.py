import os
import json
import asyncio
import glob
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
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

# Храним выбор пользователей {user_id: url}
user_urls = {}
# Блокировка для предотвращения одновременных скачиваний
user_locks = {}

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
# GOFILE
# =========================
async def upload_to_gofile(file_path):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.gofile.io/getServer") as response:
                if response.status != 200:
                    raise Exception("Не удалось получить сервер GoFile")
                
                server_data = await response.json()
                if server_data['status'] != 'ok':
                    raise Exception("Ошибка API GoFile")
                
                server = server_data['data']['server']
            
            with open(file_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('file', f, filename=os.path.basename(file_path))
                
                async with session.post(
                    f"https://{server}.gofile.io/uploadFile",
                    data=data
                ) as response:
                    if response.status != 200:
                        raise Exception("Ошибка загрузки на GoFile")
                    
                    result = await response.json()
                    if result['status'] != 'ok':
                        raise Exception("Ошибка ответа GoFile")
                    
                    return result['data']['downloadPage']
    
    except Exception as e:
        raise Exception(f"GoFile ошибка: {str(e)}")

# =========================
# СЖАТИЕ ВИДЕО
# =========================
async def compress_video(input_path, output_path, target_mb):
    try:
        probe = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            input_path,
            stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await probe.communicate()
        duration = float(stdout.decode().strip())
        
        target_bits = target_mb * 1024 * 1024 * 8 * 0.95
        bitrate = max(int(target_bits / duration) - 128000, 500000)
        
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
@dp.message_handler(commands=["start", "help"])
async def start(message: types.Message):
    await message.answer(
        "👋 Привет! Отправь ссылку на видео\n\n"
        "📱 Поддержка:\n"
        "• YouTube / Shorts\n"
        "• Instagram / Reels\n"
        "• TikTok / Facebook\n\n"
        "🎬 Выбор качества: 360p, 720p, 1080p\n"
        "🎵 Можно скачать только аудио\n"
        "☁️ Большие файлы → GoFile\n\n"
        "⚡ Качество на твой выбор!"
    )

# =========================
# ОБРАБОТКА ССЫЛКИ
# =========================
@dp.message_handler(content_types=['text'])
async def handle_url(message: types.Message):
    # Игнорируем команды
    if message.text.startswith('/'):
        return
    
    url = message.text.strip()
    user_id = message.from_user.id
    
    # Проверяем что это похоже на URL
    if not any(domain in url.lower() for domain in ['youtube.', 'youtu.be', 'instagram.', 'insta', 'tiktok.', 'facebook.', 'fb.watch', 'vk.com', 'twitter.', 'x.com', 'http']):
        await message.answer("❌ Это не похоже на ссылку на видео\nОтправьте ссылку с YouTube, Instagram, TikTok и т.д.")
        return
    
    # Сохраняем URL пользователя
    user_urls[user_id] = url
    print(f"Saved URL for user {user_id}: {url}")  # Для отладки
    
    # Создаём меню выбора качества
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("🎵 Аудио", callback_data="quality_audio"),
        InlineKeyboardButton("📱 360p", callback_data="quality_360"),
        InlineKeyboardButton("📺 720p", callback_data="quality_720"),
        InlineKeyboardButton("🖥️ 1080p", callback_data="quality_1080"),
        InlineKeyboardButton("⭐ Лучшее", callback_data="quality_best")
    )
    
    await message.answer(
        "🎯 Выбери качество:",
        reply_markup=keyboard
    )

# =========================
# ОБРАБОТКА ВЫБОРА КАЧЕСТВА
# =========================
@dp.callback_query_handler(lambda c: c.data.startswith('quality_'))
async def process_quality(callback: CallbackQuery):
    # ВАЖНО: отвечаем на callback сразу!
    await callback.answer()
    
    user_id = callback.from_user.id
    quality = callback.data.replace('quality_', '')
    
    # Проверяем что пользователь не скачивает уже
    if user_locks.get(user_id):
        await callback.answer("⏳ Подожди, предыдущее скачивание ещё идёт!", show_alert=True)
        return
    
    # Блокируем пользователя
    user_locks[user_id] = True
    
    try:
        # Получаем URL пользователя
        url = user_urls.get(user_id)
        print(f"Retrieved URL for user {user_id}: {url}")  # Для отладки
        
        if not url:
            await callback.message.edit_text(
                "❌ Ссылка потерялась. Отправьте заново.\n\n"
                "Нажмите /start"
            )
            # Снимаем блокировку
            if user_id in user_locks:
                del user_locks[user_id]
            return
        
        # Удаляем меню с кнопками
        try:
            await callback.message.edit_text("⏳ Скачиваю...")
        except:
            # Если не получилось отредактировать - отправляем новое
            await callback.message.answer("⏳ Скачиваю...")
        
        template = f"{DOWNLOAD_DIR}/{user_id}_%(id)s.%(ext)s"
        
        # Определяем платформу
        is_instagram = "instagram.com" in url.lower()
        is_shorts = "shorts" in url.lower() or "youtu.be" in url.lower()
        
        # Формат для yt-dlp в зависимости от качества
        if quality == "audio":
            # Только аудио
            format_str = "bestaudio/best"
        elif quality == "360":
            # 360p с запасными вариантами
            format_str = "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=360]+bestaudio/best[height<=360]/best"
        elif quality == "720":
            # 720p с запасными вариантами
            format_str = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]/best"
        elif quality == "1080":
            # 1080p с запасными вариантами
            format_str = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
        else:  # best
            # Лучшее качество с запасными вариантами
            format_str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
        
        # Команда для yt-dlp
        if is_instagram:
            cmd = [
                "yt-dlp", "--no-playlist",
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "-f", format_str if quality != "best" else "best",
                "-o", template, url
            ]
        elif is_shorts:
            # Для Shorts упрощённый формат
            cmd = [
                "yt-dlp",
                "-f", "best" if quality == "best" else format_str,
                "--no-playlist",
                "-o", template, url
            ]
        else:
            # Обычное видео
            cmd = [
                "yt-dlp",
                "-f", format_str,
                "--merge-output-format", "mp4" if quality != "audio" else "m4a",
                "--no-playlist",
                "-o", template, url
            ]
        
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
                await callback.message.edit_text("❌ Видео приватное или требует авторизации")
            elif "unavailable" in error.lower():
                await callback.message.edit_text("❌ Видео недоступно или удалено")
            else:
                await callback.message.edit_text("❌ Не удалось скачать\nПроверьте ссылку")
            return
        
        # Ищем файл
        files = glob.glob(f"{DOWNLOAD_DIR}/{user_id}_*")
        if not files:
            await callback.message.edit_text("❌ Файл не найден")
            return
        
        file_path = files[0]
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        
        # Если аудио - отправляем как аудио
        if quality == "audio":
            await callback.message.edit_text(f"📤 Отправляю аудио ({size_mb:.1f} MB)...")
            
            with open(file_path, "rb") as audio:
                await callback.message.answer_audio(
                    audio,
                    caption=f"🎵 Аудио | {size_mb:.1f} MB"
                )
            
            await callback.message.delete()
        
        # До 2 GB - отправляем как видео
        elif size_mb <= TELEGRAM_VIDEO_LIMIT:
            # Конвертируем в правильный формат если нужно
            file_ext = os.path.splitext(file_path)[1].lower()
            if file_ext not in ['.mp4']:
                await callback.message.edit_text(f"🔄 Конвертирую в MP4 ({size_mb:.1f} MB)...")
                
                converted_path = f"{DOWNLOAD_DIR}/{user_id}_converted.mp4"
                
                convert_cmd = [
                    "ffmpeg", "-i", file_path,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart",
                    "-y", converted_path
                ]
                
                conv_process = await asyncio.create_subprocess_exec(
                    *convert_cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE
                )
                
                await conv_process.communicate()
                
                if conv_process.returncode == 0 and os.path.exists(converted_path):
                    file_path = converted_path
                    size_mb = os.path.getsize(file_path) / (1024 * 1024)
            
            await callback.message.edit_text(f"📤 Отправляю ({size_mb:.1f} MB)...")
            
            with open(file_path, "rb") as video:
                await callback.message.answer_video(
                    video,
                    caption=f"🎬 {quality.upper()} | {size_mb:.1f} MB",
                    supports_streaming=True
                )
            
            await callback.message.delete()
        
        # Больше 2 GB - GoFile
        else:
            await callback.message.edit_text(f"☁️ Загружаю на GoFile ({size_mb:.1f} MB)...")
            
            try:
                link = await upload_to_gofile(file_path)
                
                await callback.message.edit_text(
                    f"✅ Загружено на GoFile!\n\n"
                    f"📦 Качество: {quality.upper()}\n"
                    f"📦 Размер: {size_mb:.1f} MB\n"
                    f"🔗 Ссылка:\n{link}\n\n"
                    f"💡 Оригинальное качество"
                )
            
            except Exception as gofile_error:
                print(f"GoFile error: {gofile_error}")
                
                if drive:
                    await callback.message.edit_text(f"☁️ Загружаю в Google Drive ({size_mb:.1f} MB)...")
                    
                    try:
                        link = await upload_to_drive(file_path)
                        await callback.message.edit_text(
                            f"✅ Загружено в Google Drive!\n\n"
                            f"📦 Размер: {size_mb:.1f} MB\n"
                            f"🔗 {link}"
                        )
                    except Exception:
                        await callback.message.edit_text(
                            f"❌ Не удалось загрузить\n"
                            f"Скачай напрямую: {url}"
                        )
                else:
                    await callback.message.edit_text(
                        f"❌ Файл слишком большой: {size_mb:.1f} MB\n"
                        f"Скачай напрямую: {url}"
                    )
    
    except asyncio.TimeoutError:
        await callback.message.edit_text("❌ Таймаут (10 мин)")
    
    except asyncio.TimeoutError:
        await callback.message.edit_text("❌ Таймаут (10 мин)")
    
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.message.edit_text(f"❌ Ошибка: {str(e)[:200]}")
    
    finally:
        # Удаляем файлы
        for f in glob.glob(f"{DOWNLOAD_DIR}/{user_id}_*"):
            try:
                os.remove(f)
            except:
                pass
        
        # Очищаем сохранённый URL
        if user_id in user_urls:
            del user_urls[user_id]
        
        # Снимаем блокировку
        if user_id in user_locks:
            del user_locks[user_id]

# =========================
# ЗАПУСК
# =========================
if __name__ == "__main__":
    print("🚀 Бот запущен с выбором качества!")
    print(f"🎬 Лимит: {TELEGRAM_VIDEO_LIMIT} MB")
    print(f"☁️ Drive: {'Да' if drive else 'Нет'}")
    
    try:
        executor.start_polling(dp, skip_updates=True)
    finally:
        executor_pool.shutdown(wait=True)
