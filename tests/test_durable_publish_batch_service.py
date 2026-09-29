"""使用 SQLite 和预注入替身验证持久发布，不访问数据库服务或平台。"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]


class DurablePublishBatchTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # 整个测试类保留隔离环境，覆盖 run_batch 内部的延迟导入。
        modules = patch.dict(sys.modules)
        modules.start()
        cls.addClassCleanup(modules.stop)
        for name in list(sys.modules):
            if name in {"common", "app"} or name.startswith(("common.", "app.")):
                del sys.modules[name]
        for name in ("common", "common.db", "common.services", "common.utils", "app", "app.core"):
            package = types.ModuleType(name)
            package.__path__ = [str(ROOT / name.replace(".", "/"))]
            sys.modules[name] = package

        def blocked_session(*args, **kwargs):
            raise AssertionError("离线测试禁止使用真实数据库会话")

        session_stub = types.ModuleType("common.db.session")
        session_stub.async_session_maker = blocked_session
        capacity_stub = types.ModuleType("common.services.publish_capacity_service")
        capacity_stub.settle_publish_capacity = AsyncMock()
        execution_stub = types.ModuleType("common.services.publish_execution_service")
        execution_stub.execute_single_publish = AsyncMock(side_effect=AssertionError("必须显式模拟发布"))
        paths_stub = types.ModuleType("app.core.paths")
        paths_stub.STATIC_ROOT = ROOT / "tests" / "offline-static"
        for stub in (session_stub, capacity_stub, execution_stub, paths_stub):
            sys.modules[stub.__name__] = stub
        cls.paths_stub = paths_stub

        from common.db.base_class import Base
        from common.models.publish_batch import PublishBatch, PublishBatchAccount, PublishBatchAttempt, PublishBatchTarget
        from common.models.publish_log import PublishLog
        from common.models.xy_account import XYAccount
        from common.models.product_material import ProductMaterial
        from common.models.internal_product import InternalProduct
        from common.models.publish_batch_schedule import PublishProductSchedule

        spec = importlib.util.spec_from_file_location(
            "_durable_publish_batch_service_under_test",
            ROOT / "backend-web/app/services/durable_publish_batch_service.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.module, cls.Service, cls.Base = module, module.DurablePublishBatchService, Base
        cls.Batch, cls.Account, cls.Attempt, cls.Target, cls.Log, cls.XYAccount = (
            PublishBatch, PublishBatchAccount, PublishBatchAttempt, PublishBatchTarget, PublishLog, XYAccount,
        )
        cls.Material, cls.Product, cls.Schedule = ProductMaterial, InternalProduct, PublishProductSchedule
        cls.models = (cls.Batch, cls.Account, cls.Attempt, cls.Target, cls.Log, cls.XYAccount,
                      cls.Material, cls.Product, cls.Schedule)

    async def asyncSetUp(self):
        for name in ("socket.socket.connect", "socket.socket.connect_ex", "socket.getaddrinfo"):
            self.enterContext(patch(name, side_effect=AssertionError("离线测试禁止网络访问")))
        self.now = self.module.get_beijing_now_naive().replace(microsecond=0)
        self.enterContext(patch.object(self.Service, "_database_now", new=AsyncMock(side_effect=lambda session: self.now)))
        self.offsets = self.enterContext(patch.object(self.module, "plan_product_offsets", side_effect=lambda n, t: tuple(i * t * 3600 / (2 * n) for i in range(n))))
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.addAsyncCleanup(self.engine.dispose)
        # 仅修改当前 SQLite 引擎的编译器，避免全局 BigInteger 编译注册污染。
        self.enterContext(patch.object(self.engine.sync_engine.dialect.type_compiler_instance, "visit_BIGINT", return_value="INTEGER"))
        self.maker = async_sessionmaker(self.engine, expire_on_commit=False)
        self.enterContext(patch.object(self.module, "async_session_maker", self.maker))
        self.execute = self.enterContext(patch.object(self.module, "execute_single_publish", new_callable=AsyncMock))
        self.execute.side_effect = AssertionError("必须显式模拟发布")
        self.settle = self.enterContext(patch.object(self.module, "settle_publish_capacity", new_callable=AsyncMock))
        self.enterContext(patch.object(self.module, "logger"))
        async with self.engine.begin() as conn:
            await conn.run_sync(lambda sync: self.Base.metadata.create_all(sync, tables=[m.__table__ for m in self.models]))
        async with self.maker() as session:
            session.add_all([
                self.XYAccount(id=1, owner_id=7, account_id="acct", cookie="offline", login_method="cookie"),
                self.XYAccount(id=2, owner_id=8, account_id="other", cookie="offline", login_method="cookie"),
            ])
            await session.commit()

    async def create(self, batch_id="batch-1", owner_id=7, account_ids=None, material_ids=(11,), window_hours=1):
        async with self.maker() as session:
            # 不绕过生产素材归属校验；不同 owner 使用独立素材主键。
            mids = [mid if owner_id == 7 else mid + 10000 for mid in material_ids]
            for mid in set(mids):
                if await session.get(self.Material, mid) is None:
                    session.add(self.Material(id=mid, user_id=owner_id, title=f"素材{mid}", description="离线素材", price=1))
            await session.commit()
            return await self.Service(session).create_batch(
                owner_id=owner_id, account_ids=account_ids or ["acct", "acct"], batch_id=batch_id,
                materials=[{"id": mid, "title": f"素材{mid}", "description": "离线素材", "price": 1} for mid in mids],
                window_hours=window_hours,
            )

    async def start_request(self, kwargs):
        async with kwargs["request_guard"]():
            pass

    async def rows(self, model):
        async with self.maker() as session:
            return list((await session.scalars(select(model).order_by(model.id))).all())

    async def expire(self, target_id):
        async with self.maker() as session:
            target = await session.get(self.Target, target_id)
            target.lease_expires_at = self.now - timedelta(seconds=1)
            await session.commit()

    async def run_result(self, result, batch_id="batch-1"):
        pending = [t for t in await self.rows(self.Target) if t.batch_id == batch_id and t.status == "pending"]
        if pending:
            target = pending[0]
            schedule = next(s for s in await self.rows(self.Schedule) if s.internal_product_id == target.internal_product_id)
            self.now = max(self.now, target.available_at)
            if schedule.last_request_started_at:
                self.now = max(self.now, schedule.last_request_started_at + timedelta(seconds=target.minimum_gap_seconds))
        async def execute(**kwargs):
            await self.start_request(kwargs)
            return result
        self.execute.side_effect = execute
        await self.Service.run_batch(batch_id)

    async def test_submission_persists_exact_targets_and_status(self):
        batch = await self.create(material_ids=(11, 11))
        async with self.maker() as session:
            data = await self.Service.get_status(session, 7, batch.id)
        self.assertEqual((batch.total_count, len(await self.rows(self.Target)), data["pending"], data["finished"]), (1, 1, 1, False))
        self.assertEqual(await self.Service.find_next_batch(), batch.id)
        self.execute.assert_not_awaited()

    async def test_run_batch_calls_real_flow_with_prepared_log_and_request_boundary(self):
        await self.create()

        async def execute(**kwargs):
            self.assertEqual((kwargs["user_id"], kwargs["account_id"], kwargs["batch_id"]), (7, "acct", "batch-1"))
            self.assertEqual(kwargs["static_root"], self.paths_stub.STATIC_ROOT)
            self.assertEqual(kwargs["session"].bind, self.engine)
            self.assertEqual(kwargs["item_data"]["id"], 11)
            log, = await self.rows(self.Log)
            attempt, = await self.rows(self.Attempt)
            self.assertEqual((log.id, log.status, attempt.publish_log_id, attempt.attempt_no), (kwargs["prepared_log_id"], "pending", log.id, 1))
            await self.start_request(kwargs)
            log, = await self.rows(self.Log)
            self.assertEqual(log.status, "publishing")
            return {"success": True, "item_id": "item-11", "sync_status": "success", "sync_total_count": 2, "sync_saved_count": 2}

        self.execute.side_effect = execute
        await self.Service.run_batch("batch-1")
        target, = await self.rows(self.Target)
        attempt, = await self.rows(self.Attempt)
        account, = await self.rows(self.Account)
        batch, = await self.rows(self.Batch)
        self.assertEqual((target.status, target.attempt_count, target.lease_token, target.lease_expires_at), ("success", 1, None, None))
        self.assertEqual((attempt.status, attempt.item_id, batch.status), ("success", "item-11", "success"))
        self.assertEqual((account.sync_status, account.sync_total_count, account.sync_saved_count), ("success", 2, 2))
        self.execute.assert_awaited_once()
        self.settle.assert_awaited_once_with(target.publish_log_id, "success", item_id="item-11", error_message=None)
        await self.Service.run_batch("batch-1")
        self.execute.assert_awaited_once()

    async def test_late_success_is_reported_without_becoming_retryable(self):
        await self.create()

        async def execute(**kwargs):
            await self.start_request(kwargs)
            self.now += timedelta(hours=2)
            return {"success": True, "item_id": "late-item"}

        self.execute.side_effect = execute
        await self.Service.run_batch("batch-1")
        target, = await self.rows(self.Target)
        attempt, = await self.rows(self.Attempt)
        self.assertEqual(target.status, "success")
        self.assertIn("超过排程窗口", target.schedule_error)
        self.assertEqual(attempt.schedule_error, target.schedule_error)
        self.assertEqual(target.finished_at, self.now)
        async with self.maker() as session:
            status = await self.Service.get_status(session, 7, "batch-1")
            self.assertEqual(status["timed_out"], 1)
            with self.assertRaises(ValueError):
                await self.Service(session).retry_failed(7, "batch-1", [target.id], window_hours=1)
        await self.Service.run_batch("batch-1")
        self.execute.assert_awaited_once()

    async def test_success_result_backfills_log_item_id(self):
        await self.create()
        await self.run_result({"success": True, "item_id": "returned-item"})
        log, = await self.rows(self.Log)
        self.assertEqual((log.status, log.item_id), ("success", "returned-item"))

    async def test_request_started_then_exception_becomes_unknown_without_replay(self):
        await self.create()

        async def execute(**kwargs):
            await self.start_request(kwargs)
            raise RuntimeError("模拟请求提交后断线")

        self.execute.side_effect = execute
        await self.Service.run_batch("batch-1")
        target, = await self.rows(self.Target)
        log, = await self.rows(self.Log)
        attempt, = await self.rows(self.Attempt)
        batch, = await self.rows(self.Batch)
        self.assertEqual((target.status, log.status, attempt.status, batch.status), ("unknown",) * 4)
        await self.Service.run_batch("batch-1")
        self.assertEqual(await self.Service.recover_interrupted_targets(), 0)
        self.assertIsNone(await self.Service.find_next_batch())
        self.execute.assert_awaited_once()
        self.settle.assert_awaited_once()
        self.assertEqual(self.settle.await_args.args, (log.id, "unknown"))

    async def test_success_log_wins_over_late_sync_exception(self):
        await self.create()

        async def execute(**kwargs):
            await self.start_request(kwargs)
            async with self.maker() as session:
                log = await session.get(self.Log, kwargs["prepared_log_id"])
                log.status, log.item_id = "success", "confirmed-item"
                await session.commit()
            raise RuntimeError("模拟成功后同步异常")

        self.execute.side_effect = execute
        await self.Service.run_batch("batch-1")
        target, = await self.rows(self.Target)
        log, = await self.rows(self.Log)
        attempt, = await self.rows(self.Attempt)
        account, = await self.rows(self.Account)
        self.assertEqual((target.status, log.status, attempt.status), ("success",) * 3)
        self.assertEqual((log.item_id, attempt.item_id, target.error_message), ("confirmed-item", "confirmed-item", None))
        self.assertEqual(account.sync_status, "unknown")
        self.settle.assert_awaited_once_with(log.id, "success", item_id="confirmed-item", error_message=None)

    async def test_retry_preserves_old_log_and_attempt_before_new_attempt(self):
        await self.create()
        await self.run_result({"success": False, "message": "明确失败"})
        old_log, = await self.rows(self.Log)
        old_attempt, = await self.rows(self.Attempt)
        target, = await self.rows(self.Target)
        async with self.maker() as session:
            self.assertEqual(await self.Service(session).retry_failed(7, "batch-1", [target.id, target.id], window_hours=1), 1)
        pending, = await self.rows(self.Target)
        self.assertEqual((pending.status, pending.attempt_count, pending.publish_log_id), ("pending", 1, None))
        log, = await self.rows(self.Log)
        attempt, = await self.rows(self.Attempt)
        self.assertEqual((log.id, log.status, log.error_message), (old_log.id, "failed", "明确失败"))
        self.assertEqual((attempt.id, attempt.status, attempt.finished_at), (old_attempt.id, "failed", old_attempt.finished_at))
        await self.run_result({"success": True, "item_id": "retry-item"})
        target, = await self.rows(self.Target)
        logs = await self.rows(self.Log)
        attempts = await self.rows(self.Attempt)
        self.assertEqual((target.status, target.attempt_count, len(logs), len(attempts)), ("success", 2, 2, 2))
        self.assertNotEqual(logs[0].publish_request_id, logs[1].publish_request_id)
        self.assertEqual(target.publish_log_id, logs[1].id)
        self.assertEqual([(a.attempt_no, a.status, a.publish_log_id) for a in attempts], [(1, "failed", old_log.id), (2, "success", logs[1].id)])
        self.assertEqual((logs[0].status, attempts[0].error_message), ("failed", "明确失败"))

    async def test_success_unknown_and_skipped_reject_retry(self):
        for status, result in (
            ("success", {"success": True, "item_id": "item"}),
            ("unknown", {"unknown": True}),
            ("skipped", {"skipped": True}),
        ):
            with self.subTest(status=status):
                await self.create(batch_id=status)
                await self.run_result(result, status)
                target = next(t for t in await self.rows(self.Target) if t.batch_id == status)
                async with self.maker() as session:
                    with self.assertRaisesRegex(ValueError, "只能重试"):
                        await self.Service(session).retry_failed(7, status, [target.id], window_hours=1)
                current = next(t for t in await self.rows(self.Target) if t.id == target.id)
                self.assertEqual((current.status, current.publish_log_id, current.attempt_count), (status, target.publish_log_id, 1))

    async def test_create_rejects_foreign_and_missing_accounts_atomically(self):
        for account_ids in (["other"], ["missing"], ["acct", "other"]):
            with self.subTest(account_ids=account_ids):
                with self.assertRaisesRegex(ValueError, "无权"):
                    await self.create(account_ids=account_ids)
                self.assertEqual(await self.rows(self.Batch), [])
                self.assertEqual(await self.rows(self.Target), [])

    async def test_cross_user_reads_and_retry_are_denied(self):
        await self.create()
        await self.create("foreign", owner_id=8, account_ids=["other"])
        await self.run_result({"success": False})
        target = (await self.rows(self.Target))[0]
        async with self.maker() as session:
            service = self.Service(session)
            self.assertIsNone(await service.get_status(session, 8, "batch-1"))
            self.assertIsNone(await service.list_targets(8, "batch-1", 1, 20))
            listing = await service.list_batches(8, 1, 20)
            self.assertEqual((listing["total"], [b["batch_id"] for b in listing["list"]]), (1, ["foreign"]))
            with self.assertRaisesRegex(ValueError, "无权"):
                await service.retry_failed(8, "batch-1", [target.id], window_hours=1)
        self.assertEqual((await self.rows(self.Target))[0].status, "failed")

    async def test_cross_batch_and_mixed_target_retry_are_atomic(self):
        for batch_id in ("batch-1", "batch-2"):
            await self.create(batch_id)
            await self.run_result({"success": False}, batch_id)
        first, second = await self.rows(self.Target)
        for ids in ([second.id], [first.id, second.id], [first.id, 999999], []):
            with self.subTest(ids=ids):
                async with self.maker() as session:
                    with self.assertRaises(ValueError):
                        await self.Service(session).retry_failed(7, "batch-1", ids, window_hours=1)
                self.assertEqual([t.status for t in await self.rows(self.Target)], ["failed", "failed"])

    async def test_valid_lease_is_not_recovered(self):
        await self.create()
        claimed = await self.Service._claim_next_target("batch-1")
        await self.Service._renew(claimed, start_request=True)
        before, = await self.rows(self.Target)
        self.assertEqual(await self.Service.recover_interrupted_targets(), 0)
        after, = await self.rows(self.Target)
        self.assertEqual((after.status, after.lease_token, after.lease_expires_at), ("publishing", before.lease_token, before.lease_expires_at))
        self.assertEqual((await self.rows(self.Log))[0].status, "publishing")
        self.settle.assert_not_awaited()

    async def test_expired_lease_blocks_request_in_real_run_batch(self):
        await self.create()
        requests = AsyncMock()
        errors = []

        async def execute(**kwargs):
            target, = await self.rows(self.Target)
            await self.expire(target.id)
            try:
                await self.start_request(kwargs)
            except RuntimeError as exc:
                errors.append(str(exc))
                raise
            await requests()

        self.execute.side_effect = execute
        await self.Service.run_batch("batch-1")
        self.assertEqual(len(errors), 1)
        self.assertIn("执行权已失效", errors[0])
        requests.assert_not_awaited()
        self.execute.assert_awaited_once()
        self.assertEqual((await self.rows(self.Log))[0].status, "failed")

    async def test_wrong_token_and_duplicate_request_are_rejected(self):
        await self.create()
        claimed = await self.Service._claim_next_target("batch-1")
        with self.assertRaisesRegex(RuntimeError, "执行权已失效"):
            await self.Service._renew({**claimed, "token": "stale"}, start_request=True)
        self.assertEqual((await self.rows(self.Log))[0].status, "pending")
        await self.Service._renew(claimed, start_request=True)
        with self.assertRaisesRegex(RuntimeError, "禁止重复请求"):
            await self.Service._renew(claimed, start_request=True)

    async def test_worker_cancellation_cleans_children_and_recovers_unknown(self):
        await self.create()
        started, execution_stopped, heartbeat_started, heartbeat_stopped = (asyncio.Event() for _ in range(4))

        async def execute(**kwargs):
            try:
                await self.start_request(kwargs)
                started.set()
                await asyncio.Event().wait()
            finally:
                execution_stopped.set()

        async def heartbeat(target):
            heartbeat_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                heartbeat_stopped.set()

        self.execute.side_effect = execute
        with patch.object(self.Service, "_heartbeat", side_effect=heartbeat):
            worker = asyncio.create_task(self.module.run_pending_batches_forever(asyncio.Event()))
            try:
                await asyncio.wait_for(started.wait(), 5)
                await asyncio.wait_for(heartbeat_started.wait(), 5)
            finally:
                worker.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(worker, 5)
        self.assertTrue(execution_stopped.is_set())
        self.assertTrue(heartbeat_stopped.is_set())
        target, = await self.rows(self.Target)
        self.assertEqual(target.status, "publishing")
        self.assertEqual(await self.Service.recover_interrupted_targets(), 0)
        await self.expire(target.id)
        self.assertEqual(await self.Service.recover_interrupted_targets(), 1)
        self.assertEqual([(await self.rows(model))[0].status for model in (self.Target, self.Log, self.Attempt, self.Batch)], ["unknown"] * 4)
        self.assertEqual(await self.Service.recover_interrupted_targets(), 0)
        await self.Service.run_batch("batch-1")
        self.execute.assert_awaited_once()

    async def test_heartbeat_loss_cancels_inflight_request_without_replay(self):
        await self.create()
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def execute(**kwargs):
            await self.start_request(kwargs)
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async def heartbeat(target):
            await started.wait()
            await self.expire(target["target_id"])
            await self.Service._renew(target)

        self.execute.side_effect = execute
        with patch.object(self.Service, "_heartbeat", side_effect=heartbeat):
            await asyncio.wait_for(self.Service.run_batch("batch-1"), 5)
        self.assertTrue(cancelled.is_set())
        self.assertEqual([(await self.rows(model))[0].status for model in (self.Target, self.Log, self.Attempt)], ["unknown"] * 3)
        await self.Service.run_batch("batch-1")
        self.execute.assert_awaited_once()

    async def test_attempt_timeout_releases_worker_but_never_replays_request(self):
        await self.create()
        cancelled, started = asyncio.Event(), asyncio.Event()

        async def execute(**kwargs):
            await self.start_request(kwargs)
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async def expired_wait(tasks, **kwargs):
            # guard 事务及释放均已完成，再模拟执行超时，避免取消 SQLite 建连。
            await started.wait()
            return set(), tasks

        self.execute.side_effect = execute
        with patch.object(self.module.asyncio, "wait", side_effect=expired_wait):
            await asyncio.wait_for(self.Service.run_batch("batch-1"), 5)
        self.assertTrue(cancelled.is_set())
        self.assertEqual((await self.rows(self.Target))[0].status, "unknown")
        self.assertIsNone(await self.Service.find_next_batch())
        self.execute.assert_awaited_once()

    async def test_worker_continues_after_transient_database_error(self):
        stop = asyncio.Event()
        recover = AsyncMock(side_effect=[RuntimeError("database unavailable"), 0])
        lookup = AsyncMock(return_value="batch-1")

        async def finish_batch(_batch_id):
            stop.set()

        async def immediate_retry(awaitable, **kwargs):
            awaitable.close()
            raise asyncio.TimeoutError

        with patch.object(self.Service, "recover_interrupted_targets", recover), \
                patch.object(self.Service, "find_next_batch", lookup), \
                patch.object(self.Service, "run_batch", side_effect=finish_batch) as execute, \
                patch.object(self.module.asyncio, "wait_for", side_effect=immediate_retry):
            await self.module.run_pending_batches_forever(stop)
        self.assertEqual(recover.await_count, 2)
        execute.assert_awaited_once_with("batch-1")

    async def test_partial_batch_does_not_block_next_batch(self):
        await self.create(material_ids=(11, 12))
        await self.run_result({"success": False})
        self.assertEqual(await self.Service.find_next_batch(), "batch-1")
        await self.run_result({"success": True, "item_id": "second"})
        self.assertEqual((await self.rows(self.Batch))[0].status, "partial")
        await self.create("batch-2")
        self.assertEqual(await self.Service.find_next_batch(), "batch-2")
        await self.run_result({"success": True, "item_id": "third"}, "batch-2")
        self.assertEqual([b.status for b in await self.rows(self.Batch)], ["partial", "success"])
        self.assertIsNone(await self.Service.find_next_batch())
        self.assertEqual(self.execute.await_count, 3)

    async def test_unknown_target_syncs_after_manual_log_reconciliation(self):
        for status in ("success", "failed", "skipped"):
            with self.subTest(status=status):
                await self.create(status)
                await self.run_result({"unknown": True}, status)
                target = next(t for t in await self.rows(self.Target) if t.batch_id == status)
                self.assertEqual((target.status, target.lease_token), ("unknown", None))
                self.assertEqual(await self.Service.recover_interrupted_targets(), 0)
                async with self.maker() as session:
                    log = await session.get(self.Log, target.publish_log_id)
                    log.status = status
                    log.item_id = "manual-item" if status == "success" else None
                    log.error_message = None if status == "success" else "人工确认"
                    await session.commit()
                self.settle.reset_mock()
                self.assertEqual(await self.Service.recover_interrupted_targets(), 1)
                async with self.maker() as session:
                    current = await session.get(self.Target, target.id)
                    batch = await session.get(self.Batch, status)
                    attempt = (await session.scalars(select(self.Attempt).where(self.Attempt.target_id == target.id))).one()
                self.assertEqual((current.status, attempt.status, current.attempt_count), (status, status, 1))
                self.assertEqual(attempt.item_id, "manual-item" if status == "success" else None)
                self.assertEqual(batch.status, "success" if status == "success" else "failed")
                self.settle.assert_awaited_once()
                self.assertEqual(self.settle.await_args.args, (target.publish_log_id, "failed" if status == "skipped" else status))
                self.assertEqual(await self.Service.recover_interrupted_targets(), 0)
                before = self.execute.await_count
                await self.Service.run_batch(status)
                self.assertEqual(self.execute.await_count, before)

    async def test_expired_pending_log_recovers_as_safe_failure(self):
        await self.create()
        claimed = await self.Service._claim_next_target("batch-1")
        await self.expire(claimed["target_id"])
        self.assertEqual(await self.Service.recover_interrupted_targets(), 1)
        self.assertEqual([(await self.rows(model))[0].status for model in (self.Target, self.Log, self.Attempt, self.Batch)], ["failed"] * 4)
        self.assertEqual(await self.Service.recover_interrupted_targets(), 0)
        self.assertIsNone(await self.Service.find_next_batch())
        self.execute.assert_not_awaited()

    async def test_all_windows_plan_per_product_and_reuse_identity(self):
        from common.utils.batch_schedule import plan_product_offsets
        self.offsets.side_effect = plan_product_offsets
        async with self.maker() as session:
            session.add_all([self.XYAccount(owner_id=7, account_id=f"a{i}", cookie="offline", login_method="cookie") for i in range(4)])
            await session.commit()
        for hours in (1, 3, 5, 12, 24):
            batch = await self.create(str(hours), account_ids=["acct", "a0", "a1", "a2", "a3"], material_ids=(11, 12), window_hours=hours)
            targets = [t for t in await self.rows(self.Target) if t.batch_id == batch.id]
            self.assertEqual(batch.deadline_at - batch.window_started_at, timedelta(hours=hours))
            for mid in (11, 12):
                group = [t for t in targets if t.material_id == mid]
                self.assertEqual(len({t.internal_product_id for t in group}), 1)
                plans = sorted(t.scheduled_at for t in group)
                self.assertTrue(all(b - a >= timedelta(seconds=hours * 360) for a, b in zip(plans, plans[1:])))
                self.assertTrue(all(t.window_started_at == batch.window_started_at and t.minimum_gap_seconds == hours * 360 for t in group))
                self.assertTrue(all(batch.window_started_at <= t.scheduled_at <= batch.deadline_at for t in group))
        self.assertEqual(len(await self.rows(self.Product)), 2)
        self.assertEqual(len(await self.rows(self.Schedule)), 2)
        self.assertIsNone(await self.Service.find_next_batch())
        self.execute.assert_not_awaited()

    def test_api_window_schema_requires_explicit_supported_value(self):
        import ast
        from pydantic import BaseModel, Field, ValidationError
        from typing import List, Literal
        source = ast.parse((ROOT / "backend-web/app/api/routes/product_publish.py").read_text(encoding="utf-8-sig"))
        definitions = [node for node in source.body if isinstance(node, ast.ClassDef) and node.name in {"BatchPublishRequest", "BatchRetryRequest"}]
        namespace = {"BaseModel": BaseModel, "Field": Field, "List": List, "Literal": Literal}
        exec(compile(ast.Module(body=definitions, type_ignores=[]), "batch_schema", "exec"), namespace)
        for name, payload in (("BatchPublishRequest", {"account_ids": ["acct"], "material_ids": [11]}), ("BatchRetryRequest", {"target_ids": [1]})):
            schema = namespace[name]
            schema.model_rebuild(_types_namespace=namespace)
            with self.assertRaises(ValidationError):
                schema(**payload)
            for invalid in (None, 2, 6, 0, 48):
                with self.assertRaises(ValidationError):
                    schema(**payload, window_hours=invalid)
            for hours in (1, 3, 5, 12, 24):
                self.assertEqual(schema(**payload, window_hours=hours).window_hours, hours)

    async def test_explicit_window_and_material_ownership_are_required(self):
        for value in (None, 0, 2, 6, "1"):
            with self.assertRaises(ValueError):
                await self.create(window_hours=value)
        async with self.maker() as session:
            with self.assertRaises(TypeError):
                await self.Service(session).create_batch(owner_id=7, account_ids=["acct"], materials=[{"id": 11}], batch_id="missing")
            with self.assertRaises(ValueError):
                await self.Service(session).create_batch(owner_id=7, account_ids=["acct"], materials=[{"id": 99999}], batch_id="missing", window_hours=1)
        self.assertEqual(await self.rows(self.Target), [])

    async def test_product_guard_coordinates_batches_without_blocking_other_products(self):
        await self.create("one")
        await self.create("two")
        await self.create("different", material_ids=(12,))
        first = await self.Service._claim_next_target("one")
        second = await self.Service._claim_next_target("two")
        different = await self.Service._claim_next_target("different")
        async with self.Service._request_guard(first):
            with self.assertRaises(self.module.PublishScheduleDeferred) as caught:
                async with self.Service._request_guard(second):
                    self.fail("同商品不得并发请求")
            self.assertEqual(caught.exception.retry_at, self.now + timedelta(seconds=1800))
            async with self.Service._request_guard(different):
                pass
            schedule = (await self.rows(self.Schedule))[0]
            self.assertEqual((schedule.lease_target_id, schedule.last_request_started_at), (first["target_id"], self.now))
        schedule = (await self.rows(self.Schedule))[0]
        self.assertIsNone(schedule.lease_token)
        self.assertIsNone(schedule.lease_expires_at)
        with self.assertRaises(self.module.PublishScheduleDeferred):
            async with self.Service._request_guard(second):
                pass
        self.now += timedelta(seconds=1800)
        async with self.maker() as session:
            row = await session.get(self.Target, second["target_id"])
            row.lease_expires_at = self.now + timedelta(seconds=120)
            await session.commit()
        async with self.Service._request_guard(second):
            pass
        target = (await self.rows(self.Target))[1]
        attempt = (await self.rows(self.Attempt))[1]
        self.assertEqual((target.request_started_at, attempt.request_started_at), (self.now, self.now))
        self.assertEqual(target.scheduled_at, first["scheduled_at"])

    async def test_deferred_attempt_releases_capacity_and_uses_new_log(self):
        await self.create("one")
        await self.create("two")
        await self.run_result({"success": True, "item_id": "first"}, "one")
        original = (await self.rows(self.Target))[1].scheduled_at
        async def execute(**kwargs):
            async with kwargs["request_guard"]():
                return {"success": True, "item_id": "second"}
        self.execute.side_effect = execute
        self.settle.reset_mock()
        await self.Service.run_batch("two")
        target = (await self.rows(self.Target))[1]
        attempt = (await self.rows(self.Attempt))[1]
        log = (await self.rows(self.Log))[1]
        self.assertEqual((target.status, attempt.status, log.status), ("pending", "deferred", "failed"))
        self.assertEqual(target.scheduled_at, original)
        self.assertEqual(target.available_at, self.now + timedelta(seconds=1800))
        self.assertIsNone(target.publish_log_id)
        self.assertIsNone(target.request_started_at)
        self.settle.assert_awaited_once()
        self.assertEqual(self.settle.await_args.args, (log.id, "failed"))
        self.assertIsNone(await self.Service.find_next_batch())
        async with self.maker() as session:
            details = await self.Service(session).list_targets(7, "two", 1, 20)
            self.assertEqual(details["list"][0]["attempts"][0]["status"], "deferred")
        self.now = target.available_at
        await self.Service.run_batch("two")
        target = (await self.rows(self.Target))[1]
        self.assertEqual((target.status, target.attempt_count), ("success", 2))
        self.assertNotEqual(target.publish_log_id, log.id)
        self.assertEqual(target.scheduled_at, original)

    async def test_delayed_start_beyond_deadline_fails_without_request(self):
        await self.create("one")
        await self.create("two")
        self.now += timedelta(minutes=50)
        await self.run_result({"success": True, "item_id": "first"}, "one")
        requests = AsyncMock()
        async def execute(**kwargs):
            async with kwargs["request_guard"]():
                await requests()
        self.execute.side_effect = execute
        await self.Service.run_batch("two")
        target = (await self.rows(self.Target))[1]
        attempt = (await self.rows(self.Attempt))[1]
        self.assertEqual((target.status, attempt.status), ("failed", "failed"))
        self.assertIn("窗口", target.schedule_error)
        self.assertIsNone(target.request_started_at)
        requests.assert_not_awaited()
        async with self.maker() as session:
            status = await self.Service.get_status(session, 7, "two")
        self.assertEqual((status["timed_out"], status["finished"]), (1, True))

    async def test_restart_expires_pending_even_if_available_time_is_later(self):
        await self.create(material_ids=(11, 12))
        async with self.maker() as session:
            targets = (await session.scalars(select(self.Target))).all()
            for target in targets:
                target.available_at = self.now + timedelta(days=2)
            schedule = (await session.scalars(select(self.Schedule))).first()
            schedule.lease_token, schedule.lease_target_id = "crashed", targets[0].id
            schedule.lease_expires_at = self.now + timedelta(seconds=90)
            await session.commit()
        self.now += timedelta(hours=2)
        self.assertEqual(await self.Service.expire_pending_targets(), 2)
        self.assertEqual([t.status for t in await self.rows(self.Target)], ["failed", "failed"])
        self.assertEqual([a.status for a in await self.rows(self.Attempt)], ["failed", "failed"])
        self.assertIsNone((await self.rows(self.Schedule))[0].lease_token)
        async with self.maker() as session:
            data = await self.Service.get_status(session, 7, "batch-1")
        self.assertEqual((data["timed_out"], data["finished"], data["status"]), (2, True, "failed"))
        self.execute.assert_not_awaited()
        self.assertEqual(await self.Service.expire_pending_targets(), 0)

    async def test_retry_opens_new_window_only_for_selected_failure(self):
        await self.create(material_ids=(11, 12))
        await self.run_result({"success": False, "message": "明确失败"})
        await self.run_result({"success": False, "message": "明确失败"})
        first, second = await self.rows(self.Target)
        old_attempts = await self.rows(self.Attempt)
        self.now += timedelta(days=1)
        async with self.maker() as session:
            count = await self.Service(session).retry_failed(7, "batch-1", [first.id], window_hours=3)
        current, untouched = await self.rows(self.Target)
        self.assertEqual(count, 1)
        self.assertEqual((current.window_hours, current.window_started_at, current.deadline_at), (3, self.now, self.now + timedelta(hours=3)))
        self.assertEqual(current.minimum_gap_seconds, 5400)
        self.assertEqual((untouched.status, untouched.window_started_at, untouched.scheduled_at), ("failed", second.window_started_at, second.scheduled_at))
        self.assertEqual((await self.rows(self.Attempt))[0].window_started_at, old_attempts[0].window_started_at)
        self.assertIsNone(current.request_started_at)

    async def test_real_executor_deferred_releases_real_capacity_and_preserves_history(self):
        from unittest.mock import Mock
        from common.models.publish_capacity_reservation import PublishCapacityReservation
        from common.models.internal_product import InternalProductListing
        async with self.engine.begin() as conn:
            await conn.run_sync(lambda sync: self.Base.metadata.create_all(sync, tables=[PublishCapacityReservation.__table__, InternalProductListing.__table__]))
        self.enterContext(patch.object(sys.modules["common.db.session"], "async_session_maker", self.maker))
        for name, attrs in {
            "common.services.item_service": {"ItemService": Mock()},
            "common.services.publish_address_service": {"PublishAddressService": Mock()},
            "common.services.xianyu_publish_service": {
                "detect_publish_account_capability": AsyncMock(return_value={"success": True, "is_fish_shop": True}),
                "ensure_publish_capability_reliable": lambda value: value,
                "publish_single_item": AsyncMock(), "publish_personal_single_item": AsyncMock(),
            },
        }.items():
            stub = types.ModuleType(name)
            stub.__dict__.update(attrs)
            self.enterContext(patch.dict(sys.modules, {name: stub}))
        spec = importlib.util.spec_from_file_location("common.services.publish_capacity_service", ROOT / "common/services/publish_capacity_service.py")
        capacity = importlib.util.module_from_spec(spec)
        self.enterContext(patch.dict(sys.modules, {spec.name: capacity}))
        spec.loader.exec_module(capacity)
        spec = importlib.util.spec_from_file_location("_schedule_real_executor", ROOT / "common/services/publish_execution_service.py")
        executor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(executor)
        address = types.SimpleNamespace(apply_to_item_data=lambda data: data, to_log_fields=lambda: {})
        executor.PublishAddressService = Mock(return_value=types.SimpleNamespace(resolve_publish_address=AsyncMock(return_value=address)))
        executor._sync_account_items_after_publish = AsyncMock(side_effect=RuntimeError("成功后的同步失败"))
        self.enterContext(patch.object(self.module, "execute_single_publish", executor.execute_single_publish))
        self.enterContext(patch.object(self.module, "settle_publish_capacity", capacity.settle_publish_capacity))
        calls = []
        async def publish(**kwargs):
            async with kwargs["request_guard"]():
                calls.append(self.now)
            return {"success": True, "item_id": f"item-{len(calls)}"}
        executor.publish_single_item.side_effect = publish
        async with self.maker() as session:
            account = (await session.scalars(select(self.XYAccount).where(self.XYAccount.owner_id == 7))).one()
            account.remaining_publish_capacity = 3
            await session.commit()
        await self.create("one")
        await self.create("two")
        await self.Service.run_batch("one")
        await self.Service.run_batch("two")
        first, second = await self.rows(self.Target)
        self.assertEqual((first.status, second.status), ("success", "pending"))
        self.assertEqual(len(calls), 1)
        reservations = await self.rows(PublishCapacityReservation)
        self.assertEqual(sorted(r.status for r in reservations), ["released", "succeeded"])
        account = (await self.rows(self.XYAccount))[0]
        self.assertEqual((account.remaining_publish_capacity, account.reserved_publish_count), (2, 0))
        self.now = second.available_at
        await self.Service.run_batch("two")
        account = (await self.rows(self.XYAccount))[0]
        self.assertEqual((account.remaining_publish_capacity, account.reserved_publish_count), (1, 0))
        self.assertEqual([t.status for t in await self.rows(self.Target)], ["success", "success"])
        self.assertEqual([a.status for a in await self.rows(self.Attempt)], ["success", "deferred", "success"])
        self.assertEqual(len(calls), 2)

    async def test_product_lease_renews_and_cancellation_clears_it(self):
        await self.create()
        claimed = await self.Service._claim_next_target("batch-1")
        entered = asyncio.Event()
        async def request():
            async with self.Service._request_guard(claimed):
                entered.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(request())
        try:
            await entered.wait()
            self.now += timedelta(seconds=20)
            await self.Service._renew(claimed)
            schedule, = await self.rows(self.Schedule)
            self.assertEqual(schedule.lease_expires_at, self.now + timedelta(seconds=self.module.PRODUCT_LEASE_SECONDS))
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        schedule, = await self.rows(self.Schedule)
        self.assertIsNone(schedule.lease_token)
        self.assertIsNotNone(schedule.last_request_started_at)

    async def test_future_plan_is_not_claimed_and_guard_rechecks_it(self):
        self.offsets.side_effect = lambda n, t: (300,) * n
        await self.create()
        self.assertIsNone(await self.Service.find_next_batch())
        self.assertIsNone(await self.Service._claim_next_target("batch-1"))
        self.now += timedelta(seconds=300)
        claimed = await self.Service._claim_next_target("batch-1")
        async with self.maker() as session:
            target = await session.get(self.Target, claimed["target_id"])
            target.scheduled_at = self.now + timedelta(seconds=30)
            await session.commit()
        with self.assertRaises(self.module.PublishScheduleDeferred) as caught:
            async with self.Service._request_guard(claimed):
                self.fail("计划之前不得发布")
        self.assertEqual(caught.exception.retry_at, self.now + timedelta(seconds=30))
        self.assertIsNone((await self.rows(self.Target))[0].request_started_at)
        self.assertEqual((await self.rows(self.Log))[0].status, "pending")

    async def test_guard_exit_releases_lease_after_exception_and_blocks_duplicate(self):
        await self.create()
        claimed = await self.Service._claim_next_target("batch-1")
        with self.assertRaisesRegex(RuntimeError, "请求失败"):
            async with self.Service._request_guard(claimed):
                raise RuntimeError("请求失败")
        self.assertIsNone((await self.rows(self.Schedule))[0].lease_token)
        with self.assertRaisesRegex(RuntimeError, "禁止重复请求"):
            async with self.Service._request_guard(claimed):
                pass

    async def test_post_release_heartbeat_renewal_does_not_fail_confirmed_publish(self):
        """商品租约只在最终请求边界内有效，释放后的心跳续约不能中断已确认的发布。

        回归点：guard 释放商品租约后，若 `product_lease_active` 未复位，心跳仍会尝试
        续约已释放的商品租约并抛出执行权失效；run_batch 会因此取消仍在进行中的
        发布后同步，把平台已成功的发布收尾成 unknown。
        """
        await self.create()
        guard_released, post_request = asyncio.Event(), asyncio.Event()

        async def execute(**kwargs):
            async with kwargs["request_guard"]():
                pass
            # 平台请求已发起，进入耗时较长的发布后同步。
            guard_released.set()
            await post_request.wait()
            return {"success": True, "item_id": "confirmed-item"}

        async def heartbeat(target):
            await guard_released.wait()
            # 真实心跳按 HEARTBEAT_SECONDS 独立调度，此时 guard 已释放商品租约。
            await self.Service._renew(target)
            post_request.set()

        self.execute.side_effect = execute
        with patch.object(self.Service, "_heartbeat", side_effect=heartbeat):
            await asyncio.wait_for(self.Service.run_batch("batch-1"), 5)

        target, = await self.rows(self.Target)
        log, = await self.rows(self.Log)
        attempt, = await self.rows(self.Attempt)
        self.assertEqual((target.status, log.status, attempt.status), ("success",) * 3)
        self.assertEqual(target.error_message, None)
        self.assertEqual((target.lease_token, target.lease_expires_at), (None, None))
        self.assertEqual((await self.rows(self.Schedule))[0].lease_token, None)
        self.settle.assert_awaited_once_with(log.id, "success", item_id="confirmed-item", error_message=None)

    async def test_product_lease_flag_blocks_renewal_only_while_guard_holds_lease(self):
        """复位标志必须精确跟随商品租约的持有区间（不是简单放宽校验）。"""
        await self.create()
        claimed = await self.Service._claim_next_target("batch-1")

        async with self.Service._request_guard(claimed):
            schedule, = await self.rows(self.Schedule)
            self.assertEqual(schedule.lease_target_id, claimed["target_id"])
            self.assertIsNotNone(schedule.lease_token)
            self.assertTrue(claimed["product_lease_active"])
            # 持有期间心跳必须同时续商品租约，否则长请求会丢掉商品级协调。
            self.now += timedelta(seconds=20)
            await self.Service._renew(claimed)
            schedule, = await self.rows(self.Schedule)
            self.assertEqual(
                schedule.lease_expires_at,
                self.now + timedelta(seconds=self.module.PRODUCT_LEASE_SECONDS),
            )

        # 释放后标志必须复位，心跳只续目标租约。
        self.assertFalse(claimed["product_lease_active"])
        await self.Service._renew(claimed)
        self.assertIsNone((await self.rows(self.Schedule))[0].lease_token)

        # 反向确认：标志仍为 True 时续约确实会失败，证明该复位是必要保护而非放宽校验。
        claimed["product_lease_active"] = True
        with self.assertRaisesRegex(RuntimeError, "商品发布执行权已失效"):
            await self.Service._renew(claimed)
        self.assertEqual((await self.rows(self.Target))[0].lease_token, claimed["token"])

    async def test_late_failed_result_keeps_failure_retryable_and_flags_window_overrun(self):
        """超窗收尾用数据库时间判定；明确失败仍可重试，不因超窗被降级或升级。"""
        await self.create()
        self.assertGreaterEqual(self.now + timedelta(hours=1), self.now)
        async with self.maker() as session:
            target_before = (await session.scalars(select(self.Target))).one()
            deadline = target_before.deadline_at

        async def execute(**kwargs):
            async with kwargs["request_guard"]():
                pass
            # 平台明确拒绝；收尾发生在排程窗口之后（含后处理时间）。
            self.now = deadline + timedelta(minutes=5)
            return {"success": False, "message": "明确失败"}

        self.execute.side_effect = execute
        await self.Service.run_batch("batch-1")
        target, = await self.rows(self.Target)
        attempt, = await self.rows(self.Attempt)
        self.assertEqual(target.status, "failed")
        # finished_at 取数据库时间（测试内被固定为 self.now），而非进程本地时钟。
        self.assertEqual(target.finished_at, self.now)
        self.assertIn("结果收尾超过排程窗口", target.schedule_error)
        self.assertEqual(attempt.schedule_error, target.schedule_error)
        self.assertEqual(target.error_message, "明确失败")
        async with self.maker() as session:
            status = await self.Service.get_status(session, 7, "batch-1")
            self.assertEqual((status["timed_out"], status["finished"]), (1, True))
            # 明确失败项即使超窗也必须仍可重试（只重试失败项的既有约束不受影响）。
            self.assertEqual(await self.Service(session).retry_failed(7, "batch-1", [target.id], window_hours=1), 1)
        pending, = await self.rows(self.Target)
        self.assertEqual((pending.status, pending.attempt_count), ("pending", 1))
        self.assertEqual([a.status for a in await self.rows(self.Attempt)], ["failed"])
        self.assertEqual(self.execute.await_count, 1)


if __name__ == "__main__":
    unittest.main()
