import asyncio
import json
import os
import subprocess
import uuid
from pathlib import Path

import yt_dlp
from aiogram import types, exceptions
import aiohttp

from enums import ProgressState

VIDEOS_DIR = Path("videos")
VIDEOS_DIR.mkdir(exist_ok=True)

COOKIES_FILE = Path("/app/cookies.txt")


def get_video_metadata(filepath: str | Path) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "-select_streams", "v:0",
        "format=duration:stream=width,height,duration:stream_tags=rotate:stream_side_data=rotation",
        "-of",
        "json",
        str(filepath),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            duration = 0
            if "format" in data and "duration" in data["format"]:
                try:
                    duration = int(float(data["format"]["duration"]))
                except (ValueError, TypeError):
                    pass

            width, height = 0, 0
            for stream in data.get("streams", []):
                if stream.get("width") and stream.get("height"):
                    width = int(stream["width"])
                    height = int(stream["height"])
                    
                    rotation = 0
                    if "tags" in stream and "rotate" in stream["tags"]:
                        rotation = int(float(stream["tags"]["rotate"]))
                    elif "side_data_list" in stream:
                        for sd in stream["side_data_list"]:
                            if "rotation" in sd:
                                rotation = int(float(sd["rotation"]))
                    if abs(rotation) == 90 or abs(rotation) == 270:
                        width, height = height, width
                        
                    if not duration and stream.get("duration"):
                        try:
                            duration = int(float(stream["duration"]))
                        except (ValueError, TypeError):
                            pass
                    break

            return {"duration": duration, "width": width, "height": height}
    except Exception as e:
        print(f"Error extracting metadata with ffprobe for {filepath}: {e}")

    return {"duration": 0, "width": 0, "height": 0}


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "N/A"

    value = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024

    return f"{value:.1f} TB"


def format_time(seconds: int | None) -> str:
    if seconds is None:
        return "N/A"

    minutes, seconds = divmod(seconds, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02}:{seconds:02}"

    return f"{minutes:02}:{seconds:02}"


def get_percentage(data: dict) -> float:
    downloaded = data.get("downloaded_bytes", 0)
    total = data.get("total_bytes") or data.get("total_bytes_estimate")

    return downloaded / total * 100 if total else 0


def format_message(
    state: ProgressState,
    progress: float = 0,
) -> str:
    steps = [
        ProgressState.PREPARING,
        ProgressState.VIDEO_DOWNLOADING,
        ProgressState.AUDIO_DOWNLOADING,
        ProgressState.FINALIZING,
    ]

    lines = []

    for step in steps:
        if steps.index(step) < steps.index(state):
            lines.append(f"✅ {step.value}")
        elif step == state:
            if step in (
                ProgressState.VIDEO_DOWNLOADING,
                ProgressState.AUDIO_DOWNLOADING,
            ):
                lines.append(f"🔄 {step.value} ({progress:.1f}%)")
            else:
                lines.append(f"🔄 {step.value}")
        else:
            lines.append(f"⏳ {step.value}")

    return "\n".join(lines)


async def download_tiktok_video(msg: types.Message, url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://www.tikwm.com/api/?url={url}",
            headers={"User-Agent": "Mozilla/5.0"},
        ) as resp:
            data = await resp.json()

    if data.get("code") != 0 or "data" not in data:
        raise Exception("Failed to fetch TikTok data")

    video_url = data["data"]["play"]
    duration = int(data["data"].get("duration", 0))

    try:
        await msg.edit_text(format_message(ProgressState.FINALIZING))
    except exceptions.TelegramBadRequest:
        pass

    return {
        "filename": video_url,
        "width": 0,
        "height": 0,
        "duration": duration,
        "thumbnail": None
    }


async def download_video(msg: types.Message, url: str, quality: str = '720'):
    if "tiktok.com" in url.lower():
        return await download_tiktok_video(msg, url)

    loop = asyncio.get_running_loop()
    last_update = [0.0]
    progress = [0.0]
    current_state = [ProgressState.VIDEO_DOWNLOADING]

    async def update_progress() -> None:
        await msg.edit_text(
            format_message(
                current_state[0],
                progress[0],
            )
        )

    def progress_hook(data):
        if data["status"] != "downloading":
            return

        info = data.get("info_dict", {})

        if info.get("vcodec") == "none":
            current_state[0] = ProgressState.AUDIO_DOWNLOADING
        else:
            current_state[0] = ProgressState.VIDEO_DOWNLOADING

        progress[0] = get_percentage(data)

        now = loop.time()
        if now - last_update[0] < 1:
            return

        last_update[0] = now

        asyncio.run_coroutine_threadsafe(
            update_progress(),
            loop,
        )

    def download():
        import shutil
        import tempfile

        video_id = str(uuid.uuid4())

        is_instagram = "instagram.com" in url.lower()
        if is_instagram:
            proxy_url = None
        else:
            proxy_url = os.getenv("PROXY_URL") or os.getenv("WARP_PROXY", "socks5://warp:9091")

        # Format selector based on quality
        # Ensures 360p merges separate video+audio when pre-muxed 18 is absent!
        if quality == "360":
            format_selector = (
                "18/"
                "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo[height<=360]+bestaudio/"
                "b[height<=360][ext=mp4]/"
                "best[height<=360]/"
                "best"
            )
        elif quality == "480":
            format_selector = (
                "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo[height<=480]+bestaudio/"
                "best[height<=480]/"
                "18/"
                "best"
            )
        else:
            format_selector = (
                "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
                "best[height<=720][ext=mp4]/"
                "bestvideo[height<=720]+bestaudio/"
                "best[height<=720]/"
                "18/"
                "best"
            )

        options = {
            "format": format_selector,
            "merge_output_format": "mp4",
            "outtmpl": str(VIDEOS_DIR / f"{video_id}.%(ext)s"),
            "noplaylist": True,
            "proxy": proxy_url,
            "js_runtimes": {"quickjs": {"path": "/usr/bin/qjs"}} if shutil.which("qjs") else {},
            "concurrent_fragment_downloads": 16,
            "http_chunk_size": 10 * 1024 * 1024,
            "buffersize": 16 * 1024 * 1024,
            "writethumbnail": True,
            "progress_hooks": [progress_hook],
            "postprocessors": [],
        }

        # Copy cookies to a writable temp file if valid Netscape format
        tmp_cookies = None
        if not is_instagram and COOKIES_FILE.exists() and COOKIES_FILE.is_file() and COOKIES_FILE.stat().st_size > 10:
            cookie_text = COOKIES_FILE.read_text(encoding="utf-8").strip()
            if "# Netscape" in cookie_text or "\t" in cookie_text:
                tmp_cookies = tempfile.NamedTemporaryFile(
                    suffix=".txt", delete=False, mode="w", encoding="utf-8"
                )
                tmp_cookies.write(cookie_text + "\n")
                tmp_cookies.flush()
                tmp_cookies.close()
                options["cookiefile"] = tmp_cookies.name

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_file = ydl.prepare_filename(info)

                # Find final file in case postprocessor changed extension to .mp4
                file_path = Path(downloaded_file)
                if not file_path.exists():
                    mp4_candidate = file_path.with_suffix(".mp4")
                    if mp4_candidate.exists():
                        file_path = mp4_candidate

                meta = get_video_metadata(file_path)

                width = meta["width"] or info.get("width", 0)
                height = meta["height"] or info.get("height", 0)
                raw_dur = info.get("duration")
                yt_duration = int(float(raw_dur)) if raw_dur is not None else 0
                duration = meta["duration"] or yt_duration

                thumb_path = None
                # Check if yt-dlp downloaded thumbnail
                for ext in [".jpg", ".webp", ".png", ".jpeg"]:
                    tp = file_path.with_suffix(ext)
                    if tp.exists() and tp.stat().st_size > 0:
                        thumb_path = tp
                        break

                # If webp, convert to jpg for Telegram preview support
                if thumb_path and thumb_path.exists() and thumb_path.suffix.lower() == ".webp":
                    jpg_path = thumb_path.with_suffix(".jpg")
                    subprocess.run([
                        "ffmpeg", "-y", "-i", str(thumb_path), str(jpg_path)
                    ], capture_output=True)
                    if jpg_path.exists() and jpg_path.stat().st_size > 0:
                        thumb_path.unlink(missing_ok=True)
                        thumb_path = jpg_path

                # If no thumbnail yet, generate directly from video file via ffmpeg (<0.1s)
                if not thumb_path or not thumb_path.exists():
                    gen_thumb = file_path.with_suffix(".jpg")
                    seek_time = "00:00:01.000" if duration > 2 else "00:00:00.000"
                    try:
                        subprocess.run([
                            "ffmpeg", "-y", "-ss", seek_time, "-i", str(file_path),
                            "-vframes", "1", "-q:v", "2", str(gen_thumb)
                        ], capture_output=True, timeout=3)
                        if gen_thumb.exists() and gen_thumb.stat().st_size > 0:
                            thumb_path = gen_thumb
                    except Exception:
                        pass

                return {
                    "filename": str(file_path),
                    "width": width,
                    "height": height,
                    "duration": duration,
                    "thumbnail": str(thumb_path) if (thumb_path and thumb_path.exists()) else None,
                    "format_id": info.get("format_id"),
                    "filesize": file_path.stat().st_size if file_path.exists() else info.get("filesize"),
                    "vcodec": info.get("vcodec"),
                    "acodec": info.get("acodec"),
                    "ext": file_path.suffix.lstrip(".") or info.get("ext", "mp4"),
                }
        finally:
            if tmp_cookies:
                Path(tmp_cookies.name).unlink(missing_ok=True)

    info = await loop.run_in_executor(None, download)

    await msg.edit_text(format_message(ProgressState.FINALIZING))

    return {
        "filename": info["filename"],
        "width": info["width"],
        "height": info["height"],
        "duration": info.get("duration", 0),
        "thumbnail": info.get("thumbnail"),
        "format_id": info.get("format_id"),
        "filesize": info.get("filesize"),
        "vcodec": info.get("vcodec"),
        "acodec": info.get("acodec"),
        "ext": info.get("ext", "mp4"),
    }
