"""IM 视频载荷与媒体 ID；协议来源 23Star/xianyu-super-butler PR #58。

只供视频及其封面使用，不改变已有图片/文本解析。
"""
from __future__ import annotations

import base64
import re
from typing import Any
from urllib.parse import urlsplit

from common.utils.xianyu_utils import MessagePackDecoder

DEFAULT_MEDIA_HOST = "down.im.dingtalk.cn"
_MEDIA_TYPES = {0: "jpg", 1: "gif", 2: "png", 3: "bmp", 6: "mp4", 29: "webp"}


def normalize_media_host(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return DEFAULT_MEDIA_HOST
    try:
        parsed = urlsplit(value if "://" in value else f"//{value}")
        host = (parsed.hostname or "").lower()
    except ValueError:
        return DEFAULT_MEDIA_HOST
    if any(host == domain or host.endswith("." + domain)
           for domain in ("dingtalk.cn", "dingtalk.com", "alicdn.com", "aliyuncs.com", "goofish.com")):
        return host
    return DEFAULT_MEDIA_HOST


def _value(metadata: Any, key: int, default: Any = None) -> Any:
    if isinstance(metadata, (list, tuple)):
        return metadata[key] if key < len(metadata) else default
    if isinstance(metadata, dict):
        return metadata.get(key, metadata.get(str(key), default))
    return default


def resolve_video_media_url(value: Any, media_host: str | None = None) -> str:
    """还原视频/封面的 @、$ 媒体 ID；无效值返回空地址。"""
    if not isinstance(value, str) or not value or len(value) > 8192:
        return ""
    if not value.startswith(("@", "$")):
        if value.startswith("//"):
            value = "https:" + value
        if value.startswith("http:"):
            value = "https:" + value[5:]
        try:
            parsed = urlsplit(value)
            return value if parsed.scheme == "https" and parsed.hostname else ""
        except ValueError:
            return ""
    encoded = value[1:]
    if not re.fullmatch(r"[A-Za-z0-9_+/=-]+", encoded):
        return ""
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        metadata = MessagePackDecoder(raw).decode()
        if not isinstance(metadata, (dict, list, tuple)):
            return ""
        if value[0] == "@":
            file_type = _MEDIA_TYPES.get(_value(metadata, 0), "file")
            width = max(0, int(_value(metadata, 3, 0) or 0))
            height = max(0, int(_value(metadata, 2, 0) or 0))
            path = f"media/{encoded}_{width}_{height}.{file_type}"
        else:
            file_type = str(_value(metadata, 2, "file")).lower()
            if not re.fullmatch(r"[a-z0-9]{1,10}", file_type):
                return ""
            path = f"ddmedia/{encoded}.{file_type}"
        return f"https://{normalize_media_host(media_host)}/{path}"
    except (ValueError, TypeError, IndexError, KeyError, RecursionError):
        return ""


def extract_video_fields(decoded: dict, media_host: str | None = None) -> dict[str, str]:
    video = decoded.get("video")
    if not isinstance(video, dict):
        return {"videoUrl": "", "videoCoverUrl": ""}
    return {
        "videoUrl": resolve_video_media_url(
            video.get("url") or video.get("videoUrl") or video.get("videoMediaId"), media_host,
        ),
        "videoCoverUrl": resolve_video_media_url(
            video.get("poster") or video.get("coverUrl") or video.get("picMediaId"), media_host,
        ),
    }


def make_video_content(video_url: str, width: int = 0, height: int = 0,
                       duration_ms: int = 0, cover_url: str = "") -> dict:
    video = {
        "url": video_url, "width": int(width), "height": int(height),
        "duration": int(duration_ms), "durationMs": int(duration_ms),
    }
    if cover_url:
        video.update(poster=cover_url, coverUrl=cover_url)
    return {"contentType": 4, "video": video}
