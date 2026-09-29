from __future__ import annotations

import asyncio
import importlib
import sys
import types
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]

def _install_mtop_stubs():
    dependencies = {
        "common.utils.cookie_refresh": {
            "extract_cookies_from_response": Mock(return_value={}),
            "is_session_expired_error": Mock(return_value=False),
            "mark_account_session_expired": Mock(),
            "merge_cookies": Mock(),
            "trigger_password_login_async": Mock(),
            "update_account_cookies_in_db": AsyncMock(),
        },
        "common.utils.xianyu_utils": {
            "generate_sign": Mock(return_value="sign"),
            "trans_cookies": Mock(return_value={}),
            "canonical_goofish_item_url": Mock(return_value="offline-item-url"),
        },
    }
    for name, attributes in dependencies.items():
        stub = types.ModuleType(name)
        stub.__dict__.update(attributes)
        sys.modules[name] = stub


class _OfflineGuardTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        modules = patch.dict(sys.modules)
        modules.start()
        cls.addClassCleanup(modules.stop)
        for name in list(sys.modules):
            if name in {"common", "app"} or name.startswith(("common.", "app.")):
                del sys.modules[name]
        for name, relative_path in {
            "common": "common", "common.services": "common/services", "common.utils": "common/utils",
            "app": "backend-web/app", "app.services": "backend-web/app/services",
        }.items():
            package = types.ModuleType(name)
            package.__path__ = [str(ROOT / relative_path)]
            sys.modules[name] = package
        _install_mtop_stubs()
        for name, attributes in {
            "common.db.session": {"async_session_maker": Mock(side_effect=AssertionError("禁止真实数据库会话"))},
            "common.services.backend_web_loader": {"load_backend_web_class": Mock()},
            "app.services.amap_inputtips_service": {"AmapInputTipsError": RuntimeError, "AmapInputTipsService": Mock()},
            "common.services.xianyu_publish_media": {
                "PublishMediaError": RuntimeError,
                "upload_publish_image": AsyncMock(side_effect=AssertionError("必须注入离线图片替身")),
            },
            "common.services.xianyu_publish_video": {
                "PublishVideoError": RuntimeError,
                "upload_publish_videos": AsyncMock(side_effect=AssertionError("必须注入离线视频替身")),
            },
        }.items():
            stub = types.ModuleType(name)
            stub.__dict__.update(attributes)
            sys.modules[name] = stub
        for target in ("socket.create_connection", "socket.getaddrinfo"):
            blocker = patch(target, side_effect=AssertionError("离线测试禁止真实网络访问"))
            blocker.start()
            cls.addClassCleanup(blocker.stop)

    async def asyncSetUp(self):
        # Windows 事件循环创建内部 socketpair 后再阻断连接。
        for target in ("socket.socket.connect", "socket.socket.connect_ex"):
            self.enterContext(patch(target, side_effect=AssertionError("离线测试禁止真实网络访问")))


class _Response:
    def __init__(self, payload=None, status=200, error=None):
        self.payload = payload
        self.status = status
        self.error = error
        self.cookies = {}

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self.payload


class _Session:
    def __init__(self, response, calls):
        self.response = response
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


class MtopGuardBoundaryTests(_OfflineGuardTests):
    async def call_mtop(self, response, guard=None, calls=None):
        module = importlib.import_module("common.services.xianyu_mtop")
        calls = calls if calls is not None else []
        session = _Session(response, calls)
        with patch.object(module.aiohttp, "ClientSession", return_value=session), \
             patch.object(module, "trans_cookies", return_value={}), \
             patch.object(module, "generate_sign", return_value="sign"):
            return await module.mtop_call(
                account_id="offline-account",
                cookies_str="offline-cookie",
                api="mtop.test.publish",
                version="1.0",
                data={"value": "offline"},
                request_guard=guard,
            )

    async def test_guard_wraps_http_and_response_parsing(self):
        events = []
        calls = []

        @asynccontextmanager
        async def guard():
            events.append("guard-enter")
            yield
            events.append("guard-exit")

        response = await self.call_mtop(_Response({"ret": ["SUCCESS::OK"]}), guard, calls)
        self.assertTrue(response["success"])
        self.assertEqual(events, ["guard-enter", "guard-exit"])
        self.assertEqual(len(calls), 1)

    async def test_guard_rejection_makes_zero_http_requests(self):
        calls = []

        @asynccontextmanager
        async def guard():
            raise RuntimeError("schedule rejected")
            yield

        with self.assertRaisesRegex(RuntimeError, "schedule rejected"):
            await self.call_mtop(_Response({"ret": ["SUCCESS::OK"]}), guard, calls)
        self.assertEqual(calls, [])

    async def test_guarded_network_error_is_unknown_and_sent_once(self):
        calls = []
        response = _Response(error=OSError("offline network"))

        @asynccontextmanager
        async def guard():
            yield

        result = await self.call_mtop(response, guard, calls)
        self.assertFalse(result["success"])
        self.assertTrue(result["_request_status_unknown"])
        self.assertEqual(len(calls), 1)

    async def test_guarded_invalid_response_is_unknown_and_sent_once(self):
        calls = []

        @asynccontextmanager
        async def guard():
            yield

        result = await self.call_mtop(_Response({"unexpected": True}), guard, calls)
        self.assertFalse(result["success"])
        self.assertTrue(result["_request_status_unknown"])
        self.assertEqual(len(calls), 1)

    async def test_guarded_empty_or_unconfirmed_ret_code_is_unknown(self):
        for ret in (
            [], [None], [""], ["SUCCESS"], ["::missing-code"], ["  ::missing-code"],
            ["PLATFORM_CODE::message"], ["PLATFORM_CODE::captcha"], ["NOT_SUCCESS::OK"],
            ["FAIL_::message"], ["FAIL_bad code::message"],
            ["SUCCESS::OK", "FAIL_BIZ_REJECTED::拒绝"],
        ):
            with self.subTest(ret=ret):
                calls = []

                @asynccontextmanager
                async def guard():
                    yield

                result = await self.call_mtop(_Response({"ret": ret}), guard, calls)
                self.assertFalse(result["success"])
                self.assertTrue(result["_request_status_unknown"])
                self.assertIn("对账", result["error"])
                self.assertEqual(len(calls), 1)

    async def test_guard_exit_error_after_http_is_propagated_once(self):
        calls = []

        @asynccontextmanager
        async def guard():
            yield
            raise RuntimeError("lease release failed")

        with self.assertRaisesRegex(RuntimeError, "lease release failed"):
            await self.call_mtop(_Response({"ret": ["SUCCESS::OK"]}), guard, calls)
        self.assertEqual(len(calls), 1)

    async def test_guarded_token_rejection_is_failed_without_retry(self):
        calls = []

        @asynccontextmanager
        async def guard():
            yield

        result = await self.call_mtop(
            _Response({"ret": ["FAIL_SYS_TOKEN_EXPIRED::拒绝"]}), guard, calls
        )
        self.assertFalse(result["success"])
        self.assertFalse(result.get("_request_status_unknown", False))
        self.assertIn("FAIL_SYS_TOKEN_EXPIRED", result["error"])
        self.assertEqual(len(calls), 1)

    async def test_non_guard_path_keeps_normal_success_call(self):
        calls = []
        result = await self.call_mtop(_Response({"ret": ["SUCCESS::OK"]}), None, calls)
        self.assertTrue(result["success"])
        self.assertEqual(len(calls), 1)


class PublisherMediaGuardTests(_OfflineGuardTests):
    async def test_direct_and_personal_publishers_prepare_before_guard(self):
        direct = importlib.import_module("app.services.xianyu_direct_publisher")
        personal = importlib.import_module("app.services.xianyu_personal_publisher")
        events = []

        @asynccontextmanager
        async def guard():
            events.append("guard-enter")
            yield
            events.append("guard-exit")

        async def fake_mtop(**kwargs):
            events.append("mtop")
            async with kwargs["request_guard"]():
                events.append("http")
            return {"success": True, "res": {"itemId": "offline-item"}, "cookies_str": kwargs["cookies_str"]}

        async def fake_direct_payload(*args, **kwargs):
            events.append("direct-media-ready")
            return {"imageInfoDOList": []}, "offline-cookie"

        async def fake_personal_image(*args, **kwargs):
            events.append("personal-image-ready")
            return {"url": "offline-image"}

        with patch.object(direct, "build_item_payload", new=AsyncMock(side_effect=fake_direct_payload)), \
             patch.object(direct, "mtop_call", new=AsyncMock(side_effect=fake_mtop)), \
             patch.object(personal, "_resolve_item_address", new=AsyncMock(return_value={"divisionId": "1", "gps": "2,3", "poiId": "4", "poiName": "离线地址"})), \
             patch.object(personal, "upload_publish_image", new=AsyncMock(side_effect=fake_personal_image)), \
             patch.object(personal, "mtop_call", new=AsyncMock(side_effect=fake_mtop)):
            await direct.XianyuDirectPublisher().publish_item(
                {"title": "标题", "description": "描述"}, "offline-cookie", "acct", 1, guard
            )
            self.assertEqual(events, ["direct-media-ready", "mtop", "guard-enter", "http", "guard-exit"])
            events.clear()
            await personal.XianyuPersonalPublisher().publish_item(
                {"title": "标题", "description": "描述", "price": "10", "images": ["image"]},
                "offline-cookie", "acct", 1, guard,
            )
        self.assertEqual(events, ["personal-image-ready", "mtop", "guard-enter", "http", "guard-exit"])


class PublisherGuardWiringTests(_OfflineGuardTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = importlib.import_module("common.services.xianyu_publish_service")

    async def test_both_publishers_receive_guard(self):
        guard = Mock(name="request_guard")
        direct = Mock(return_value=Mock(publish_item=AsyncMock(return_value={"success": True})))
        personal = Mock(return_value=Mock(publish_item=AsyncMock(return_value={"success": True})))
        with patch.object(self.module, "get_xianyu_direct_publisher_class", return_value=direct), \
             patch.object(self.module, "get_xianyu_personal_publisher_class", return_value=personal):
            await self.module.publish_single_item({}, "cookie", account_id="a", owner_id=1, request_guard=guard)
            await self.module.publish_personal_single_item({}, "cookie", account_id="a", owner_id=1, request_guard=guard)
        direct.return_value.publish_item.assert_awaited_once()
        personal.return_value.publish_item.assert_awaited_once()
        self.assertIs(direct.return_value.publish_item.await_args.kwargs["request_guard"], guard)
        self.assertIs(personal.return_value.publish_item.await_args.kwargs["request_guard"], guard)


if __name__ == "__main__":
    unittest.main()
