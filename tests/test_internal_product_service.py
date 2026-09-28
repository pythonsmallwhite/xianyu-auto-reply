"""Offline SQLite checks for explicit mapping and shared-stock accounting."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

try:
    import aiosqlite  # noqa: F401
    from sqlalchemy import BigInteger, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.ext.compiler import compiles
except ImportError:
    async_sessionmaker = None

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(async_sessionmaker is None, "SQLAlchemy and aiosqlite are required")
class InternalProductServiceTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # common.services/common.utils package initializers import live platform
        # dependencies. Load only the isolated service and its pure inventory rule.
        from common.db.base_class import Base
        from common.models.internal_product import (
            InternalProduct,
            InternalProductListing,
            InventoryOrderHold,
        )
        from common.models.product_material import ProductMaterial
        from common.models.publish_log import PublishLog
        from common.models.xy_account import XYAccount

        @compiles(BigInteger, "sqlite")
        def _bigint_sqlite(_type, _compiler, **_kwargs):
            return "INTEGER"

        originals = {
            name: sys.modules.get(name)
            for name in ("common.services", "common.utils")
        }
        try:
            for name in originals:
                package = types.ModuleType(name)
                package.__path__ = [str(ROOT / name.replace(".", "/"))]
                sys.modules[name] = package
            spec = importlib.util.spec_from_file_location(
                "_internal_product_service_under_test",
                ROOT / "common/services/internal_product_service.py",
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            for name, previous in originals.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous
        cls.Service = module.InternalProductService
        publish_log_spec = importlib.util.spec_from_file_location(
            "_publish_log_service_under_test",
            ROOT / "common/services/publish_log_service.py",
        )
        publish_log_module = importlib.util.module_from_spec(publish_log_spec)
        publish_log_spec.loader.exec_module(publish_log_module)
        cls.PublishLogService = publish_log_module.PublishLogService
        cls.InternalProductModule = module
        cls.Base = Base
        cls.InternalProduct = InternalProduct
        cls.InternalProductListing = InternalProductListing
        cls.InventoryOrderHold = InventoryOrderHold
        cls.ProductMaterial = ProductMaterial
        cls.PublishLog = PublishLog
        cls.XYAccount = XYAccount

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: self.Base.metadata.create_all(
                    sync_connection,
                    tables=[
                        self.InternalProduct.__table__,
                        self.InternalProductListing.__table__,
                        self.InventoryOrderHold.__table__,
                        self.ProductMaterial.__table__,
                        self.PublishLog.__table__,
                        self.XYAccount.__table__,
                    ],
                )
            )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.session = self.sessions()
        self.service = self.Service(self.session)

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    async def _seed_material_and_logs(self, count=5):
        material = self.ProductMaterial(
            id=10,
            user_id=1,
            title="Exact source material",
            description="description",
            price=10,
            is_deleted=False,
        )
        self.session.add(material)
        for number in range(1, count + 1):
            account_id = f"account-{number}"
            self.session.add(
                self.XYAccount(
                    id=number,
                    owner_id=1,
                    account_id=account_id,
                    cookie="test-only",
                    login_method="manual",
                )
            )
            self.session.add(
                self.PublishLog(
                    id=number,
                    user_id=1,
                    account_id=account_id,
                    title="Same title is not the association key",
                    material_id=10,
                    status="success",
                    item_id=f"platform-item-{number}",
                )
            )
        await self.session.commit()

    async def test_same_material_maps_five_accounts_and_ignores_unconfirmed_log(self):
        await self._seed_material_and_logs()
        bindings = [
            await self.service.bind_successful_publish_log(1, log_id)
            for log_id in range(1, 6)
        ]
        self.assertEqual({binding.internal_product_id for binding in bindings}, {bindings[0].internal_product_id})
        snapshot = await self.service.snapshot(1, bindings[0].internal_product_id)
        self.assertIsNone(snapshot["total_stock"])
        self.assertEqual(len(snapshot["listings"]), 5)
        self.assertEqual(
            (await self.service.bind_successful_publish_log(1, 1)).id,
            bindings[0].id,
        )
        with self.assertRaises(ValueError):
            await self.service.bind_successful_publish_log(2, 1)
        self.session.add(
            self.PublishLog(
                id=99,
                user_id=1,
                account_id="account-1",
                title="Exact source material",
                material_id=10,
                status="unknown",
                item_id="historical-or-unknown",
            )
        )
        await self.session.commit()
        with self.assertRaises(ValueError):
            await self.service.bind_successful_publish_log(1, 99)

    async def test_three_orders_exhaust_five_listings_and_cancel_restores_two(self):
        await self._seed_material_and_logs()
        bindings = [
            await self.service.bind_successful_publish_log(1, log_id)
            for log_id in range(1, 6)
        ]
        product_id = bindings[0].internal_product_id
        await self.service.update_total_stock(1, product_id, 3)
        for number in range(1, 4):
            plan = await self.service.apply_order_event(
                1, f"account-{number}", f"platform-item-{number}",
                f"order-{number}", "placed",
            )
        self.assertEqual(plan["available"], 0)
        self.assertEqual(
            {action["listing_id"] for action in plan["actions"]},
            {bindings[3].id, bindings[4].id},
        )
        repeat = await self.service.apply_order_event(
            1, "account-1", "platform-item-1", "order-1", "paid",
        )
        self.assertEqual(repeat["occupied"], 3)
        for listing in bindings[3:]:
            self.assertTrue(
                await self.service.can_run_inventory_action(
                    1, listing.id, "offline", listing.state_version
                )
            )
            await self.service.confirm_inventory_action(
                1, listing.id, "offline", listing.state_version
            )
        restored = await self.service.apply_order_event(
            1, "account-3", "platform-item-3", "order-3", "cancelled",
        )
        self.assertEqual(restored["available"], 1)
        self.assertEqual(
            {action["listing_id"] for action in restored["actions"]},
            {bindings[3].id, bindings[4].id},
        )
        self.assertTrue(all(action["kind"] == "schedule_relist" for action in restored["actions"]))
        self.assertTrue(
            await self.service.can_run_inventory_action(
                1, bindings[3].id, "relist", bindings[3].state_version
            )
        )
        old_version = bindings[3].state_version
        await self.service.mark_manual_offline(1, "account-4", "platform-item-4")
        self.assertFalse(
            await self.service.can_run_inventory_action(
                1, bindings[3].id, "relist", old_version
            )
        )
        manual = await self.service.reconcile_plan(1, product_id)
        self.assertEqual(
            manual["actions"],
            [{"listing_id": bindings[4].id, "kind": "schedule_relist"}],
        )

    async def test_publish_log_success_binds_by_material_id(self):
        await self._seed_material_and_logs(1)
        log_service = self.PublishLogService(self.session)
        await log_service.update_log(1, "success", item_id="platform-item-1")
        product = (await self.session.execute(
            select(self.InternalProduct)
        )).scalar_one()
        listing = (await self.session.execute(
            select(self.InternalProductListing)
        )).scalar_one()
        self.assertEqual((product.material_id, listing.item_id), (10, "platform-item-1"))

    async def test_refund_hold_is_not_released_by_late_cancel_or_place(self):
        await self._seed_material_and_logs(1)
        binding = await self.service.bind_successful_publish_log(1, 1)
        await self.service.update_total_stock(1, binding.internal_product_id, 1)
        await self.service.apply_order_event(
            1, "account-1", "platform-item-1", "refund-order", "placed"
        )
        await self.service.apply_order_event(
            1, "account-1", "platform-item-1", "refund-order", "refunded"
        )
        await self.service.apply_order_event(
            1, "account-1", "platform-item-1", "refund-order", "cancelled"
        )
        await self.service.apply_order_event(
            1, "account-1", "platform-item-1", "refund-order", "placed"
        )
        snapshot = await self.service.snapshot(1, binding.internal_product_id)
        self.assertEqual((snapshot["occupied"], snapshot["available"]), (1, 0))

    async def test_cancellation_before_placement_is_terminal_and_history_is_ignored(self):
        await self._seed_material_and_logs(1)
        binding = await self.service.bind_successful_publish_log(1, 1)
        product_id = binding.internal_product_id
        self.assertIsNone(
            await self.service.apply_order_event(
                1, "account-1", "unlinked-item", "historical-order", "placed",
            )
        )
        await self.service.update_total_stock(1, product_id, 1)
        await self.service.apply_order_event(
            1, "account-1", "platform-item-1", "cancel-first", "cancelled",
        )
        later = await self.service.apply_order_event(
            1, "account-1", "platform-item-1", "cancel-first", "placed",
        )
        self.assertEqual(later["occupied"], 0)
        self.assertEqual(later["available"], 1)


if __name__ == "__main__":
    unittest.main()
