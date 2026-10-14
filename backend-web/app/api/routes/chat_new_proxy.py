"""
在线聊天(新) - 图片代理 API

将闲鱼 CDN 图片通过服务器中转，绕过 Referer 防盗链限制。
前端将消息中的图片 URL 替换为 /api/v1/chat-new/image-proxy?url=<encoded>，
后端携带合适的 Referer 头向 CDN 请求原图并流式返回给浏览器。
"""
from __future__ import annotations

import urllib.parse

import httpx
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from loguru import logger

from app.api.deps import get_current_active_user
from common.models.user import User

router = APIRouter(prefix="/chat-new")

# 只代理来自闲鱼/淘宝 CDN 的图片，避免被当成通用代理
_ALLOWED_HOSTS = (
    "img.alicdn.com",
    "gw.alicdn.com",
    "g.alicdn.com",
    "img.taobao.com",
    "goofish.com",
    "goofish-prod.oss-cn-hangzhou.aliyuncs.com",
    "img01.taobaocdn.com",
    "img02.taobaocdn.com",
    "img03.taobaocdn.com",
    "img04.taobaocdn.com",
    "img05.taobaocdn.com",
    "cbu01.alicdn.com",
)

_PROXY_HEADERS = {
    "Referer": "https://www.goofish.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


@router.get("/image-proxy")
async def image_proxy(
    url: str = Query(..., description="需要代理的图片 URL（需 URL 编码）"),
    _current_user: User = Depends(get_current_active_user),
) -> Response:
    """代理转发闲鱼 CDN 图片，解决浏览器直接请求时被 Referer 防盗链拦截的问题"""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return Response(status_code=400, content=b"invalid url")

    host = parsed.netloc.lower().split(":")[0]
    if not any(host == h or host.endswith("." + h) for h in _ALLOWED_HOSTS):
        return Response(status_code=403, content=b"url not allowed")

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=_PROXY_HEADERS)
        content_type = resp.headers.get("content-type", "image/jpeg")
        return Response(
            content=resp.content,
            status_code=200,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except Exception as exc:
        logger.warning(f"image proxy failed for {url}: {exc}")
        return Response(status_code=502, content=b"upstream error")
