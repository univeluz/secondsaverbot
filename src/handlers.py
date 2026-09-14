from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from cache import get_cached_media, cache_media, get_cached_video, cache_video
import logging
import os
import shutil
from pathlib import Path

from aiogram import F, Router, exceptions, types
from aiogram.filters import Command, CommandStart
from dotenv import load_dotenv

from enums import Links, ProgressState, VideoStatusMessages
from utils import VIDEOS_DIR, download_video, download_audio, format_bytes, format_message

router = Router()
load_dotenv()

# Local Bot API supports up to 2000 MB (2 GB)
MAX_TELEGRAM_SIZE = 2000 * 1024 * 1024
FILES_URL = os.getenv("FILES_URL")


@router.message(F.text.startswith(tuple(Links.STANDART.value)))
async def handle_standart_download(message: types.Message):
    url = message.text.strip()
    if not url:
        return

    await message.react([types.reaction_type_emoji.ReactionTypeEmoji(emoji="👀")])

    # 1. Check Redis cache for instant 0.5s response (if already fetched before)
    cached = await get_cached_media(url)
    if cached and cached.get("file_id"):
        caption = VideoStatusMessages.Caption.value.format(url=url)
        await message.answer_video(
            video=cached["file_id"],
            caption=caption,
            width=cached.get("width", 0),
            height=cached.get("height", 0),
            duration=cached.get("duration", 0),
        )
        await message.delete()
        return

    # Check if YouTube link (show 360p, 720p, Audio)
    is_yt = any(domain in url.lower() for domain in ["youtube.com", "youtu.be"])
    if is_yt and not ("/shorts/" in url.lower()):
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="⚡ 360p", callback_data=f"dl:360:{url}"),
            InlineKeyboardButton(text="💎 720p", callback_data=f"dl:720:{url}"),
            InlineKeyboardButton(text="🎵 MP3 Audio", callback_data=f"dl:audio:{url}")
        )
        await message.answer(
            f"🎬 <b>Formatni tanlang:</b>\n<code>{url}</code>",
            reply_markup=builder.as_markup()
        )
        return

    # For Shorts, Reels, TikTok - direct instant download
    msg = await message.answer(format_message(ProgressState.PREPARING))
    try:
        info = await download_video(msg, url, quality="720")
        filename = info["filename"]
        duration = info.get("duration", 0)

        thumb_input = None
        if info.get("thumbnail") and os.path.exists(info["thumbnail"]):
            thumb_input = types.FSInputFile(info["thumbnail"])

        video_input = types.FSInputFile(filename, chunk_size=4 * 1024 * 1024)

        sent_msg = await message.answer_video(
            video=video_input,
            caption=(VideoStatusMessages.Caption.value.format(url=url)),
            width=info.get("width", 0),
            height=info.get("height", 0),
            duration=duration,
            thumbnail=thumb_input
        )

        if sent_msg and sent_msg.video:
            await cache_media(
                key=url,
                file_id=sent_msg.video.file_id,
                media_type="video",
                width=info.get("width", 0),
                height=info.get("height", 0),
                duration=duration,
                format_id=info.get("format_id"),
                resolution=f"{info.get('width', 0)}x{info.get('height', 0)}",
                filesize=info.get("filesize"),
                vcodec=info.get("vcodec"),
                acodec=info.get("acodec"),
                ext=info.get("ext", "mp4")
            )

        if info.get("thumbnail") and os.path.exists(info["thumbnail"]):
            try:
                os.remove(info["thumbnail"])
            except:
                pass
    except Exception as e:
        logging.exception(f"Direct download failed: {e}")
        await message.answer(VideoStatusMessages.VideoError.value.format(url=url))
    else:
        await msg.delete()
        await message.delete()


@router.callback_query(F.data.startswith("dl:"))
async def handle_quality_choice(callback: types.CallbackQuery):
    _, choice, url = callback.data.split(":", 2)
    message = callback.message
    await callback.answer()
    msg = await message.edit_text(format_message(ProgressState.PREPARING))

    cache_key = f"{url}#{choice}"

    try:
        # Check cache
        cached = await get_cached_media(cache_key)
        if cached and cached.get("file_id"):
            caption = VideoStatusMessages.Caption.value.format(url=url)
            if cached.get("media_type") == "audio":
                await callback.bot.send_audio(
                    chat_id=callback.from_user.id,
                    audio=cached["file_id"],
                    caption=caption,
                    title=cached.get("title"),
                    performer=cached.get("performer"),
                    duration=cached.get("duration", 0),
                )
            else:
                await callback.bot.send_video(
                    chat_id=callback.from_user.id,
                    video=cached["file_id"],
                    caption=caption,
                    width=cached.get("width", 0),
                    height=cached.get("height", 0),
                    duration=cached.get("duration", 0),
                )
            await msg.delete()
            return

        # Audio choice
        if choice == "audio":
            info = await download_audio(msg, url)
            filename = info["filename"]
            duration = info.get("duration", 0)

            thumb_input = None
            if info.get("thumbnail") and os.path.exists(info["thumbnail"]):
                thumb_input = types.FSInputFile(info["thumbnail"])

            audio_input = types.FSInputFile(filename, chunk_size=4 * 1024 * 1024)

            sent_msg = await callback.bot.send_audio(
                chat_id=callback.from_user.id,
                audio=audio_input,
                caption=(VideoStatusMessages.Caption.value.format(url=url)),
                duration=duration,
                title=info.get("title"),
                performer=info.get("performer"),
                thumbnail=thumb_input
            )

            if sent_msg and sent_msg.audio:
                await cache_media(
                    key=cache_key,
                    file_id=sent_msg.audio.file_id,
                    media_type="audio",
                    duration=duration,
                    title=info.get("title"),
                    performer=info.get("performer"),
                    format_id=info.get("format_id"),
                    filesize=info.get("filesize"),
                    ext=info.get("ext", "m4a")
                )

            if info.get("thumbnail") and os.path.exists(info["thumbnail"]):
                try:
                    os.remove(info["thumbnail"])
                except:
                    pass
        else:
            # Video choice (360p or 720p)
            info = await download_video(msg, url, quality=choice)
            filename = info["filename"]
            duration = info.get("duration", 0)

            thumb_input = None
            if info.get("thumbnail") and os.path.exists(info["thumbnail"]):
                thumb_input = types.FSInputFile(info["thumbnail"])

            video_input = types.FSInputFile(filename, chunk_size=4 * 1024 * 1024)

            sent_msg = await callback.bot.send_video(
                chat_id=callback.from_user.id,
                video=video_input,
                caption=(VideoStatusMessages.Caption.value.format(url=url)),
                width=info.get("width", 0),
                height=info.get("height", 0),
                duration=duration,
                thumbnail=thumb_input
            )

            if sent_msg and sent_msg.video:
                await cache_media(
                    key=cache_key,
                    file_id=sent_msg.video.file_id,
                    media_type="video",
                    width=info.get("width", 0),
                    height=info.get("height", 0),
                    duration=duration,
                    format_id=info.get("format_id"),
                    resolution=f"{info.get('width', 0)}x{info.get('height', 0)}",
                    filesize=info.get("filesize"),
                    vcodec=info.get("vcodec"),
                    acodec=info.get("acodec"),
                    ext=info.get("ext", "mp4")
                )

            if info.get("thumbnail") and os.path.exists(info["thumbnail"]):
                try:
                    os.remove(info["thumbnail"])
                except:
                    pass

    except Exception as e:
        logging.exception(f"Download choice failed: {e}")
        await msg.edit_text(VideoStatusMessages.VideoError.value.format(url=url))
    else:
        await msg.delete()


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
