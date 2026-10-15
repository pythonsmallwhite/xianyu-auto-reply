"""在线聊天(新) - 视频发送 API，与 chat_new_image 共用账号归属与 IM 会话。"""
from __future__ import annotations

import asyncio
import os
import tempfile
import re
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, Depends, File, Form, UploadFile, Query, Request
from fastapi.responses import Response, StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session
from app.api.routes.chat_new_image import _get_owned_chat_account
from app.services.chat_new import get_im_session_manager
from common.models import User
from common.schemas.common import ApiResponse
from common.utils.chat_video_uploader import ChatVideoUploader, MAX_CHAT_VIDEO_SIZE, probe_chat_video

router = APIRouter(prefix="/chat-new")


def _allowed_video_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        return (parsed.scheme == "https" and parsed.port in (None, 443)
                and not parsed.username and not parsed.password
                and any(host == domain or host.endswith("." + domain)
                        for domain in ("dingtalk.cn", "dingtalk.com")))
    except ValueError:
        return False


@router.get("/video-proxy")
async def video_proxy(request: Request, url: str = Query(..., max_length=8192)):
    """视频媒体 ID 域名的独立代理，支持单 Range；原图片代理保持不变。"""
    if not _allowed_video_url(url):
        return Response(status_code=403)
    headers = {"Referer": "https://www.goofish.com/", "Accept": "*/*", "Accept-Encoding": "identity"}
    byte_range = request.headers.get("range")
    if byte_range:
        if not re.fullmatch(r"bytes=(?:[0-9]+-[0-9]*|-[0-9]+)", byte_range):
            return Response(status_code=416)
        headers["Range"] = byte_range
    client = httpx.AsyncClient(timeout=30, follow_redirects=False)
    upstream = None
    try:
        for _ in range(5):
            if not _allowed_video_url(url):
                await client.aclose()
                return Response(status_code=403)
            upstream = await client.send(client.build_request("GET", url, headers=headers), stream=True)
            if upstream.is_redirect:
                location = upstream.headers.get("location", "")
                await upstream.aclose()
                url = urljoin(url, location) if location else ""
                continue
            if upstream.status_code not in (200, 206):
                status = upstream.status_code if upstream.status_code in (404, 416) else 502
                await upstream.aclose()
                await client.aclose()
                return Response(status_code=status)
            media_type = upstream.headers.get("content-type", "application/octet-stream").split(";")[0]
            if not (media_type.startswith(("video/", "image/")) or media_type == "application/octet-stream"):
                await upstream.aclose()
                await client.aclose()
                return Response(status_code=502)
            response_headers = {"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"}
            for name in ("content-range", "accept-ranges", "content-length"):
                if name in upstream.headers:
                    response_headers[name] = upstream.headers[name]

            async def stream():
                try:
                    async for chunk in upstream.aiter_raw():
                        yield chunk
                finally:
                    await upstream.aclose()
                    await client.aclose()

            return StreamingResponse(stream(), status_code=upstream.status_code,
                                     media_type=media_type, headers=response_headers)
        await client.aclose()
        return Response(status_code=502)
    except (httpx.HTTPError, ValueError):
        if upstream is not None:
            await upstream.aclose()
        await client.aclose()
        return Response(status_code=502)


@router.post("/send-video/{account_id}")
async def send_video(
    account_id: str,
    cid: str = Form(..., min_length=1, max_length=200),
    toUserId: str = Form(..., min_length=1, max_length=100),
    video: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """先检查账号和文件，上传视频，再单次发送 IM 消息并返回平台回执。"""
    if not await _get_owned_chat_account(account_id, current_user, db):
        return ApiResponse(success=False, message="账号不存在或无权操作")
    client = get_im_session_manager().clients.get(account_id)
    if not client or not client.is_connected:
        return ApiResponse(success=False, message="账号未连接，请先连接")
    if not cid.strip() or not toUserId.strip():
        return ApiResponse(success=False, message="会话或接收用户不能为空")
    content_type = (video.content_type or "").lower()
    if not content_type.startswith("video/"):
        return ApiResponse(success=False, message="请上传视频文件")

    temp_path = None
    try:
        # 分块读取，超过上限即停止，不把任意大小的文件一次性加载到内存。
        suffix = os.path.splitext(video.filename or "")[1].lower()
        if suffix not in (".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv", ".3gp"):
            suffix = ".mp4"
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        size = 0
        with os.fdopen(fd, "wb") as handle:
            while chunk := await video.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_CHAT_VIDEO_SIZE:
                    return ApiResponse(success=False, message="视频大小不能超过20MB")
                handle.write(chunk)
        if size == 0:
            return ApiResponse(success=False, message="上传文件为空")

        info = await asyncio.to_thread(probe_chat_video, temp_path)
        async with ChatVideoUploader(client.cookies_str) as uploader:
            cdn_url = await uploader.upload_video(temp_path, content_type)
        if not cdn_url:
            return ApiResponse(success=False, message="视频上传失败，未发送消息")
        send_result = await client.send_video_message(
            cid=cid.strip(), to_user_id=toUserId.strip(), video_url=cdn_url, **info,
        )
        logger.info(f"【{account_id}】视频消息已取得IM回执")
        return ApiResponse(success=True, message="发送成功", data={
            "messageId": send_result.get("messageId", ""),
            "videoUrl": cdn_url, "videoCoverUrl": "",
        })
    except Exception as exc:
        logger.warning(f"【{account_id}】视频发送失败，异常类型={type(exc).__name__}")
        return ApiResponse(success=False, message=f"发送失败：{exc}")
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass
