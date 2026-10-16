"""Real video/payload/publisher functions with offline media and platform doubles."""
from __future__ import annotations

import importlib
import json
import sys
import types
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

from tests.test_publish_guard_boundaries import _OfflineGuardTests


class PublishVideoRegressions(_OfflineGuardTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Decoding and RSA authorization are outside these protocol regressions.
        # No real network/database or native decoder is initialized.
        for name, attrs in {
            "cv2": {},
            "Crypto": {},
            "Crypto.Cipher": {"PKCS1_v1_5": Mock()},
            "Crypto.PublicKey": {"RSA": Mock()},
        }.items():
            stub = types.ModuleType(name)
            stub.__dict__.update(attrs)
            sys.modules[name] = stub
        sys.modules["common.services.xianyu_publish_media"].upload_publish_image_content = AsyncMock(
            side_effect=AssertionError("explicit cover mock required"))
        del sys.modules["common.services.xianyu_publish_video"]
        cls.video = importlib.import_module("common.services.xianyu_publish_video")
        cls.builder = importlib.import_module("app.services.xianyu_item_payload_builder")
        cls.publisher = importlib.import_module("app.services.xianyu_direct_publisher")

    async def test_uploaded_cover_wins_over_local_or_stale_material_thumbnail(self):
        for thumbnail in ("/static/cover.jpg", "https://old.example/cover.jpg", ""):
            payload = self.video._video_payload(
                {"thumbnail_url": thumbnail}, "video-id", "https://video.example/item.mp4",
                640, 360, "https://image.example/uploaded.jpg")
            self.assertEqual(payload["url"], "https://image.example/uploaded.jpg")
            self.assertEqual(payload["videoUrl"], "https://video.example/item.mp4")
            self.assertEqual(payload["mediaCloudFileId"], "video-id")

    async def test_missing_uploaded_cover_never_uses_video_url_as_image(self):
        for value in (None, "", "/static/local.jpg"):
            with self.assertRaisesRegex(self.video.PublishVideoError, "封面"):
                self.video._video_payload({}, "id", "https://video.example/a.mp4", 640, 360, value)
        with patch.object(self.video, "upload_publish_image_content", AsyncMock(return_value={"url": ""})):
            with self.assertRaisesRegex(self.video.PublishVideoError, "封面上传"):
                await self.video._upload_video_cover(b"cover", "test.mp4", "offline")

    async def test_video_count_is_rejected_instead_of_silent_truncation(self):
        with patch.object(self.video, "upload_publish_video", new_callable=AsyncMock) as upload:
            with self.assertRaisesRegex(self.video.PublishVideoError, "3 个"):
                await self.video.upload_publish_videos([{}] * 4, "offline", "acct")
            upload.assert_not_awaited()

    async def test_second_upload_path_preserves_uploaded_cover(self):
        responses = [
            {"success": True, "res": {"data": {"model": {
                "uploadId": "upload-id", "uploadUrlList": ["https://oss.example/part"],
                "publicKey": "offline-key", "requestId": "request",
                "videoUploadPolicy": {"supportSecondTransfer": True},
            }}}},
            {"success": True, "cookies_str": "offline-second", "res": {"data": {"model": {
                "secondUpload": True, "fileId": "second-video", "ossUrl": "https://video.example/second.mp4",
            }}}},
        ]
        with patch.object(self.video, "_read_video", AsyncMock(return_value=(b"video", "test.mp4", "video/mp4"))), \
             patch.object(self.video, "_extract_video_cover", AsyncMock(return_value=(b"cover", 640, 360))), \
             patch.object(self.video, "_fetch_biz_config", AsyncMock(return_value={"apiInfo": {}})), \
             patch.object(self.video, "_encrypt_second_upload", Mock(return_value="offline-encrypted")), \
             patch.object(self.video, "_put_part", new_callable=AsyncMock) as part, \
             patch.object(self.video, "_upload_video_cover", AsyncMock(return_value="https://image.example/second.jpg")), \
             patch.object(self.video, "mtop_call", AsyncMock(side_effect=responses)), \
             patch.object(self.video, "logger"):
            payload, cookie = await self.video.upload_publish_video(
                {"thumbnail_url": "/static/local.jpg"}, "offline", "acct", 7)
        self.assertEqual((payload["mediaCloudFileId"], cookie), ("second-video", "offline-second"))
        self.assertEqual(payload["url"], "https://image.example/second.jpg")
        part.assert_not_awaited()

    async def test_video_preparation_errors_flow_through_real_builder_as_failed(self):
        for error in (self.video.PublishVideoError("file missing"),
                      self.video.PublishVideoError("upload rejected", account_invalid=True)):
            with patch.object(self.builder, "_resolve_address", AsyncMock(return_value={})), \
                 patch.object(self.builder, "upload_publish_videos", AsyncMock(side_effect=error)), \
                 patch.object(self.publisher, "mtop_call", new_callable=AsyncMock) as final:
                result = await self.publisher.XianyuDirectPublisher().publish_item({
                    "title": "offline", "description": "offline", "price": 1,
                    "images": ["/static/main.jpg"], "videos": [{"url": "/static/video.mp4"}],
                }, "offline", "acct", 7)
            self.assertFalse(result["success"])
            self.assertIn(str(error), result["message"])
            self.assertEqual(result["account_invalid"], error.account_invalid)
            final.assert_not_awaited()

    async def test_multipart_upload_keeps_file_cover_and_refreshed_cookie(self):
        responses = [
            {"success": True, "cookies_str": "offline-init", "res": {"data": {"model": {
                "uploadId": "upload-id", "uploadUrlList": ["https://oss.example/part"],
                "videoUploadPolicy": {"supportSecondTransfer": False},
            }}}},
            {"success": True, "cookies_str": "offline-complete", "res": {"data": {"model": {
                "fileId": "platform-video", "ossUrl": "https://video.example/file.mp4",
            }}}},
        ]
        with patch.object(self.video, "_read_video", AsyncMock(return_value=(b"video", "test.mp4", "video/mp4"))), \
             patch.object(self.video, "_extract_video_cover", AsyncMock(return_value=(b"cover", 640, 360))), \
             patch.object(self.video, "_fetch_biz_config", AsyncMock(return_value={"apiInfo": {}})), \
             patch.object(self.video, "_put_part", AsyncMock(return_value="part-md5")) as part, \
             patch.object(self.video, "_upload_video_cover", AsyncMock(return_value="https://image.example/cover.jpg")) as cover, \
             patch.object(self.video, "mtop_call", AsyncMock(side_effect=responses)) as mtop, \
             patch.object(self.video, "logger"):
            payload, cookie = await self.video.upload_publish_video(
                {"url": "/static/videos/local.mp4", "thumbnail_url": "/static/local.jpg"},
                "offline-start", "acct", 7)
        self.assertEqual(cookie, "offline-complete")
        self.assertEqual(payload["url"], "https://image.example/cover.jpg")
        self.assertEqual(payload["videoUrl"], "https://video.example/file.mp4")
        self.assertEqual((payload["widthSize"], payload["heightSize"]), (640, 360))
        cover.assert_awaited_once_with(b"cover", "test.mp4", "offline-complete")
        part.assert_awaited_once()
        self.assertEqual(mtop.await_args.kwargs["cookies_str"], "offline-init")

    async def test_real_builder_and_publisher_keep_video_and_enter_guard_once(self):
        events = []
        uploaded = self.video._video_payload({}, "id", "https://video.example/a.mp4",
                                             640, 360, "https://image.example/cover.jpg")
        @asynccontextmanager
        async def guard():
            events.append("guard")
            yield

        async def final_request(**kwargs):
            payload = json.loads(kwargs["data"]["inputJson"])
            self.assertEqual(payload["imageInfoDOList"][0]["videoUrl"], uploaded["videoUrl"])
            self.assertEqual(payload["imageInfoDOList"][0]["url"], uploaded["url"])
            self.assertEqual(kwargs["cookies_str"], "offline-refreshed")
            async with kwargs["request_guard"]():
                events.append("publish")
            return {"success": True, "res": {"data": {"itemId": "123"}}}

        with patch.object(self.builder, "_resolve_address", AsyncMock(return_value={})), \
             patch.object(self.builder, "upload_publish_videos", AsyncMock(return_value=([uploaded], "offline-refreshed"))), \
             patch.object(self.builder, "upload_publish_image", AsyncMock(return_value={"url": "https://image.example/main.jpg"})), \
             patch.object(self.publisher, "mtop_call", AsyncMock(side_effect=final_request)) as final:
            result = await self.publisher.XianyuDirectPublisher().publish_item({
                "title": "offline", "description": "offline", "price": 1,
                "images": ["/static/main.jpg"], "videos": [{"url": "/static/video.mp4"}],
            }, "offline", "acct", 7, guard)
        self.assertTrue(result["success"])
        self.assertEqual(events, ["guard", "publish"])
        final.assert_awaited_once()

    async def test_media_preparation_failure_is_definite_and_never_publishes(self):
        for invalid in (False, True):
            error = self.publisher.DirectPublishError("video preparation failed", account_invalid=invalid)
            with patch.object(self.publisher, "build_item_payload", AsyncMock(side_effect=error)), \
                 patch.object(self.publisher, "mtop_call", new_callable=AsyncMock) as final:
                guard = Mock(side_effect=AssertionError("must not enter final request"))
                result = await self.publisher.XianyuDirectPublisher().publish_item({}, "offline", "acct", 7, guard)
            self.assertFalse(result["success"])
            self.assertFalse(result.get("_request_status_unknown"))
            self.assertEqual(result["account_invalid"], invalid)
            final.assert_not_awaited()
            guard.assert_not_called()
