import os
import json
import logging
import redis.asyncio as aioredis
from typing import Optional, Dict, Any

redis_client: Optional[aioredis.Redis] = None

def get_redis() -> Optional[aioredis.Redis]:
    global redis_client
    if redis_client is None and os.getenv("USE_REDIS", "False").lower() in ("true", "1", "yes"):
        host = os.getenv("REDIS_HOST", "redis_cache")
        port = int(os.getenv("REDIS_PORT", 6379))
        db = int(os.getenv("REDIS_DB", 1))
        password = os.getenv("REDIS_PASSWORD") or None
        try:
            redis_client = aioredis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                decode_responses=True,
                socket_timeout=2.0
            )
            logging.info("Redis cache initialized successfully.")
        except Exception as e:
            logging.error(f"Failed to connect to Redis: {e}")
            redis_client = None
    return redis_client

async def get_cached_media(key: str) -> Optional[dict]:
    """Returns cached media dict if exists."""
    r = get_redis()
    if not r:
        return None
    try:
        data = await r.get(f"media:{key}")
        if data:
            return json.loads(data)
    except Exception as e:
        logging.warning(f"Redis get error: {e}")
    return None

async def cache_media(
    key: str,
    file_id: str,
    media_type: str = "video", # video or audio
    width: int = 0,
    height: int = 0,
    duration: int = 0,
    title: Optional[str] = None,
    performer: Optional[str] = None,
    format_id: Optional[str] = None,
    resolution: Optional[str] = None,
    filesize: Optional[int] = None,
    vcodec: Optional[str] = None,
    acodec: Optional[str] = None,
    ext: Optional[str] = None
):
    """Caches telegram file_id + all metadata for 7 days."""
    r = get_redis()
    if not r:
        return
    try:
        val = json.dumps({
            "file_id": file_id,
            "media_type": media_type,
            "width": width,
            "height": height,
            "duration": duration,
            "title": title,
            "performer": performer,
            "format_id": format_id,
            "resolution": resolution or (f"{width}x{height}" if width else None),
            "filesize": filesize,
            "vcodec": vcodec,
            "acodec": acodec,
            "ext": ext or ("mp4" if media_type == "video" else "m4a"),
        })
        await r.setex(f"media:{key}", 7 * 24 * 3600, val)
    except Exception as e:
        logging.warning(f"Redis set error: {e}")

# Backward compatibility wrappers
async def get_cached_video(url: str):
    return await get_cached_media(url)

async def cache_video(url: str, **kwargs):
    await cache_media(key=url, media_type="video", **kwargs)
