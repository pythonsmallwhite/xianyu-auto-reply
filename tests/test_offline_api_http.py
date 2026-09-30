"""HTTP-level contract for the durable offline endpoints.

These tests drive the real FastAPI router through a TestClient with an in-memory
database, so they cover what the service tests cannot: request validation at the
HTTP boundary, dependency wiring, ownership enforcement, and the promise that a
cancelled confirmation and a window-less request never reach the platform.
"""
import asyncio
import socket
import sys
import threading
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]


def _load_internal_products_router(test_class):
    """Keep isolated modules alive for the class, then restore the whole registry."""
    test_class.enterClassContext(patch.dict(sys.modules))
    for name in list(sys.modules):
        if name in {"app", "common"} or name.startswith(("app.", "common.")):
            del sys.modules[name]
    for name in (
        "app", "app.api", "app.api.routes", "common", "common.db",
        "common.models", "common.services", "common.utils", "common.schemas",
    ):
        package = types.ModuleType(name)
        folder = "backend-web" if name.startswith("app") else ""
        package.__path__ = [str(ROOT / folder / name.replace(".", "/"))]
        sys.modules[name] = package

    def blocked_session(*args, **kwargs):
        raise AssertionError("HTTP contract test must not use the real database")

    session_module = types.ModuleType("common.db.session")
    session_module.async_session_maker = blocked_session
    sys.modules[session_module.__name__] = session_module
    deps_module = types.ModuleType("app.api.deps")

    async def get_db_session():
        raise AssertionError("HTTP contract test must override get_db_session")
        yield  # pragma: no cover

    async def get_current_active_user():
        raise AssertionError("HTTP contract test must override get_current_active_user")

    deps_module.get_db_session = get_db_session
    deps_module.get_current_active_user = get_current_active_user
    sys.modules[deps_module.__name__] = deps_module
    from app.api.routes import internal_products
    from common.services import listing_action_service
    return internal_products, deps_module, listing_action_service


PREFIX = "/api/v1/internal-products"
BATCH_ID = "11111111-1111-4111-8111-111111111111"
RETRY_ID = "22222222-2222-4222-8222-222222222222"


class OfflineHttpContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router_module, cls.deps, cls.actions = _load_internal_products_router(cls)
        from common.db.base_class import Base
        cls.Base = Base
        from common.models.card import Card
        from common.models.card_item_relation import CardItemRelation
        from common.models.xy_catalog_item import XYCatalogItem
        from common.models.xy_keyword_rule import XYKeywordRule
        from common.models.internal_product import InternalProduct, InternalProductListing
        from common.models.listing_action import (
            ListingActionBatch,
            ListingActionTarget,
            ListingActionAttempt,
        )
        from common.models.publish_batch import PublishBatch, PublishBatchTarget, PublishBatchAttempt
        from common.models.publish_batch_schedule import PublishProductSchedule
        from common.models.xy_account import XYAccount

        cls.Product = InternalProduct
        cls.Listing = InternalProductListing
        cls.XYAccount = XYAccount
        cls.Batch, cls.Target = ListingActionBatch, ListingActionTarget
        cls.models = [
            InternalProduct,
            InternalProductListing,
            ListingActionBatch,
            ListingActionTarget,
            ListingActionAttempt,
            PublishBatch,
            PublishBatchTarget,
            PublishBatchAttempt,
            PublishProductSchedule,
            XYAccount,
        ]

    def setUp(self):
        # Windows asyncio builds its wake-up pipe through socketpair's loopback fallback.
        internal_pipe = threading.local()
        real_pair, real_connect = socket.socketpair, socket.socket.connect

        def socketpair(*args, **kwargs):
            internal_pipe.active = True
            try:
                return real_pair(*args, **kwargs)
            finally:
                internal_pipe.active = False

        def connect(sock, address):
            if getattr(internal_pipe, "active", False):
                return real_connect(sock, address)
            raise AssertionError("HTTP contract test forbids network access")

        self.enterContext(patch("socket.socketpair", side_effect=socketpair))
        self.enterContext(patch("socket.socket.connect", new=connect))
        for name in ("socket.socket.connect_ex", "socket.getaddrinfo"):
            self.enterContext(patch(name, side_effect=AssertionError("HTTP contract test forbids network access")))
        self.platform = self.enterContext(patch.object(
            self.actions, "offline_listing", AsyncMock(side_effect=AssertionError("Explicit platform mock required"))))
        self.enterContext(patch.object(self.actions, "plan_product_offsets",
            side_effect=lambda n, w: tuple(i * w * 3600 / (2 * n) for i in range(n))))
        self.engine = create_async_engine("sqlite+aiosqlite://")
        self.addCleanup(lambda: asyncio.run(self.engine.dispose()))
        self.enterContext(patch.object(
            self.engine.sync_engine.dialect.type_compiler_instance,
            "visit_BIGINT",
            return_value="INTEGER",
        ))
        self.maker = async_sessionmaker(self.engine, expire_on_commit=False)
        self.now = datetime(2026, 9, 30, 12, 0)

        async def prepare():
            async with self.engine.begin() as conn:
                await conn.run_sync(
                    lambda sync: self.Base.metadata.create_all(
                        sync, tables=[m.__table__ for m in self.models]
                    )
                )
            async with self.maker() as session:
                session.add(self.XYAccount(id=1, owner_id=7, account_id="acct", cookie="c", login_method="cookie"))
                session.add(self.Product(id=10, owner_id=7, title="http fixture"))
                session.add(self.Listing(
                    id=20, owner_id=7, internal_product_id=10, account_id="acct",
                    item_id="item", publish_log_id=100, state="active"))
                await session.commit()

        self.enterContext(patch.object(self.actions, "async_session_maker", self.maker))
        self.enterContext(patch.object(
            self.actions, "database_now", AsyncMock(side_effect=lambda session: self.now)))
        asyncio.run(prepare())

        async def override_session():
            async with self.maker() as session:
                yield session

        app = FastAPI()
        app.include_router(self.router_module.router, prefix="/api/v1")
        app.dependency_overrides[self.deps.get_db_session] = override_session
        app.dependency_overrides[self.deps.get_current_active_user] = lambda: SimpleNamespace(id=7)
        self.client = self.enterContext(TestClient(app))

    def create_batch(self, body=None, request_id=BATCH_ID):
        payload = {"listing_ids": [20], "window_hours": 1, "request_id": request_id, "confirmed": True}
        return self.client.post(f"{PREFIX}/10/offline-batches", json=payload if body is None else body)

    def retry_batch(self, target, window=3):
        return self.client.post(f"{PREFIX}/offline-batches/{BATCH_ID}/retry", json={
            "target_ids": [target], "window_hours": window, "request_id": RETRY_ID, "confirmed": True,
        })

    def reconcile_target(self, target, state="offline", batch_id=BATCH_ID):
        return self.client.post(f"{PREFIX}/offline-batches/{batch_id}/targets/{target}/reconcile", json={
            "platform_state": state, "note": "Offline fixture verification", "confirmed": True,
        })

    def test_create_requires_confirmed_and_an_explicit_window(self):
        # 取消确认（confirmed 缺失或 false）等同于「未确认」，必须零效果。
        for body in [
            {"listing_ids": [20], "window_hours": 1, "request_id": "11111111-1111-4111-8111-111111111111"},
            {"listing_ids": [20], "window_hours": 1, "request_id": "11111111-1111-4111-8111-111111111111", "confirmed": False},
            {"listing_ids": [20], "request_id": "11111111-1111-4111-8111-111111111111", "confirmed": True},
            {"listing_ids": [20], "window_hours": 2, "request_id": "11111111-1111-4111-8111-111111111111", "confirmed": True},
            {"listing_ids": [], "window_hours": 1, "request_id": "11111111-1111-4111-8111-111111111111", "confirmed": True},
        ]:
            response = self.client.post(f"{PREFIX}/10/offline-batches", json=body)
            self.assertEqual(response.status_code, 422, response.text)
        created = asyncio.run(self.count_batches())
        self.assertEqual(created, 0, "被拒绝的确认不得留下任务")

    async def count_batches(self):
        from sqlalchemy import func, select
        from common.models.listing_action import ListingActionBatch
        async with self.maker() as session:
            return await session.scalar(select(func.count()).select_from(ListingActionBatch))

    def test_confirmed_request_creates_a_batch_and_reports_it(self):
        response = self.create_batch()
        self.assertEqual(response.status_code, 200, response.text)
        batch_id = response.json()["data"]["batch_id"]
        self.assertEqual(batch_id, "11111111-1111-4111-8111-111111111111")
        detail = self.client.get(f"{PREFIX}/offline-batches/{batch_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(len(detail.json()["data"]["targets"]), 1)

    def test_same_request_id_retry_is_idempotent_over_http(self):
        first = self.create_batch()
        second = self.create_batch()
        self.assertEqual(first.json()["data"]["batch_id"], second.json()["data"]["batch_id"])
        self.assertEqual(asyncio.run(self.count_batches()), 1)

    def test_reconcile_endpoint_requires_note_and_explicit_state(self):
        self.create_batch()
        self.run_unknown()
        target = asyncio.run(self.target_id())
        for body in [
            {"platform_state": "maybe", "note": "n", "confirmed": True},
            {"platform_state": "failed", "note": "n", "confirmed": True},
            {"platform_state": "offline", "note": "", "confirmed": True},
            {"platform_state": "offline", "note": "   ", "confirmed": True},
            {"platform_state": "offline", "note": "n"},
            {"platform_state": "offline", "note": "n", "confirmed": False},
        ]:
            response = self.client.post(
                f"{PREFIX}/offline-batches/x/targets/{target}/reconcile", json=body)
            self.assertEqual(response.status_code, 422, response.text)

    def run_unknown(self):
        self.run_status("unknown")

    def run_status(self, status):
        async def call(account, cookie, item, owner, guard):
            self.assertEqual((account, item, owner), ("acct", "item", 7))
            async with guard():
                return {"status": status, "message": "HTTP offline fixture"}

        self.platform.side_effect = call
        self.assertTrue(asyncio.run(self.actions.run_one()), "Worker must claim the due target")
        self.platform.assert_awaited_once()
        target = asyncio.run(self.target_row())
        self.assertEqual(target.status, status)
        self.assertIsNotNone(target.request_started_at, "The final request guard must have run")
        self.assertFalse(asyncio.run(self.actions.run_one()), "Terminal targets must not replay")
        self.platform.assert_awaited_once()

    async def target_row(self):
        from sqlalchemy import select
        async with self.maker() as session:
            return await session.scalar(select(self.Target).order_by(self.Target.id).limit(1))

    async def target_id(self):
        from sqlalchemy import select
        from common.models.listing_action import ListingActionTarget
        async with self.maker() as session:
            return await session.scalar(select(ListingActionTarget.id))

    def test_reconcile_over_http_saves_the_conclusion(self):
        self.create_batch()
        self.run_unknown()
        target = asyncio.run(self.target_id())
        response = self.client.post(
            f"{PREFIX}/offline-batches/11111111-1111-4111-8111-111111111111/targets/{target}/reconcile",
            json={"platform_state": "offline", "note": "已在下架列表确认", "confirmed": True},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()["data"]
        self.assertEqual(body["status"], "reconciled")
        self.assertFalse(body["conflict"])
        self.assertEqual(asyncio.run(self.listing_state()), ("offline", 1))

    def test_reconcile_conflict_is_reported_not_hidden(self):
        self.create_batch()
        self.run_unknown()

        async def bump():
            from sqlalchemy import select
            from common.models.internal_product import InternalProductListing
            async with self.maker() as session:
                row = await session.scalar(select(InternalProductListing).where(InternalProductListing.id == 20))
                row.state_version += 1
                await session.commit()

        asyncio.run(bump())
        target = asyncio.run(self.target_id())
        response = self.client.post(
            f"{PREFIX}/offline-batches/11111111-1111-4111-8111-111111111111/targets/{target}/reconcile",
            json={"platform_state": "offline", "note": "已确认", "confirmed": True},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()["data"]
        self.assertTrue(body["conflict"])
        self.assertIn("本地状态已变更", body["message"])
        self.assertEqual(asyncio.run(self.listing_state())[1], 1, "不得覆盖人工修改")
        repeated = self.reconcile_target(target)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertTrue(repeated.json()["data"]["conflict"], "Repeated reconciliation must preserve the conflict")
        self.assertEqual(repeated.json()["data"]["message"], body["message"])

    async def listing_state(self):
        from sqlalchemy import select
        from common.models.internal_product import InternalProductListing
        async with self.maker() as session:
            row = await session.scalar(select(InternalProductListing).where(InternalProductListing.id == 20))
            return row.state, row.state_version

    def test_unknown_target_is_not_retryable_over_http(self):
        self.create_batch()
        self.run_unknown()
        target = asyncio.run(self.target_id())
        response = self.client.post(
            f"{PREFIX}/offline-batches/11111111-1111-4111-8111-111111111111/retry",
            json={"target_ids": [target], "window_hours": 1,
                  "request_id": "22222222-2222-4222-8222-222222222222", "confirmed": True},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("未知", response.json()["detail"])

    def test_batch_detail_is_scoped_to_the_owner(self):
        self.create_batch()
        self.client.app.dependency_overrides[self.deps.get_current_active_user] = lambda: SimpleNamespace(id=8)
        response = self.client.get(
            f"{PREFIX}/offline-batches/11111111-1111-4111-8111-111111111111")
        self.assertEqual(response.status_code, 404, response.text)

    def test_cancelled_confirmation_leaves_no_task_and_never_calls_platform(self):
        """取消确认 = 零请求：既没有任务，也没有任何平台调用。"""
        call = AsyncMock()
        with patch.object(self.actions, "offline_listing", call):
            response = self.create_batch({"listing_ids": [20], "window_hours": 1,
                "request_id": "33333333-3333-4333-8333-333333333333", "confirmed": False})
            self.assertEqual(response.status_code, 422, response.text)
            asyncio.run(self.actions.run_one())
            call.assert_not_awaited()
        self.assertEqual(asyncio.run(self.count_batches()), 0)

    def test_missing_window_blocks_at_the_service_not_just_the_client(self):
        """客户端不选窗口时服务端同样拒绝，避免绕过 UI 直接提交。"""
        for window in ("", None, 0, 25, -1, "1"):
            response = self.create_batch({"listing_ids": [20], "window_hours": window,
                "request_id": "44444444-4444-4444-8444-444444444444", "confirmed": True})
            self.assertEqual(response.status_code, 422, f"window={window!r}: {response.text}")

    def test_network_and_real_database_are_blocked_but_asyncio_pipe_works(self):
        with self.assertRaises(AssertionError):
            sys.modules["common.db.session"].async_session_maker()
        with socket.socket() as sock:
            with self.assertRaises(AssertionError):
                sock.connect(("127.0.0.1", 3306))
            with self.assertRaises(AssertionError):
                sock.connect_ex(("127.0.0.1", 3306))
        with self.assertRaises(AssertionError):
            socket.getaddrinfo("example.invalid", 443)
        left, right = socket.socketpair()
        left.close()
        right.close()
        self.assertEqual(asyncio.run(self.count_batches()), 0)

    def test_same_request_id_cannot_change_the_payload(self):
        self.assertEqual(self.create_batch().status_code, 200)
        response = self.create_batch({"listing_ids": [20], "window_hours": 3,
            "request_id": BATCH_ID, "confirmed": True})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(asyncio.run(self.count_batches()), 1)
        self.platform.assert_not_awaited()

    def test_success_cannot_retry_or_be_reconciled(self):
        self.assertEqual(self.create_batch().status_code, 200)
        self.run_status("success")
        target = asyncio.run(self.target_id())
        self.assertEqual(self.retry_batch(target).status_code, 400)
        self.assertEqual(self.reconcile_target(target).status_code, 400)
        self.assertEqual(asyncio.run(self.listing_state()), ("offline", 1))
        self.assertEqual(asyncio.run(self.count_batches()), 1)
        self.platform.assert_awaited_once()

    def test_failed_retry_uses_a_new_window_and_preserves_original(self):
        self.assertEqual(self.create_batch().status_code, 200)
        self.run_status("failed")
        target = asyncio.run(self.target_id())
        response = self.retry_batch(target)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["batch_id"], RETRY_ID)
        repeated = self.retry_batch(target)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(asyncio.run(self.count_batches()), 2)
        detail = self.client.get(f"{PREFIX}/offline-batches/{RETRY_ID}").json()["data"]
        self.assertEqual(detail["window_hours"], 3)
        self.assertEqual(datetime.fromisoformat(detail["deadline_at"]), self.now + timedelta(hours=3))
        original = self.client.get(f"{PREFIX}/offline-batches/{BATCH_ID}").json()["data"]
        self.assertEqual(original["targets"][0]["status"], "failed")
        self.assertEqual(original["targets"][0]["retry_batch_id"], RETRY_ID)
        self.assertEqual(self.retry_batch(target, 5).status_code, 400)
        self.platform.assert_awaited_once()

    def test_retry_also_requires_confirmation_and_explicit_window(self):
        self.assertEqual(self.create_batch().status_code, 200)
        self.run_status("failed")
        target = asyncio.run(self.target_id())
        valid = {"target_ids": [target], "window_hours": 3, "request_id": RETRY_ID, "confirmed": True}
        for missing in ("confirmed", "window_hours"):
            response = self.client.post(f"{PREFIX}/offline-batches/{BATCH_ID}/retry",
                json={key: value for key, value in valid.items() if key != missing})
            self.assertEqual(response.status_code, 422, response.text)
        response = self.client.post(f"{PREFIX}/offline-batches/{BATCH_ID}/retry",
            json={**valid, "confirmed": False})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(asyncio.run(self.count_batches()), 1)
        self.platform.assert_awaited_once()

    def test_create_rejects_other_owner_or_an_unlinked_listing(self):
        self.client.app.dependency_overrides[self.deps.get_current_active_user] = lambda: SimpleNamespace(id=8)
        self.assertEqual(self.create_batch().status_code, 400)
        self.client.app.dependency_overrides[self.deps.get_current_active_user] = lambda: SimpleNamespace(id=7)
        response = self.create_batch({"listing_ids": [999], "window_hours": 1,
            "request_id": BATCH_ID, "confirmed": True})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(asyncio.run(self.count_batches()), 0)
        self.platform.assert_not_awaited()

    def test_reconcile_is_scoped_to_owner_batch_and_account(self):
        self.assertEqual(self.create_batch().status_code, 200)
        self.run_unknown()
        target = asyncio.run(self.target_id())
        self.client.app.dependency_overrides[self.deps.get_current_active_user] = lambda: SimpleNamespace(id=8)
        self.assertEqual(self.reconcile_target(target).status_code, 400)
        self.client.app.dependency_overrides[self.deps.get_current_active_user] = lambda: SimpleNamespace(id=7)
        self.assertEqual(self.reconcile_target(target, batch_id=RETRY_ID).status_code, 400)

        async def reassign():
            async with self.maker() as session:
                account = await session.get(self.XYAccount, 1)
                account.owner_id = 8
                await session.commit()

        asyncio.run(reassign())
        self.assertEqual(self.reconcile_target(target).status_code, 400)
        self.assertEqual(asyncio.run(self.target_row()).status, "unknown")
        self.assertEqual(asyncio.run(self.listing_state()), ("active", 0))
        self.platform.assert_awaited_once()

    def test_reconcile_active_records_conclusion_without_resending(self):
        self.assertEqual(self.create_batch().status_code, 200)
        self.run_unknown()
        target = asyncio.run(self.target_id())
        self.assertEqual(self.create_batch(request_id=RETRY_ID).status_code, 400)
        response = self.reconcile_target(target, "active")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["status"], "reconciled")
        self.assertEqual(self.reconcile_target(target, "active").status_code, 200)
        self.assertEqual(self.reconcile_target(target, "offline").status_code, 400)
        self.assertEqual(asyncio.run(self.listing_state()), ("active", 0))
        self.assertFalse(asyncio.run(self.actions.run_one()))
        self.platform.assert_awaited_once()
        self.assertEqual(self.create_batch(request_id=RETRY_ID).status_code, 200)


if __name__ == "__main__":
    unittest.main()
