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
        cls.models = (cls.Batch, cls.Account, cls.Attempt, cls.Target, cls.Log, cls.XYAccount)

    async def asyncSetUp(self):
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

    async def create(self, batch_id="batch-1", owner_id=7, account_ids=None, material_ids=(11,)):
        async with self.maker() as session:
            return await self.Service(session).create_batch(
                owner_id=owner_id, account_ids=account_ids or ["acct", "acct"], batch_id=batch_id,
                materials=[{"id": mid, "title": f"素材{mid}", "description": "离线素材", "price": 1} for mid in material_ids],
            )

    async def rows(self, model):
        async with self.maker() as session:
            return list((await session.scalars(select(model).order_by(model.id))).all())

    async def expire(self, target_id):
        async with self.maker() as session:
            target = await session.get(self.Target, target_id)
            target.lease_expires_at = self.module.get_beijing_now_naive() - timedelta(seconds=1)
            await session.commit()

    async def run_result(self, result, batch_id="batch-1"):
        async def execute(**kwargs):
            await kwargs["before_publish"]()
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
            await kwargs["before_publish"]()
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

    async def test_success_result_backfills_log_item_id(self):
        await self.create()
        await self.run_result({"success": True, "item_id": "returned-item"})
        log, = await self.rows(self.Log)
        self.assertEqual((log.status, log.item_id), ("success", "returned-item"))

    async def test_request_started_then_exception_becomes_unknown_without_replay(self):
        await self.create()

        async def execute(**kwargs):
            await kwargs["before_publish"]()
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
            await kwargs["before_publish"]()
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
            self.assertEqual(await self.Service(session).retry_failed(7, "batch-1", [target.id, target.id]), 1)
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
                        await self.Service(session).retry_failed(7, status, [target.id])
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
                await service.retry_failed(8, "batch-1", [target.id])
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
                        await self.Service(session).retry_failed(7, "batch-1", ids)
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
                await kwargs["before_publish"]()
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
                await kwargs["before_publish"]()
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
            await kwargs["before_publish"]()
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
        cancelled = asyncio.Event()

        async def execute(**kwargs):
            await kwargs["before_publish"]()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        real_wait = asyncio.wait

        async def expired_wait(tasks, **kwargs):
            # Wait until the simulated request has started, then force the deadline.
            while (await self.rows(self.Log))[0].status != "publishing":
                await real_wait(tasks, timeout=0.01)
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


if __name__ == "__main__":
    unittest.main()
