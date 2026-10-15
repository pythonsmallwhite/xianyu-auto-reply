"""聊天视频上传：PR #58 的 xy_chat 文件上传协议，独立于图片压缩流程。"""
from __future__ import annotations

import json
import math
from pathlib import Path
from uuid import uuid4

import aiohttp

from common.utils.image_uploader import ImageUploader
from common.utils.xianyu_video import resolve_video_media_url

MAX_CHAT_VIDEO_SIZE = 20 * 1024 * 1024


def probe_chat_video(path: str) -> dict[str, int]:
    """复用项目已有 OpenCV 依赖读取尺寸/时长，不引入 ffmpeg 安装。"""
    import cv2

    capture = cv2.VideoCapture(path)
    try:
        success, frame = capture.read()
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not success or frame is None or width <= 0 or height <= 0:
            raise ValueError("无法读取视频，请选择可正常播放的视频文件")
        duration_ms = int(frames / fps * 1000) if (
            math.isfinite(frames) and math.isfinite(fps) and frames > 0 and fps > 0
        ) else 0
        return {"width": width, "height": height, "duration_ms": duration_ms}
    finally:
        capture.release()


class ChatVideoUploader(ImageUploader):
    """复用会话与 xy_chat 地址，视频原文件上传，不调用 upload_image。"""

    async def upload_video(self, path: str, content_type: str) -> str:
        if not self.session:
            await self.create_session()
        headers = {
            "cookie": self.cookies_str,
            "Referer": "https://www.goofish.com/",
            "x-requested-with": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        with open(path, "rb") as handle:
            data = aiohttp.FormData()
            data.add_field("file", handle,
                           filename=f"video_{uuid4().hex[:12]}{Path(path).suffix}",
                           content_type=content_type)
            async with self.session.post(
                self.upload_url, data=data, headers=headers,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as response:
                if response.status != 200:
                    raise RuntimeError(f"视频上传失败：HTTP {response.status}")
                try:
                    result = json.loads(await response.text())
                except (ValueError, TypeError) as exc:
                    raise RuntimeError("视频上传失败：返回无效，请检查账号登录状态") from exc
        if isinstance(result, dict):
            for block in (result.get("data"), result.get("object"), result, result.get("result")):
                if isinstance(block, dict):
                    url = resolve_video_media_url(block.get("url") or block.get("fileUrl") or block.get("file_url"))
                    if url:
                        return url
        raise RuntimeError("视频上传未返回有效地址，请检查账号登录状态")
