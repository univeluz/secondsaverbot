from cache import get_cached_video, cache_video
import logging
import os
import shutil
from pathlib import Path

from aiogram import F, Router, exceptions, types
from aiogram.filters import Command, CommandStart
from dotenv import load_dotenv

from enums import Links, ProgressState, VideoStatusMessages
from utils import VIDEOS_DIR, download_video, format_bytes, format_message

router = Router()
load_dotenv()

# Local Bot API supports up to 2000 MB (2 GB)
MAX_TELEGRAM_SIZE = 2000 * 1024 * 1024
FILES_URL = os.getenv("FILES_URL")


@router.message(F.text.startswith(tuple(Links.STANDART.value)))
async def handle_standart_download(message: types.Message):
    filename = None
    url = message.text
    if not url:
        return

    await message.react([types.reaction_type_emoji.ReactionTypeEmoji(emoji="👀")])
    msg = await message.answer(format_message(ProgressState.PREPARING))

    try:
        # 1. Check Redis cache for instant 0.5s response
        cached = await get_cached_video(url)
        if cached and cached.get("file_id"):
            await message.answer_video(
                video=cached["file_id"],
                caption=(VideoStatusMessages.Caption.value.format(url=url)),
                width=cached.get("width", 0),
                height=cached.get("height", 0),
                duration=cached.get("duration", 0),
            )
            await msg.delete()
            await message.delete()
            return

        # 2. Fresh download
        info = await download_video(msg, url)
        filename = info["filename"]
        duration = info.get("duration", 0)

        thumb_input = None
        if info.get("thumbnail") and os.path.exists(info["thumbnail"]):
            thumb_input = types.FSInputFile(info["thumbnail"])

        if filename.startswith("http://") or filename.startswith("https://"):
            video_input = types.URLInputFile(filename)
        else:
            if os.path.getsize(filename) > MAX_TELEGRAM_SIZE:
                await msg.edit_text(
                    VideoStatusMessages.VideoHostRedirect.value.format(
                        download_url=f"{FILES_URL}/{os.path.basename(filename)}"
                    )
                )
                return
            # Use 4MB chunk size for ultra-fast pipe to local telegram-bot-api
            video_input = types.FSInputFile(filename, chunk_size=4 * 1024 * 1024)

        sent_msg = await message.answer_video(
            video=video_input,
            caption=(VideoStatusMessages.Caption.value.format(url=url)),
            width=info["width"],
            height=info["height"],
            duration=duration,
            thumbnail=thumb_input
        )

        # 3. Cache the sent video file_id in Redis
        if sent_msg and sent_msg.video:
            await cache_video(
                url=url,
                file_id=sent_msg.video.file_id,
                width=info["width"],
                height=info["height"],
                duration=duration
            )
        
        if info.get("thumbnail") and os.path.exists(info["thumbnail"]):
            try:
                os.remove(info["thumbnail"])
            except:
                pass
    except exceptions.TelegramEntityTooLarge:
        if filename:
            await message.answer(
                VideoStatusMessages.VideoHostRedirect.value.format(
                    download_url=f"{FILES_URL}/{os.path.basename(filename)}"
                )
            )
    except Exception as e:
        logging.exception(f"Download failed: {e}")
        await message.answer(VideoStatusMessages.VideoError.value.format(url=url))
    else:
        await msg.delete()
        await message.delete()


@router.message(Command("stats"))
async def stats(message: types.Message):
    if message.from_user.id != int(os.getenv("ADMIN_ID", 0)):
        return

    counts = {}
    total_size = 0
    total_files = 0

    for file in VIDEOS_DIR.rglob("*"):
        if file.is_file():
            total_files += 1
            total_size += file.stat().st_size
            counts[file.suffix or "[none]"] = counts.get(file.suffix or "[none]", 0) + 1

    disk = shutil.disk_usage("/")
    text = [
        "<b>Videos:</b>",
        f"Files: {total_files}",
        f"Size: {format_bytes(total_size)}",
        "",
        "<b>Extensions:</b>",
    ]

    for ext, count in sorted(counts.items()):
        text.append(f"{ext}: {count}")

    text += [
        "",
        "<b>Disk:</b>",
        f"Used: {format_bytes(disk.used)} / {format_bytes(disk.total)}",
        f"Free: {format_bytes(disk.free)}",
    ]
    await message.answer("\n".join(text))


@router.message(Command("clean"))
async def clean(message: types.Message):
    if message.from_user.id != int(os.getenv("ADMIN_ID", 0)):
        return

    deleted = 0
    for file in filter(Path.is_file, VIDEOS_DIR.rglob("*")):
        file.unlink()
        deleted += 1

    await message.answer(f"Deleted {deleted} files.")


@router.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        f"Hello, @{message.from_user.username}! Just send the link to the video.\n\n"
        "ℹ️ <b>We don't collect any data.</b>\n\n"
        "🙏 <b>Please don't block the bot</b> — "
        "it needs to message you when the download is ready.",
    )
