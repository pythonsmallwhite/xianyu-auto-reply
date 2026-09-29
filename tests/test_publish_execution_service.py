"""公共发布执行链路的离线回归：真实日志服务、内存 SQLite、导入前替身。"""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]


class PublishExecutionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # 包和子模块一起隔离，恢复时保留其他测试已加载模块的原始对象。
        modules = patch.dict(sys.modules)
        modules.start()
        cls.addClassCleanup(modules.stop)
        for name in list(sys.modules):
            if name == "common" or name.startswith("common."):
                del sys.modules[name]
        for name in ("common", "common.db", "common.services", "common.utils"):
            package = types.ModuleType(name)
            package.__path__ = [str(ROOT / name.replace(".", "/"))]
            sys.modules[name] = package

        for target in ("socket.create_connection", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("离线测试禁止真实网络访问"))
            guard.start()
            cls.addClassCleanup(guard.stop)

        def blocked_session(*args, **kwargs):
            raise AssertionError("离线测试禁止使用真实数据库会话")

        dependencies = {
            "common.db.session": {"async_session_maker": blocked_session},
            "common.services.item_service": {"ItemService": Mock()},
            "common.services.publish_address_service": {"PublishAddressService": Mock()},
            "common.services.internal_product_service": {"InternalProductService": Mock()},
            "common.services.publish_capacity_service": {
                "reserve_publish_capacity": AsyncMock(side_effect=AssertionError("必须注入离线容量替身")),
                "settle_publish_capacity": AsyncMock(),
            },
            "common.services.xianyu_publish_service": {
                "detect_publish_account_capability": AsyncMock(),
                "ensure_publish_capability_reliable": Mock(),
                "publish_single_item": AsyncMock(side_effect=AssertionError("必须注入离线平台替身")),
                "publish_personal_single_item": AsyncMock(side_effect=AssertionError("必须注入离线平台替身")),
            },
        }
        for name, attributes in dependencies.items():
            stub = types.ModuleType(name)
            stub.__dict__.update(attributes)
            sys.modules[name] = stub

        from common.db.base_class import Base
        from common.models.publish_log import PublishLog
        from common.models.xy_account import XYAccount
        from common.services.publish_log_service import PublishLogService

        cls.module = importlib.import_module("common.services.publish_execution_service")
        cls.session_stub = sys.modules["common.db.session"]
        cls.internal_stub = sys.modules["common.services.internal_product_service"]
        cls.Base, cls.Log, cls.Account, cls.LogService = Base, PublishLog, XYAccount, PublishLogService

    async def asyncSetUp(self):
        # Windows 事件循环先创建内部 socketpair，再阻断业务代码的所有连接。
        for target in ("socket.socket.connect", "socket.socket.connect_ex"):
            self.enterContext(patch(target, side_effect=AssertionError("离线测试禁止真实网络访问")))
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.addAsyncCleanup(self.engine.dispose)
        self.enterContext(patch.object(self.engine.sync_engine.dialect.type_compiler_instance, "visit_BIGINT", return_value="INTEGER"))
        self.maker = async_sessionmaker(self.engine, expire_on_commit=False)
        self.enterContext(patch.object(self.session_stub, "async_session_maker", self.maker))
        self.enterContext(patch.object(self.module, "async_session_maker", self.maker))
        self.enterContext(patch.object(self.module, "SYNC_AFTER_PUBLISH_DELAY_SECONDS", 0))
        self.enterContext(patch.object(self.module, "logger"))
        self.assertIs(self.module.PublishLogService, self.LogService)

        self.events = []
        self.before = AsyncMock(side_effect=lambda: self.events.append("before_publish"))
        self.guard_events = []
        self.request_guard = None
        self.detect = self.enterContext(patch.object(
            self.module, "detect_publish_account_capability", new=AsyncMock(return_value={"success": True, "is_fish_shop": True}),
        ))
        self.reliable = self.enterContext(patch.object(
            self.module, "ensure_publish_capability_reliable", new=Mock(side_effect=lambda value: value),
        ))
        self.shop = self.enterContext(patch.object(self.module, "publish_single_item", new=AsyncMock(side_effect=self.platform_result)))
        self.personal = self.enterContext(patch.object(self.module, "publish_personal_single_item", new=AsyncMock(side_effect=self.platform_result)))
        self.reserve = self.enterContext(patch.object(self.module, "reserve_publish_capacity", new=AsyncMock(return_value="reserved")))
        self.settle = self.enterContext(patch.object(self.module, "settle_publish_capacity", new=AsyncMock()))
        self.resolve = AsyncMock(side_effect=self.resolve_address)
        self.enterContext(patch.object(self.module, "PublishAddressService", new=Mock(return_value=types.SimpleNamespace(resolve_publish_address=self.resolve))))
        self.sync = AsyncMock(return_value={"success": True, "total_count": 1, "saved_count": 1})
        self.enterContext(patch.object(self.module, "ItemService", new=Mock(return_value=types.SimpleNamespace(fetch_all_items_from_account=self.sync))))
        self.bind = AsyncMock()
        self.enterContext(patch.object(self.internal_stub, "InternalProductService", new=Mock(return_value=types.SimpleNamespace(bind_successful_publish_log=self.bind))))
        self.item = {"id": 11, "title": "离线素材", "description": "测试描述", "price": "10.00"}

        async with self.engine.begin() as conn:
            await conn.run_sync(lambda sync: self.Base.metadata.create_all(sync, tables=[self.Log.__table__, self.Account.__table__]))
        async with self.maker() as session:
            session.add(self.Account(id=1, owner_id=7, account_id="acct", cookie="offline", login_method="cookie"))
            await session.commit()

    async def platform_result(self, **kwargs):
        self.events.append("platform")
        return {"success": True, "item_id": "offline-item", "message": "发布成功"}

    async def resolve_address(self, account_id, item_data):
        # 替身仅实现地址服务的返回契约；测试断言执行器实际传入和落库的数据。
        manual = bool(item_data.get("address"))
        fields = {
            "resolved_address_id": None if manual else 23,
            "resolved_address_text": item_data["address"] if manual else "地址库测试地址",
            "address_source": "material" if manual else "global_pool",
        }
        expected = item_data.get("address_expected_text") if manual else "地址库校验文本"
        return types.SimpleNamespace(
            apply_to_item_data=lambda data: {**data, "address": fields["resolved_address_text"], "address_expected_text": expected},
            to_log_fields=lambda: dict(fields),
        )

    async def prepare_log(self, **overrides):
        values = {"user_id": 7, "account_id": "acct", "title": self.item["title"], "material_id": 11, "batch_id": "batch-1", "status": "pending"}
        values.update(overrides)
        async with self.maker() as session:
            return await self.LogService(session).create_log(**values)

    async def logs(self):
        async with self.maker() as session:
            return list((await session.scalars(select(self.Log).order_by(self.Log.id))).all())

    async def execute(self, **overrides):
        kwargs = {"user_id": 7, "account_id": "acct", "item_data": self.item, "before_publish": self.before}
        kwargs.update(overrides)
        async with self.maker() as session:
            return await self.module.execute_single_publish(session=session, **kwargs)

    async def test_prepared_log_checks_owner_account_batch_and_pending_status(self):
        cases = [
            {"user_id": 8}, {"account_id": "other"}, {"batch_id": "other-batch"},
            *({"status": status} for status in ("publishing", "success", "failed", "unknown", "skipped")),
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                log = await self.prepare_log(**changes)
                with self.assertRaisesRegex(ValueError, "禁止重复发布"):
                    await self.execute(batch_id="batch-1", prepared_log_id=log.id)
                current = (await self.logs())[-1]
                self.assertEqual(
                    (current.user_id, current.account_id, current.batch_id, current.status),
                    (log.user_id, log.account_id, log.batch_id, log.status),
                )
        with self.assertRaisesRegex(ValueError, "禁止重复发布"):
            await self.execute(batch_id="batch-1", prepared_log_id=999999)
        self.assertEqual(len(await self.logs()), len(cases))
        for dependency in (self.resolve, self.reserve, self.detect, self.before, self.shop, self.personal, self.settle, self.sync, self.bind):
            dependency.assert_not_awaited()

    async def test_before_publish_runs_once_before_each_platform_route_and_replay_is_blocked(self):
        for is_shop in (True, False):
            with self.subTest(is_fish_shop=is_shop):
                self.events.clear()
                for dependency in (self.before, self.shop, self.personal, self.reserve, self.settle):
                    dependency.reset_mock()
                self.detect.return_value = {"success": True, "is_fish_shop": is_shop}
                log = await self.prepare_log()
                result = await self.execute(batch_id="batch-1", prepared_log_id=log.id)
                self.assertTrue(result["success"])
                self.assertEqual(result["log_id"], log.id)
                self.assertEqual(self.events, ["before_publish", "platform"])
                selected, unused = (self.shop, self.personal) if is_shop else (self.personal, self.shop)
                selected.assert_awaited_once()
                unused.assert_not_awaited()
                self.before.assert_awaited_once_with()
                self.reserve.assert_awaited_once_with(7, "acct", log.id)
                with self.assertRaisesRegex(ValueError, "禁止重复发布"):
                    await self.execute(batch_id="batch-1", prepared_log_id=log.id)
                self.before.assert_awaited_once()
                selected.assert_awaited_once()
                self.reserve.assert_awaited_once()
                self.settle.assert_awaited_once_with(log.id, "success", item_id="offline-item", error_message=None)
                self.assertEqual(self.events, ["before_publish", "platform"])
        self.assertEqual([(log.status, log.item_id) for log in await self.logs()], [("success", "offline-item")] * 2)

    async def test_request_guard_starts_after_preparation_and_before_publish_http(self):
        log = await self.prepare_log()
        events = []

        @asynccontextmanager
        async def guard():
            events.append("guard-enter")
            yield
            events.append("guard-exit")

        async def publish(**kwargs):
            events.append("prepared")
            async with kwargs["request_guard"]():
                events.append("http")
            return await self.platform_result(**kwargs)

        self.shop.side_effect = publish
        result = await self.execute(
            batch_id="batch-1", prepared_log_id=log.id, request_guard=guard
        )
        self.assertTrue(result["success"])
        self.assertEqual(events, ["prepared", "guard-enter", "http", "guard-exit"])
        self.assertEqual(self.events, ["before_publish", "platform"])
        self.before.assert_awaited_once_with()
        self.assertTrue(self.shop.await_args.kwargs["request_guard"])

    async def test_guard_exit_errors_keep_unknown_log_and_capacity(self):
        from common.utils.batch_schedule import PublishScheduleDeferred, PublishWindowExpired

        async def publish(**kwargs):
            async with kwargs["request_guard"]():
                self.events.append("http")
            return await self.platform_result(**kwargs)

        self.shop.side_effect = publish
        errors = (RuntimeError("lease release failed"), PublishScheduleDeferred(), PublishWindowExpired())
        for index, error in enumerate(errors, 1):
            with self.subTest(error=type(error).__name__):
                self.events.clear()
                self.before.reset_mock()
                self.shop.reset_mock()
                log = await self.prepare_log(batch_id=f"guard-batch-{index}")

                @asynccontextmanager
                async def guard():
                    yield
                    raise error

                result = await self.execute(
                    batch_id=f"guard-batch-{index}",
                    prepared_log_id=log.id,
                    request_guard=guard,
                )
                self.assertFalse(result["success"])
                self.assertTrue(result["unknown"])
                self.assertEqual(result["log_id"], log.id)
                current = (await self.logs())[-1]
                self.assertEqual((current.id, current.status), (log.id, "unknown"))
                self.settle.assert_awaited_with(log.id, "unknown", error_message=str(error))
                self.assertEqual(self.events, ["before_publish", "http"])

    async def test_batch_resolves_pool_address_and_persists_it_on_prepared_log_before_publish(self):
        self.item.update(address="素材旧地址", address_expected_text="素材旧校验文本")
        original = deepcopy(self.item)
        log = await self.prepare_log(resolved_address_id=99, resolved_address_text="旧日志地址", address_source="material")

        async def publish(**kwargs):
            current, = await self.logs()
            self.assertEqual((current.id, current.status), (log.id, "pending"))
            self.assertEqual(
                (current.resolved_address_id, current.resolved_address_text, current.address_source),
                (23, "地址库测试地址", "global_pool"),
            )
            return await self.platform_result(**kwargs)

        self.shop.side_effect = publish
        result = await self.execute(batch_id="batch-1", prepared_log_id=log.id)
        self.assertTrue(result["success"])
        self.resolve.assert_awaited_once_with("acct", {key: value for key, value in original.items() if key not in {"address", "address_expected_text"}})
        payload = self.shop.await_args.kwargs["item_data"]
        self.assertEqual((payload["address"], payload["address_expected_text"]), ("地址库测试地址", "地址库校验文本"))
        self.assertEqual(self.item, original)
        current, = await self.logs()
        self.assertEqual((current.id, current.batch_id, current.status), (log.id, "batch-1", "success"))
        self.assertEqual((current.resolved_address_id, current.resolved_address_text, current.address_source), (23, "地址库测试地址", "global_pool"))
        self.bind.assert_awaited_once_with(owner_id=7, publish_log_id=log.id)

    async def test_single_publish_keeps_manual_address_and_creates_real_log(self):
        self.item.update(address="手工测试地址", address_expected_text="手工校验文本")
        original = deepcopy(self.item)
        result = await self.execute()
        self.assertTrue(result["success"])
        self.resolve.assert_awaited_once_with("acct", original)
        self.assertEqual(self.shop.await_args.kwargs["item_data"], original)
        self.assertEqual(self.item, original)
        log, = await self.logs()
        self.assertEqual((log.id, log.user_id, log.account_id, log.material_id, log.batch_id, log.status), (result["log_id"], 7, "acct", 11, None, "success"))
        self.assertEqual((log.resolved_address_id, log.resolved_address_text, log.address_source), (None, "手工测试地址", "material"))
        self.bind.assert_awaited_once_with(owner_id=7, publish_log_id=log.id)

    async def test_sync_failure_or_exception_does_not_change_publish_success(self):
        for failure in ({"success": False, "message": "模拟同步失败"}, RuntimeError("模拟同步异常")):
            with self.subTest(failure=failure):
                self.sync.reset_mock()
                self.settle.reset_mock()
                self.shop.reset_mock()
                self.sync.side_effect = failure if isinstance(failure, Exception) else None
                self.sync.return_value = failure if isinstance(failure, dict) else None
                result = await self.execute()
                self.assertTrue(result["success"])
                self.assertFalse(result.get("unknown", False))
                self.assertEqual((result["item_id"], result["sync_status"], result["sync_total_count"], result["sync_saved_count"]), ("offline-item", "failed", 0, 0))
                self.assertIn("模拟同步", result["sync_message"])
                log = (await self.logs())[-1]
                self.assertEqual((log.id, log.status, log.item_id, log.error_message), (result["log_id"], "success", "offline-item", None))
                self.sync.assert_awaited_once()
                self.shop.assert_awaited_once()
                self.settle.assert_awaited_once_with(log.id, "success", item_id="offline-item", error_message=None)

    async def test_exhausted_capacity_skips_before_any_platform_request(self):
        log = await self.prepare_log()
        self.reserve.return_value = "exhausted"
        result = await self.execute(batch_id="batch-1", prepared_log_id=log.id)
        self.assertFalse(result["success"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["log_id"], log.id)
        self.reserve.assert_awaited_once_with(7, "acct", log.id)
        self.settle.assert_awaited_once_with(log.id, "failed", error_message="账号剩余可发布数量不足")
        current, = await self.logs()
        self.assertEqual((current.id, current.status, current.item_id, current.error_message), (log.id, "skipped", None, "账号剩余可发布数量不足"))
        self.reliable.assert_not_called()
        for dependency in (self.detect, self.before, self.shop, self.personal, self.sync, self.bind):
            dependency.assert_not_awaited()
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()
