"""视频协议离线回归：执行实际解析/路由/发送函数，网络与数据库用替身。"""
import ast
import asyncio
import base64
import importlib.util
import io
import json
import os
import re
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
logger = Mock()


def definitions(path, names, scope=None, class_name=None):
    """仅隔离模块导入副作用，不替换被测函数体。"""
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))
    nodes = tree.body
    if class_name:
        nodes = next(n for n in nodes if isinstance(n, ast.ClassDef) and n.name == class_name).body
    selected = [n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in names]
    assert {n.name for n in selected} == set(names)
    for node in selected:
        node.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *selected], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"logger": logger, "json": json, "base64": base64, "asyncio": asyncio, "time": time, **(scope or {})}
    exec(compile(module, path, "exec"), namespace)
    return namespace


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VideoTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # 仅 logger 替身；使用真实公共解码器、解析器和媒体 ID 实现。
        cls.log_patch = patch.dict(sys.modules, {"loguru": SimpleNamespace(logger=logger)})
        cls.log_patch.start()
        from common.utils import xianyu_message_parser, xianyu_video
        cls.parser = xianyu_message_parser
        cls.video = xianyu_video
        cls.push_module = load_module("video_push_test", "backend-web/app/services/chat_new/push_message_parser.py")
        cls.history = definitions("backend-web/app/api/routes/chat_new.py", ["_parse_message", "_extract_message_summary"], {
            "load_content_json": cls.parser.load_content_json,
            "interpret_content": cls.parser.interpret_content,
            "extract_video_fields": cls.video.extract_video_fields,
        })

    @classmethod
    def tearDownClass(cls):
        cls.log_patch.stop()

    def payload(self, **video):
        return {"contentType": 4, "video": {"url": "https://gw.alicdn.com/video.mp4", "poster": "https://gw.alicdn.com/cover.jpg", **video}}

    def envelope(self, payload, encoded=False, reminder=True):
        data = json.dumps(payload)
        if encoded:
            data = base64.b64encode(data.encode()).decode()
        return {"1": {"1": {"1": "buyer@goofish"}, "2": "cid@goofish", "3": "v1", "5": 1000,
                      "10": {"senderUserId": "buyer@goofish", "senderNick": "buyer", **({"reminderContent": "[视频]"} if reminder else {})},
                      "6": {"3": {"1" if encoded else "5": data}}}}

    def test_history_and_push_video_fields(self):
        payload = self.payload()
        model = {"message": {"messageId": "v1", "extension": {"senderUserId": "buyer@goofish"},
                             "content": {"custom": {"data": base64.b64encode(json.dumps(payload).encode()).decode()}}, "createAt": 1000}}
        history = self.history["_parse_message"](model, "seller")
        self.assertEqual(history["type"], "video")
        self.assertEqual(history["videoUrl"], payload["video"]["url"])
        self.assertEqual(history["videoCoverUrl"], payload["video"]["poster"])
        self.assertEqual(history["images"], [])
        self.assertEqual(self.history["_extract_message_summary"](model["message"]), "[视频]")
        parser = self.push_module.PushMessageParser("account", "seller")
        for encoded in (False, True):
            for reminder in (False, True):
                with self.subTest(encoded=encoded, reminder=reminder):
                    pushed = parser.parse(self.envelope(payload, encoded, reminder))["message"]
                    for key in ("type", "videoUrl", "videoCoverUrl", "images", "messageId", "senderId"):
                        self.assertEqual(pushed[key], history[key])

    def test_video_aliases_and_media_ids(self):
        # @ fixarray: [6, 0, 720, 1280]，$ fixarray: [0, 0, 'mp4', 0, 1280, 720]。
        at = base64.urlsafe_b64encode(b'\x94\x06\x00\xcd\x02\xd0\xcd\x05\x00').decode().rstrip('=')
        dollar = base64.urlsafe_b64encode(b'\x96\x00\x00\xa3mp4\x00\xcd\x05\x00\xcd\x02\xd0').decode().rstrip('=')
        fields = self.video.extract_video_fields({"video": {"videoMediaId": "@" + at, "picMediaId": "$" + dollar}})
        self.assertEqual(fields["videoUrl"], f"https://down.im.dingtalk.cn/media/{at}_1280_720.mp4")
        self.assertEqual(fields["videoCoverUrl"], f"https://down.im.dingtalk.cn/ddmedia/{dollar}.mp4")
        self.assertEqual(self.video.resolve_video_media_url("@" + at, "https://media.dingtalk.cn"), f"https://media.dingtalk.cn/media/{at}_1280_720.mp4")
        aliases = {"contentType": "4", "video": {"videoUrl": "https://gw.alicdn.com/v.mp4", "coverUrl": "https://gw.alicdn.com/p.jpg"}}
        self.assertEqual(self.parser.interpret_content(aliases)[2], "video")
        self.assertEqual(self.video.extract_video_fields(aliases)["videoCoverUrl"], aliases["video"]["coverUrl"])

    def test_malformed_video_keeps_placeholder(self):
        for payload in ({"contentType": 4}, {"contentType": 4, "video": None}, self.payload(url="@invalid"), self.payload(url="https://[")):
            with self.subTest(payload=payload):
                self.assertEqual(self.parser.interpret_content(payload), ("[视频]", [], "video"))
                result = self.push_module.PushMessageParser("a", "s").parse(self.envelope(payload))
                self.assertEqual(result["message"]["type"], "video")
                self.assertEqual(result["message"]["videoUrl"], "")

    def test_existing_text_image_audio_unchanged(self):
        for payload, expected in [
            ({"contentType": 1, "text": {"text": "hello"}}, ("hello", [], "text")),
            ({"contentType": 2, "image": {"pics": [{"url": "image"}]}}, ("", ["image"], "image")),
            ({"contentType": 3, "audio": {}}, ("[语音消息]", [], "text")),
            ({"picUrl": "legacy"}, ("", ["legacy"], "image")),
        ]:
            self.assertEqual(self.parser.interpret_content(payload), expected)

    def test_auto_reply_push_video(self):
        scope = definitions("websocket/app/services/xianyu/message_handler.py", ["parse_chat_message", "is_chat_message"], {
            "decode_first_content": self.parser.decode_first_content,
            "interpret_content": self.parser.interpret_content,
            "extract_video_fields": self.video.extract_video_fields, "safe_str": str,
        }, "MessageHandler")
        handler = SimpleNamespace(cookie_id="a", _extract_item_id=lambda msg: "item")
        for reminder in (False, True):
            self.assertTrue(scope["is_chat_message"](handler, self.envelope(self.payload(), reminder=reminder)))
            result = scope["parse_chat_message"](handler, self.envelope(self.payload(), reminder=reminder))
            self.assertEqual(result["type"], "video")
            self.assertEqual(result["send_message"], "https://gw.alicdn.com/video.mp4")
            self.assertEqual(result["videoCoverUrl"], "https://gw.alicdn.com/cover.jpg")

    async def test_send_video_protocol_and_rejections(self):
        scope = definitions("backend-web/app/services/chat_new/im_client.py", ["send_video_message", "_raise_if_send_rejected"], {
            "make_video_content": self.video.make_video_content,
            "generate_mid": lambda: "mid", "generate_uuid": lambda: "uuid",
        }, "GoofishImClient")
        captured = []
        response = {"code": 200, "body": {"messageId": "server-id"}}

        async def send(factory, **kwargs):
            captured.append((factory(), kwargs))
            return response

        client = SimpleNamespace(myid="seller", _send_and_wait_with_retry=send, _raise_if_send_rejected=scope["_raise_if_send_rejected"])
        result = await scope["send_video_message"](client, "cid", "buyer", "https://gw.alicdn.com/v.mp4", 1280, 720, 5400, "https://gw.alicdn.com/p.jpg")
        self.assertEqual(result["messageId"], "server-id")
        (_, message), options = captured[0]
        self.assertEqual(options, {"retry_after_reconnect": False})
        self.assertEqual(message["body"][0]["cid"], "cid@goofish")
        self.assertEqual(message["body"][1]["actualReceivers"], ["buyer@goofish", "seller@goofish"])
        payload = json.loads(base64.b64decode(message["body"][0]["content"]["custom"]["data"]))
        self.assertEqual(payload, {"contentType": 4, "video": {"url": "https://gw.alicdn.com/v.mp4", "width": 1280, "height": 720, "duration": 5400, "durationMs": 5400, "poster": "https://gw.alicdn.com/p.jpg", "coverUrl": "https://gw.alicdn.com/p.jpg"}})
        for failure in ({"code": 400}, {"code": 200, "body": {}}, {"code": 200, "body": {"reason": "CSI_FORBID"}}):
            response = failure
            before = len(captured)
            with self.assertRaises(Exception):
                await scope["send_video_message"](client, "cid", "buyer", "https://gw.alicdn.com/v.mp4")
            self.assertEqual(len(captured), before + 1)

    async def test_video_route_guards_cleanup_and_failures(self):
        uploaded_paths = []
        client = SimpleNamespace(is_connected=True, cookies_str="test-cookie", send_video_message=AsyncMock(return_value={"messageId": "id"}))
        owner = AsyncMock(return_value=True)
        upload = AsyncMock(return_value="https://gw.alicdn.com/v.mp4")

        class Uploader:
            def __init__(self, cookie): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def upload_video(self, path, mime):
                uploaded_paths.append(path)
                self_data = Path(path).read_bytes()
                self_assert(self_data == b"video")
                return await upload(path, mime)

        self_assert = self.assertTrue
        scope = definitions("backend-web/app/api/routes/chat_new_video.py", ["send_video"], {
            "Form": lambda *a, **k: None, "File": lambda *a, **k: None, "Depends": lambda *a: None,
            "get_current_active_user": None, "get_db_session": None,
            "_get_owned_chat_account": owner, "get_im_session_manager": lambda: SimpleNamespace(clients={"a": client}),
            "ApiResponse": lambda **k: SimpleNamespace(**k), "os": os, "tempfile": tempfile,
            "MAX_CHAT_VIDEO_SIZE": 8, "ChatVideoUploader": Uploader,
            "probe_chat_video": lambda path: {"width": 10, "height": 20, "duration_ms": 30},
        })

        async def call(data=b"video", mime="video/mp4"):
            file = io.BytesIO(data)
            upload_file = SimpleNamespace(filename="video.mp4", content_type=mime, read=AsyncMock(side_effect=file.read))
            return await scope["send_video"]("a", "cid", "buyer", upload_file, object(), object())

        owner.return_value = False
        self.assertFalse((await call()).success)
        upload.assert_not_awaited()
        owner.return_value = True
        for data, mime in ((b"", "video/mp4"), (b"x" * 9, "video/mp4"), (b"video", "text/plain")):
            self.assertFalse((await call(data, mime)).success)
        upload.assert_not_awaited()
        client.is_connected = False
        self.assertFalse((await call()).success)
        client.is_connected = True
        result = await call()
        self.assertTrue(result.success)
        self.assertEqual(result.data["messageId"], "id")
        client.send_video_message.assert_awaited_once_with(cid="cid", to_user_id="buyer", video_url="https://gw.alicdn.com/v.mp4", width=10, height=20, duration_ms=30)
        client.send_video_message.reset_mock()
        upload.side_effect = RuntimeError("upload failure")
        self.assertFalse((await call()).success)
        client.send_video_message.assert_not_awaited()
        upload.side_effect = None
        client.send_video_message.side_effect = RuntimeError("rejected")
        self.assertFalse((await call()).success)
        for path in uploaded_paths:
            self.assertFalse(Path(path).exists(), "temporary video must be removed")

    async def test_uploader_uses_chat_file_endpoint_without_image_compression(self):
        module = load_module("chat_video_upload_test", "common/utils/chat_video_uploader.py")
        uploader = module.ChatVideoUploader("test-cookie")
        response = SimpleNamespace(status=200, text=AsyncMock(return_value='{"data":{"url":"https://gw.alicdn.com/v.mp4"}}'))

        class ResponseContext:
            async def __aenter__(self): return response
            async def __aexit__(self, *args): pass

        uploader.session = SimpleNamespace(post=Mock(return_value=ResponseContext()))
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            handle.write(b"video")
            path = handle.name
        try:
            url = await uploader.upload_video(path, "video/mp4")
            self.assertEqual(url, "https://gw.alicdn.com/v.mp4")
            args, kwargs = uploader.session.post.call_args
            self.assertEqual(args[0], "https://stream-upload.goofish.com/api/upload.api?floderId=0&appkey=xy_chat&_input_charset=utf-8")
            self.assertEqual(kwargs["timeout"].total, 180)
            self.assertEqual(kwargs["headers"]["cookie"], "test-cookie")
            response.status = 500
            with self.assertRaises(RuntimeError): await uploader.upload_video(path, "video/mp4")
            response.status = 200
            response.text.return_value = '<html>login</html>'
            with self.assertRaises(RuntimeError): await uploader.upload_video(path, "video/mp4")
            response.text.return_value = '{}'
            with self.assertRaises(RuntimeError): await uploader.upload_video(path, "video/mp4")
        finally:
            os.remove(path)

    def test_video_proxy_domain_restriction(self):
        scope = definitions("backend-web/app/api/routes/chat_new_video.py", ["_allowed_video_url"], {"urlsplit": urlsplit})
        allowed = scope["_allowed_video_url"]
        self.assertTrue(allowed("https://down.im.dingtalk.cn/media/test.mp4"))
        for url in ("http://down.im.dingtalk.cn/test", "https://127.0.0.1/test", "https://dingtalk.cn.evil.test/test", "https://user:pass@dingtalk.cn/test", "https://dingtalk.cn:123/test"):
            self.assertFalse(allowed(url))

    async def test_video_proxy_range_redirect_and_cleanup(self):
        import httpx

        class Upstream:
            def __init__(self, status=206, location=None):
                self.status_code = status
                self.is_redirect = status == 302
                self.headers = {"content-type": "video/mp4", "content-range": "bytes 0-4/10", "accept-ranges": "bytes", "content-length": "5"}
                if location: self.headers["location"] = location
                self.closed = False
            async def aclose(self): self.closed = True
            async def aiter_raw(self): yield b"video"

        class Client:
            def __init__(self, responses): self.responses, self.requests, self.closed = responses, [], False
            def build_request(self, method, url, headers):
                self.requests.append((url, headers))
                return url
            async def send(self, request, stream): return self.responses.pop(0)
            async def aclose(self): self.closed = True

        def response(content=None, status_code=200, **kwargs):
            return SimpleNamespace(content=content, status_code=status_code, **kwargs)

        upstream = Upstream()
        client = Client([upstream])
        http = SimpleNamespace(AsyncClient=lambda **kw: client, HTTPError=httpx.HTTPError)
        scope = definitions("backend-web/app/api/routes/chat_new_video.py", ["_allowed_video_url", "video_proxy"], {
            "urlsplit": urlsplit, "urljoin": urljoin, "re": re, "httpx": http,
            "Query": lambda *a, **kw: None, "Response": response, "StreamingResponse": response,
        })
        result = await scope["video_proxy"](SimpleNamespace(headers={"range": "bytes=0-4"}), "https://down.im.dingtalk.cn/v.mp4")
        self.assertEqual(result.status_code, 206)
        self.assertEqual(result.headers["content-range"], "bytes 0-4/10")
        self.assertEqual(client.requests[0][1]["Range"], "bytes=0-4")
        self.assertEqual(b"".join([chunk async for chunk in result.content]), b"video")
        self.assertTrue(client.closed and upstream.closed)
        redirect = Upstream(302, "https://127.0.0.1/private")
        client = Client([redirect])
        result = await scope["video_proxy"](SimpleNamespace(headers={}), "https://down.im.dingtalk.cn/v.mp4")
        self.assertEqual(result.status_code, 403)
        self.assertEqual(len(client.requests), 1)
        self.assertTrue(client.closed and redirect.closed)
        result = await scope["video_proxy"](SimpleNamespace(headers={"range": "bytes=0-1,3-4"}), "https://down.im.dingtalk.cn/v.mp4")
        self.assertEqual(result.status_code, 416)

    def test_probe_rejects_invalid_video_and_releases_capture(self):
        module = load_module("chat_video_probe_test", "common/utils/chat_video_uploader.py")
        capture = SimpleNamespace(read=Mock(return_value=(True, object())), get=lambda prop: {1: 1280, 2: 720, 3: 90, 4: 30}[prop], release=Mock())
        cv = SimpleNamespace(VideoCapture=lambda path: capture, CAP_PROP_FRAME_WIDTH=1, CAP_PROP_FRAME_HEIGHT=2, CAP_PROP_FRAME_COUNT=3, CAP_PROP_FPS=4)
        with patch.dict(sys.modules, {"cv2": cv}):
            self.assertEqual(module.probe_chat_video("local.mp4"), {"width": 1280, "height": 720, "duration_ms": 3000})
            capture.read.return_value = (False, None)
            with self.assertRaises(ValueError): module.probe_chat_video("invalid.mp4")
        self.assertEqual(capture.release.call_count, 2)


if __name__ == "__main__":
    unittest.main()
