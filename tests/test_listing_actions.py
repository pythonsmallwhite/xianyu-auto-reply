"""Offline durable listing actions: real SQLite transactions, no platform access."""
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from sqlalchemy import select
from tests import test_durable_publish_batch_service as fixture

class ListingActionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        fixture.DurablePublishBatchTests.setUpClass.__func__(cls)
        from common.models.listing_action import ListingActionBatch, ListingActionTarget, ListingActionAttempt
        from common.models.internal_product import InternalProductListing, InventoryOrderHold
        from common.services import listing_action_service, listing_action_platform
        cls.actions, cls.platform = listing_action_service, listing_action_platform
        cls.ActionBatch, cls.ActionTarget, cls.ActionAttempt = ListingActionBatch, ListingActionTarget, ListingActionAttempt
        cls.Listing = InternalProductListing
        cls.Hold = InventoryOrderHold
        cls.models += (ListingActionBatch, ListingActionTarget, ListingActionAttempt, InternalProductListing, InventoryOrderHold)

    async def asyncSetUp(self):
        await fixture.DurablePublishBatchTests.asyncSetUp(self)
        self.enterContext(patch.object(self.actions, "async_session_maker", self.maker))
        self.enterContext(patch.object(self.actions, "database_now", AsyncMock(side_effect=lambda session: self.now)))
        self.enterContext(patch.object(self.actions, "plan_product_offsets", side_effect=lambda n,w: tuple(i*w*3600/(2*n) for i in range(n))))
        self.call = self.enterContext(patch.object(self.actions, "offline_listing", AsyncMock()))
        self.relist_call = self.enterContext(patch.object(self.actions, "relist_listing", AsyncMock()))
        async with self.maker() as session:
            session.add(self.Product(id=10, owner_id=7, title="offline fixture"))
            session.add(self.Listing(id=20, owner_id=7, internal_product_id=10, account_id="acct", item_id="item", publish_log_id=100, state="active"))
            await session.commit()

    rows = fixture.DurablePublishBatchTests.rows

    async def create(self, batch_id="action", window=1):
        async with self.maker() as session:
            result = await self.actions.ListingActionService(session).create(7, 10, [20], window, batch_id)
            await session.commit()
            return result

    async def run_status(self, status):
        async def call(account, cookie, item, owner, guard):
            async with guard():
                return {"status": status, "message": "offline test"}
        self.call.side_effect = call
        await self.actions.run_one()

    async def test_success_updates_exact_listing_and_never_replays(self):
        await self.create()
        await self.run_status("success")
        row, = await self.rows(self.Listing)
        self.assertEqual((row.state, row.offline_reason, row.state_version), ("offline", "manual", 1))
        self.assertFalse(await self.actions.run_one())
        self.call.assert_awaited_once()
        async with self.maker() as s:
            d = await self.actions.ListingActionService(s).detail(7, "action")
            self.assertEqual(d["attempts"][0]["status"], "success")
            with self.assertRaises(ValueError):
                await self.actions.ListingActionService(s).detail(8, "action")

    async def test_owner_scope_and_unlinked_rejected(self):
        for owner, ids in [(8,[20]), (7,[999]), (7,[])]:
            async with self.maker() as s:
                with self.assertRaises(ValueError):
                    await self.actions.ListingActionService(s).create(owner,10,ids,1,"x")
        self.assertEqual(await self.rows(self.ActionBatch), [])

    async def test_request_id_is_idempotent_and_payload_cannot_change(self):
        await self.create()
        await self.create()
        self.assertEqual(len(await self.rows(self.ActionTarget)),1)
        with self.assertRaises(ValueError):
            await self.create(window=3)

    async def test_retry_only_failed_and_new_window(self):
        await self.create()
        await self.run_status("failed")
        row, = await self.rows(self.ActionTarget)
        async with self.maker() as s:
            service = self.actions.ListingActionService(s)
            result = await service.retry(7,"action",[row.id],3,"retry")
            await s.commit()
            self.assertEqual(result,"retry")
        async with self.maker() as s:
            with self.assertRaises(ValueError):
                await self.actions.ListingActionService(s).retry(7,"action",[row.id],1,"again")
        batch = next(b for b in await self.rows(self.ActionBatch) if b.id=="retry")
        self.assertEqual(batch.deadline_at, self.now+timedelta(hours=3))

    async def test_unknown_never_retryable(self):
        await self.create()
        await self.run_status("unknown")
        row, = await self.rows(self.ActionTarget)
        async with self.maker() as s:
            with self.assertRaises(ValueError):
                await self.actions.ListingActionService(s).retry(7,"action",[row.id],1,"retry")
        self.assertFalse(await self.actions.run_one())

    async def test_recovery_after_request_keeps_unknown(self):
        await self.create()
        target, token = await self.actions.claim()
        async with self.actions.request_guard(target,token):
            pass
        self.now += timedelta(seconds=121)
        await self.actions.recover()
        row, = await self.rows(self.ActionTarget)
        self.assertEqual(row.status,"unknown")
        self.call.assert_not_awaited()

    async def test_expired_window_makes_no_platform_request(self):
        await self.create()
        self.now += timedelta(hours=2)
        target, token = await self.actions.claim()
        with self.assertRaises(ValueError):
            async with self.actions.request_guard(target, token):
                self.fail("guard must not permit HTTP")

    async def test_state_version_change_stops_old_request(self):
        await self.create()
        async with self.maker() as s:
            row = await s.get(self.Listing,20)
            row.state_version += 1
            await s.commit()
        target,token = await self.actions.claim()
        with self.assertRaises(ValueError):
            async with self.actions.request_guard(target,token):
                self.fail("stale request")

    async def test_product_slot_is_shared_with_publish(self):
        await self.create()
        async with self.maker() as s:
            schedule = (await s.scalars(select(self.Schedule))).one()
            schedule.last_request_started_at = self.now
            await s.commit()
        target,token = await self.actions.claim()
        with self.assertRaises(self.actions.Deferred):
            async with self.actions.request_guard(target,token):
                self.fail("must respect previous product request")

    async def test_duplicate_new_batch_cannot_bypass_unknown_protection(self):
        await self.create()
        with self.assertRaises(ValueError):
            await self.create("duplicate")
        await self.run_status("unknown")
        with self.assertRaises(ValueError):
            await self.create("duplicate")

    async def test_adapter_uses_single_guarded_transport(self):
        import sys, types
        stub = types.ModuleType("common.services.xianyu_mtop")
        stub.mtop_call = AsyncMock(return_value={"_request_status_unknown": True})
        with patch.dict(sys.modules, {stub.__name__: stub}):
            guard = object()
            result = await self.platform.offline_listing("acct", "offline", "item", 7, guard)
        self.assertEqual(result["status"], "unknown")
        stub.mtop_call.assert_awaited_once()
        self.assertIs(stub.mtop_call.call_args.kwargs["request_guard"], guard)
        self.assertEqual(stub.mtop_call.call_args.kwargs["version"], "1.0")

    async def test_request_exception_stays_unknown_and_is_not_replayed(self):
        await self.create()
        async def call(account,cookie,item,owner,guard):
            async with guard():
                raise OSError("offline network failure")
        self.call.side_effect = call
        await self.actions.run_one()
        row, = await self.rows(self.ActionTarget)
        self.assertEqual(row.status,"unknown")
        self.assertFalse(await self.actions.run_one())
        self.call.assert_awaited_once()

    async def test_unstarted_recovery_and_late_success(self):
        await self.create()
        await self.actions.claim()
        self.now += timedelta(seconds=121)
        await self.actions.recover()
        row, = await self.rows(self.ActionTarget)
        self.assertEqual(row.status,"failed")
        async with self.maker() as s:
            await self.actions.ListingActionService(s).retry(7,"action",[row.id],1,"retry")
            await s.commit()
        async def call(account,cookie,item,owner,guard):
            async with guard():
                self.now += timedelta(hours=2)
                return {"status":"success", "message":"confirmed"}
        self.call.side_effect = call
        await self.actions.run_one()
        row = next(r for r in await self.rows(self.ActionTarget) if r.batch_id=="retry")
        self.assertEqual(row.status,"success")
        self.assertIn("窗口",row.schedule_error)

    async def reconcile(self, state="offline", note="人工核对", target_id=None, batch_id="action"):
        if target_id is None:
            target_id = (await self.rows(self.ActionTarget))[0].id
        async with self.maker() as session:
            result = await self.actions.ListingActionService(session).reconcile(
                7, batch_id, target_id, state, note)
            await session.commit()
            return result

    async def test_reconcile_active_allows_a_deliberate_new_batch_only(self):
        """核对为「仍在售」解除 unknown 阻碍，但下架仍需人工重新发起。"""
        await self.create()
        await self.run_status("unknown")
        await self.reconcile("active")
        self.assertEqual(await self.create("next"), "next")
        self.call.assert_awaited_once()
        self.assertEqual(len(await self.rows(self.ActionBatch)), 2)

    async def test_reconcile_only_accepts_unknown_with_explicit_platform_state(self):
        await self.create()
        target, = await self.rows(self.ActionTarget)
        async with self.maker() as s:
            service = self.actions.ListingActionService(s)
            with self.assertRaises(ValueError):
                await service.reconcile(7, "action", target.id, "maybe", "核对依据")
            with self.assertRaises(ValueError):
                await service.reconcile(7, "action", target.id, "offline", "   ")
            with self.assertRaises(ValueError):
                await service.reconcile(7, "action", target.id, "offline", "核对依据")
        await self.run_status("success")
        async with self.maker() as s:
            with self.assertRaises(ValueError):
                await self.actions.ListingActionService(s).reconcile(7, "action", target.id, "offline", "核对依据")
        target, = await self.rows(self.ActionTarget)
        self.assertIsNone(target.reconciled_state)

    async def test_reconcile_offline_records_state_and_never_resends(self):
        await self.create()
        await self.run_status("unknown")
        result = await self.reconcile()
        self.assertEqual(result["status"], "reconciled")
        target, = await self.rows(self.ActionTarget)
        self.assertEqual((target.status, target.reconciled_state, target.reconciled_note),
                         ("reconciled", "offline", "人工核对"))
        self.assertIsNotNone(target.reconciled_at)
        listing, = await self.rows(self.Listing)
        self.assertEqual((listing.state, listing.offline_reason, listing.state_version),
                         ("offline", "manual", 1))
        self.call.assert_awaited_once()
        self.assertFalse(await self.actions.run_one())
        self.call.assert_awaited_once()

    async def test_reconcile_keeps_conflict_warning_and_does_not_overwrite_local_change(self):
        await self.create()
        await self.run_status("unknown")
        async with self.maker() as s:
            listing = await s.get(self.Listing, 20)
            listing.state, listing.state_version = "active", 1
            await s.commit()
        await self.reconcile()
        listing, = await self.rows(self.Listing)
        self.assertEqual((listing.state, listing.state_version), ("active", 1))
        target, = await self.rows(self.ActionTarget)
        self.assertIn("本地状态已变更", target.message)

    async def test_reconcile_conflict_survives_repeat_and_legacy_record(self):
        await self.create()
        await self.run_status("unknown")
        async with self.maker() as session:
            listing = await session.get(self.Listing, 20)
            listing.state_version += 1
            await session.commit()
        first = await self.reconcile()
        self.assertTrue(first["conflict"])
        self.assertTrue((await self.reconcile())["conflict"])
        async with self.maker() as session:
            target = await session.get(self.ActionTarget, 1)
            target.reconciled_conflict = None
            await session.commit()
        legacy = await self.reconcile()
        self.assertTrue(legacy["conflict"])
        self.assertEqual(legacy["message"], first["message"])
        self.assertEqual((await self.rows(self.Listing))[0].state, "active")
        self.call.assert_awaited_once()

    async def test_reconcile_active_keeps_listing_and_unblocks_new_batch(self):
        await self.create()
        await self.run_status("unknown")
        with self.assertRaises(ValueError):
            await self.create("blocked")
        await self.reconcile("active")
        self.assertEqual((await self.rows(self.Listing))[0].state, "active")
        self.assertEqual(await self.create("next"), "next")

    async def test_reconciled_offline_batch_is_rejected_for_listing_state_not_unknown(self):
        await self.create()
        await self.run_status("unknown")
        await self.reconcile()
        with self.assertRaises(ValueError) as caught:
            await self.create("next")
        self.assertIn("在售", str(caught.exception))

    async def test_reconcile_is_owner_scoped_idempotent_and_rejects_contradiction(self):
        await self.create()
        await self.run_status("unknown")
        async with self.maker() as s:
            with self.assertRaises(ValueError):
                await self.actions.ListingActionService(s).reconcile(8, "action", 1, "offline", None)
        await self.reconcile()
        self.assertEqual((await self.reconcile())["status"], "reconciled")
        self.assertEqual((await self.rows(self.Listing))[0].state_version, 1)
        with self.assertRaises(ValueError):
            await self.reconcile("active")
        self.assertEqual((await self.rows(self.Listing))[0].state_version, 1)

    async def test_reconcile_after_listing_removal_stays_idempotent(self):
        """Listing 被删除后重复核对不能抛异常：接口必须可重复调用。"""
        await self.create()
        await self.run_status("unknown")
        await self.reconcile()
        async with self.maker() as s:
            await s.delete(await s.get(self.Listing, 20))
            await s.commit()
        async with self.maker() as s:
            result = await self.actions.ListingActionService(s).reconcile(7, "action", 1, "offline", "再次核对")
            await s.commit()
        self.assertEqual(result["status"], "reconciled")
        self.assertIsNone(result["listing_state"])

    async def test_reconcile_active_never_resends(self):
        await self.create()
        await self.run_status("unknown")
        await self.reconcile("active")
        self.assertFalse(await self.actions.run_one())
        self.call.assert_awaited_once()
        target, = await self.rows(self.ActionTarget)
        self.assertEqual((target.status, target.reconciled_state), ("reconciled", "active"))

    async def test_reconcile_rejects_target_from_another_batch(self):
        await self.create()
        await self.run_status("unknown")
        async with self.maker() as s:
            s.add(self.Product(id=11, owner_id=7, title="second"))
            s.add(self.Listing(id=21, owner_id=7, internal_product_id=11, account_id="acct", item_id="item2", publish_log_id=101, state="active"))
            await s.commit()
            await self.actions.ListingActionService(s).create(7, 11, [21], 1, "other")
            await s.commit()
        other, = [t for t in await self.rows(self.ActionTarget) if t.batch_id == "other"]
        async with self.maker() as s:
            with self.assertRaises(ValueError):
                await self.actions.ListingActionService(s).reconcile(7, "action", other.id, "offline", "错批次")
        self.assertEqual((await self.rows(self.ActionTarget))[0].status, "unknown")

    async def test_reconcile_requires_account_ownership(self):
        from common.models.xy_account import XYAccount
        await self.create()
        await self.run_status("unknown")
        async with self.maker() as s:
            account = await s.get(XYAccount, 1)
            account.owner_id = 8
            await s.commit()
        async with self.maker() as s:
            with self.assertRaises(ValueError):
                await self.actions.ListingActionService(s).reconcile(7, "action", 1, "offline", "归属变了")
        self.assertEqual((await self.rows(self.ActionTarget))[0].status, "unknown")
        self.assertEqual((await self.rows(self.ActionTarget))[0].status, "unknown")

    async def test_strict_platform_results(self):
        parse = self.platform.classify_offline_response
        def response(rows):
            return {"res":{"ret":["SUCCESS::ok"],"data":{"code":"success","data":{"itemProcessResultList":rows}}}}
        self.assertEqual(parse(response([]),"item"),"unknown")
        self.assertEqual(parse(response([{"itemId":"item","success":"false"}]),"item"),"unknown")
        self.assertEqual(parse(response([{"itemId":"other","success":True}]),"item"),"unknown")
        self.assertEqual(parse(response([{"itemId":"item","success":True}]),"item"),"success")
        self.assertEqual(parse(response([{"itemId":"item","success":False}]),"item"),"failed")
        self.assertEqual(parse({"_request_status_unknown":True},"item"),"unknown")


    async def create_relist(self, batch_id="relist", window=1):
        async with self.maker() as session:
            result = await self.actions.ListingActionService(session).create(
                7, 10, [20], window, batch_id, operation="relist")
            await session.commit()
            return result

    async def prepare_relist(self):
        async with self.maker() as session:
            product = await session.get(self.Product, 10)
            product.total_stock = 3
            listing = await session.get(self.Listing, 20)
            listing.state, listing.offline_reason = "offline", "inventory"
            await session.commit()
        return await self.create_relist()

    async def run_relist_status(self, status):
        async def call(account, cookie, item, owner, guard):
            async with guard():
                return {"status": status, "message": "relist test"}
        self.relist_call.side_effect = call
        await self.actions.run_one()

    async def test_relist_operation_is_explicit_and_request_idempotent(self):
        await self.prepare_relist()
        self.assertEqual(await self.create_relist(), "relist")
        batches = await self.rows(self.ActionBatch)
        targets = await self.rows(self.ActionTarget)
        self.assertEqual([(row.operation, row.window_hours) for row in batches], [("relist", 1)])
        self.assertEqual(len(targets), 1)

    async def test_relist_success_reactivates_only_inventory_offline_listing(self):
        await self.prepare_relist()
        await self.run_relist_status("success")
        listing, = await self.rows(self.Listing)
        self.assertEqual((listing.state, listing.offline_reason, listing.state_version),
                         ("active", None, 1))
        target, = await self.rows(self.ActionTarget)
        self.assertEqual((target.status, target.message), ("success", "relist test"))
        self.relist_call.assert_awaited_once()
        self.call.assert_not_awaited()

    async def test_relist_failed_retry_preserves_operation_and_unknown_is_terminal(self):
        await self.prepare_relist()
        await self.run_relist_status("failed")
        target, = await self.rows(self.ActionTarget)
        async with self.maker() as session:
            self.assertEqual(
                await self.actions.ListingActionService(session).retry(
                    7, "relist", [target.id], 3, "relist-retry"),
                "relist-retry")
            await session.commit()
        retry = next(row for row in await self.rows(self.ActionBatch) if row.id == "relist-retry")
        self.assertEqual((retry.operation, retry.window_hours), ("relist", 3))
        self.assertEqual(len(await self.rows(self.ActionTarget)), 2)
        await self.run_relist_status("unknown")
        unknown = next(row for row in await self.rows(self.ActionTarget) if row.batch_id == "relist-retry")
        self.assertEqual(unknown.status, "unknown")
        listing, = await self.rows(self.Listing)
        self.assertEqual(listing.state, "offline")
        async with self.maker() as session:
            with self.assertRaises(ValueError):
                await self.actions.ListingActionService(session).retry(
                    7, "relist-retry", [unknown.id], 1, "relist-retry-2")

    async def test_relist_rejects_manual_offline_and_stale_version_guard(self):
        async with self.maker() as session:
            product = await session.get(self.Product, 10)
            product.total_stock = 3
            listing = await session.get(self.Listing, 20)
            listing.state, listing.offline_reason = "offline", "manual"
            await session.commit()
        with self.assertRaises(ValueError):
            await self.create_relist("manual-relist")
        async with self.maker() as session:
            listing = await session.get(self.Listing, 20)
            listing.offline_reason = "inventory"
            await session.commit()
        await self.create_relist("stale-relist")
        async with self.maker() as session:
            listing = await session.get(self.Listing, 20)
            listing.state_version += 1
            await session.commit()
        await self.run_relist_status("success")
        row, = await self.rows(self.Listing)
        self.assertEqual((row.state, row.offline_reason, row.state_version),
                         ("offline", "inventory", 1))
        target, = await self.rows(self.ActionTarget)
        self.assertEqual(target.status, "failed")
        self.relist_call.assert_awaited_once()

class ListingActionMigrationTests(unittest.TestCase):
    """These tables are created by model-generated DDL with checkfirst=True.

    checkfirst creates a missing table but never alters an existing one, so every
    column and index must exist in the table's first DDL. What still needs proving
    is that a database created by an earlier release converges: the new tables do
    not exist there yet, so create is reached, but the schedule precision and the
    due-queue index must survive an upgrade path that only runs ALTERs.
    """

    @classmethod
    def setUpClass(cls):
        import ast
        from pathlib import Path
        cls.source = Path(__file__).resolve().parents[1] / "common/db/init_database.py"
        cls.text = cls.source.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.text)

    def literal_assign(self, name):
        import ast
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets
            ):
                return ast.literal_eval(node.value)
        self.fail(f"{name} not found in init_database.py")

    def test_unknown_resolution_columns_have_an_alter_path(self):
        """checkfirst=True never adds a column to a table that already exists.

        xy_listing_action_targets was already created by an earlier build of this
        feature, so the reconciliation columns must also be reachable through
        COLUMN_MIGRATIONS or they silently stay missing after an upgrade.
        """
        from common.models.listing_action import ListingActionTarget
        table = "xy_listing_action_targets"
        migrated = {name for name, _, _ in self.literal_assign("COLUMN_MIGRATIONS").get(table, [])}
        columns = {c.name for c in ListingActionTarget.__table__.columns}
        added = {"reconciled_state", "reconciled_note", "reconciled_at", "reconciled_conflict"}
        self.assertLessEqual(added, columns, "模型缺少核对字段")
        self.assertEqual(added - migrated, set(),
            f"已存在的表不会被 checkfirst 补字段，需加入 COLUMN_MIGRATIONS：{sorted(added - migrated)}")
        for name in added:
            self.assertTrue(ListingActionTarget.__table__.columns[name].nullable, f"{name} 必须允许为空")

    def test_schedule_columns_are_covered_by_the_precision_migration(self):
        """ALTER 只在精度不足时触发，因此新表的时间列也要登记在迁移表里。"""
        import ast
        from sqlalchemy.schema import CreateTable
        from sqlalchemy.dialects import mysql
        from common.models.listing_action import ListingActionBatch, ListingActionTarget, ListingActionAttempt
        coverage = None
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "schedule_time_columns" for t in node.targets
            ):
                coverage = ast.literal_eval(node.value)
        self.assertIsNotNone(coverage, "未找到排程时间精度迁移表")
        for model in (ListingActionBatch, ListingActionTarget, ListingActionAttempt):
            ddl = str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))
            expected = {n for n in coverage.get(model.__tablename__, ())}
            self.assertTrue(expected, f"{model.__tablename__} 未登记排程时间精度")
            for column in expected:
                self.assertIn(f"{column} DATETIME", ddl, f"{column} 不存在于 {model.__tablename__}")

    def test_migration_entries_reference_an_existing_previous_column(self):
        """ALTER ... AFTER <col> 的锚点必须真实存在，否则依赖回退分支。"""
        from common.models.listing_action import ListingActionTarget
        columns = {c.name for c in ListingActionTarget.__table__.columns}
        for name, _, after in self.literal_assign("COLUMN_MIGRATIONS").get("xy_listing_action_targets", []):
            self.assertIn(after, columns, f"{name} 的 AFTER 锚点 {after} 不存在")
            self.assertNotEqual(name, after)

    def test_due_queue_index_survives_table_generation(self):
        import asyncio
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine
        from common.models.listing_action import ListingActionBatch, ListingActionTarget, ListingActionAttempt

        async def probe():
            engine = create_async_engine("sqlite+aiosqlite://")
            tables = [ListingActionBatch.__table__, ListingActionTarget.__table__, ListingActionAttempt.__table__]
            async with engine.begin() as conn:
                for table in tables:
                    await conn.run_sync(lambda sync, tb=table: tb.create(sync, checkfirst=True))
            async with engine.connect() as conn:
                indexes = await conn.run_sync(lambda sync: inspect(sync).get_indexes("xy_listing_action_targets"))
                constraints = await conn.run_sync(lambda sync: inspect(sync).get_unique_constraints("xy_listing_action_targets"))
            await engine.dispose()
            return indexes, constraints

        indexes, constraints = asyncio.run(probe())
        due = next(index for index in indexes if index["name"] == "idx_listing_action_due")
        self.assertEqual(due["column_names"], ["status", "available_at"])
        self.assertTrue(any(c["column_names"] == ["batch_id", "listing_id"] for c in constraints),
            "Exact batch/listing uniqueness must survive regardless of SQLite autoindex numbering")

    def test_schedule_columns_render_with_microsecond_precision_on_mysql(self):
        from sqlalchemy.schema import CreateTable
        from sqlalchemy.dialects import mysql
        from common.models.listing_action import ListingActionTarget
        ddl = str(CreateTable(ListingActionTarget.__table__).compile(dialect=mysql.dialect()))
        for column in ("scheduled_at", "available_at", "lease_expires_at",
                       "request_started_at", "finished_at"):
            self.assertIn(f"{column} DATETIME(6)", ddl,
                f"{column} 必须是 DATETIME(6)，否则最小间隔会被截断")

    def test_timestamp_columns_follow_the_house_default_convention(self):
        """模型生成 DDL 产出 DEFAULT (now())，仓库既有 141 处用 CURRENT_TIMESTAMP。"""
        from sqlalchemy.schema import CreateTable
        from sqlalchemy.dialects import mysql
        from common.models.listing_action import ListingActionTarget
        ddl = str(CreateTable(ListingActionTarget.__table__).compile(dialect=mysql.dialect()))
        self.assertIn("created_at DATETIME NOT NULL DEFAULT (now())", ddl)


class ListingActionSchemaTests(unittest.TestCase):
    def test_api_requires_confirmation_and_explicit_window(self):
        import ast
        from pathlib import Path
        from typing import Literal
        from uuid import UUID
        from pydantic import BaseModel, Field, ValidationError, field_validator
        source = Path(__file__).resolve().parents[1] / "backend-web/app/api/routes/internal_products.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in {"OfflineBatchRequest","OfflineRetryRequest","OfflineReconcileRequest"}]
        scope = {"__name__":__name__, "BaseModel":BaseModel,"Field":Field,"UUID":UUID,"Literal":Literal,"field_validator":field_validator}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),"exec"),scope)
        for name, field in [("OfflineBatchRequest","listing_ids"),("OfflineRetryRequest","target_ids")]:
            model = scope[name]
            valid = {field:[1],"request_id":"00000000-0000-4000-8000-000000000001","window_hours":1,"confirmed":True}
            self.assertEqual(model(**valid).window_hours,1)
            for mutation in [{"window_hours":2},{"confirmed":False},{field:[]}]:
                with self.assertRaises(ValidationError):
                    model(**{**valid,**mutation})
            for missing in ["window_hours","confirmed"]:
                with self.assertRaises(ValidationError):
                    model(**{k:v for k,v in valid.items() if k!=missing})

    def test_reconcile_api_requires_explicit_state_and_note(self):
        import ast
        from pathlib import Path
        from typing import Literal
        from uuid import UUID
        from pydantic import BaseModel, Field, ValidationError, field_validator
        source = Path(__file__).resolve().parents[1] / "backend-web/app/api/routes/internal_products.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "OfflineReconcileRequest"]
        scope = {"__name__":__name__, "BaseModel":BaseModel,"Field":Field,"UUID":UUID,"Literal":Literal,"field_validator":field_validator}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),"exec"),scope)
        model = scope["OfflineReconcileRequest"]
        self.assertEqual(model(platform_state="offline", note="已在下架列表确认", confirmed=True).platform_state, "offline")
        for mutation in [{"platform_state":"maybe"},{"platform_state":"failed"},{"note":""},
                         {"note":"   "},{"confirmed":False}]:
            with self.assertRaises(ValidationError):
                model(**{"platform_state":"offline","note":"核对依据","confirmed":True,**mutation})
        self.assertEqual(set(model.model_fields), {"platform_state","note","confirmed"})
    def test_relist_schema_is_explicit_and_requires_confirmation(self):
        from common.schemas.listing_action import (
            ListingActionBatchRequest,
            ListingActionReconcileRequest,
            ListingActionRetryRequest,
        )
        valid_batch = {
            "listing_ids": [1],
            "window_hours": 1,
            "request_id": "00000000-0000-4000-8000-000000000001",
            "confirmed": True,
        }
        self.assertEqual(ListingActionBatchRequest(**valid_batch).window_hours, 1)
        valid_retry = {
            "target_ids": [1],
            "window_hours": 3,
            "request_id": "00000000-0000-4000-8000-000000000002",
            "confirmed": True,
        }
        self.assertEqual(ListingActionRetryRequest(**valid_retry).window_hours, 3)
        self.assertEqual(
            ListingActionReconcileRequest(
                platform_state="active", note="已核对在售", confirmed=True
            ).platform_state,
            "active",
        )
        from pydantic import ValidationError
        for mutation in ({"confirmed": False}, {"window_hours": 2}, {"listing_ids": []}):
            with self.assertRaises(ValidationError):
                ListingActionBatchRequest(**{**valid_batch, **mutation})
