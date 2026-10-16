"""Normalize cached catalog media for list thumbnails without network requests."""
from __future__ import annotations

import json
from urllib.parse import urlsplit


def _media_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or any(ord(char) < 32 for char in value) or '\\' in value:
        return None
    if value.startswith('//'):
        value = 'https:' + value
    if value.startswith('/static/'):
        return value
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {'https', 'http'} and parsed.netloc and not parsed.username:
            return value
    except ValueError:
        pass
    return None


def extract_catalog_media(*sources: object) -> dict:
    """Read known item/media fields only; preserve first-image ordering."""
    images: list[str] = []
    video_url: str | None = None
    video_cover: str | None = None

    def image(value: object) -> None:
        url = _media_url(value)
        if url and urlsplit(url).path.lower().endswith(('.mp4', '.mov', '.webm', '.m4v', '.avi')):
            return
        if url and url not in images and len(images) < 9:
            images.append(url)

    def video(value: object) -> None:
        nonlocal video_url
        video_url = video_url or _media_url(value)

    def cover(value: object) -> None:
        nonlocal video_cover
        url = _media_url(value)
        if url and not urlsplit(url).path.lower().endswith(('.mp4', '.mov', '.webm', '.m4v', '.avi')):
            video_cover = video_cover or url

    def read(value: object, kind: str = '', depth: int = 0) -> None:
        if depth > 4:
            return
        if isinstance(value, str):
            if kind == 'image':
                image(value)
            elif kind == 'video':
                video(value)
            else:
                try:
                    read(json.loads(value), depth=depth + 1)
                except (ValueError, TypeError):
                    pass
            return
        if isinstance(value, list):
            for entry in value[:30]:
                read(entry, kind, depth + 1)
            return
        if not isinstance(value, dict):
            return
        is_video = kind == 'video' or str(value.get('type', '')) == '10000' or bool(value.get('videoUrl') or value.get('video_url'))
        for key in ('item_video_url', 'video_url', 'videoUrl'):
            video(value.get(key))
        for key in ('item_video_cover', 'video_cover', 'videoCoverUrl', 'cover_url', 'coverUrl', 'thumbnail_url', 'posterUrl', 'poster'):
            cover(value.get(key))
        if is_video:
            video(value.get('videoUrl') or value.get('video_url') or value.get('url'))
            if value.get('videoUrl') or value.get('video_url'):
                cover(value.get('url'))
        elif kind == 'image':
            image(value.get('url') or value.get('imageUrl') or value.get('picUrl'))
        for key in ('image_url', 'imageUrl', 'itemImageUrl', 'picUrl'):
            image(value.get(key))
        for key in ('item_images', 'images', 'pic_info', 'picInfo', 'imageInfoList', 'picList'):
            read(value.get(key), 'image', depth + 1)
        for key in ('videos', 'video', 'video_info', 'videoInfo', 'videoList'):
            read(value.get(key), 'video', depth + 1)
        for key in ('mediaList', 'media_list'):
            read(value.get(key), 'image', depth + 1)
        for key in ('detail',):
            read(value.get(key), depth=depth + 1)

    for source in sources:
        read(source)
    return {'item_images': images, 'item_video_url': video_url, 'item_video_cover': video_cover}
