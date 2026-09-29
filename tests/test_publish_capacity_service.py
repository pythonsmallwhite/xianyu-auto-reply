"""Isolated SQLite checks for the durable publish-capacity ledger."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import aiosqlite  # noqa: F401
    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from common.db.base_class import Base
    from common.models.publish_capacity_reservation import PublishCapacityReservation
    from common.models.publish_log import PublishLog
    from common.models.xy_account import XYAccount
except ModuleNotFoundError:
    select = None


if select is not None:
    session_stub = types.ModuleType('common.db.session')
    session_stub.async_session_maker = None
    old_session_module = sys.modules.get('common.db.session')
    sys.modules['common.db.session'] = session_stub
    try:
        service_path = Path(__file__).resolve().parents[1] / 'common/services/publish_capacity_service.py'
        spec = importlib.util.spec_from_file_location('publish_capacity_service_under_test', service_path)
        capacity_service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(capacity_service)
    finally:
        if old_session_module is None:
            sys.modules.pop('common.db.session', None)
        else:
            sys.modules['common.db.session'] = old_session_module


@unittest.skipIf(select is None, 'SQLAlchemy and aiosqlite are required for SQLite integration tests')
class PublishCapacityServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / 'capacity.sqlite'
        self.engine = create_async_engine(f'sqlite+aiosqlite:///{db_path.as_posix()}', connect_args={'timeout': 30})
        self.maker = async_sessionmaker(self.engine, expire_on_commit=False)
        capacity_service.async_session_maker = self.maker
        async with self.engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[XYAccount.__table__, PublishLog.__table__, PublishCapacityReservation.__table__],
            ))
        async with self.maker() as session:
            session.add(XYAccount(
                id=1, owner_id=7, account_id='acct', cookie='test-cookie', login_method='cookie',
                remaining_publish_capacity=2, reserved_publish_count=0,
            ))
            session.add_all([
                PublishLog(id=log_id, user_id=7, account_id='acct', title=f'item-{log_id}', status='publishing')
                for log_id in range(1, 5)
            ])
            await session.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def snapshot(self, log_id=None):
        async with self.maker() as session:
            account = (await session.execute(select(XYAccount).where(XYAccount.id == 1))).scalar_one()
            result = (account.remaining_publish_capacity, account.reserved_publish_count)
            if log_id is None:
                return result
            reservation = (await session.execute(select(PublishCapacityReservation).where(
                PublishCapacityReservation.publish_log_id == log_id
            ))).scalar_one_or_none()
            return result + ((reservation.status if reservation else None),)

    async def test_concurrent_claims_cannot_exceed_capacity(self):
        results = await asyncio.gather(*[
            capacity_service.reserve_publish_capacity(7, 'acct', log_id)
            for log_id in (1, 2, 3)
        ])
        self.assertEqual(results.count('reserved'), 2)
        self.assertEqual(results.count('exhausted'), 1)
        self.assertEqual(await self.snapshot(), (2, 2))

    async def test_success_failure_retry_and_idempotent_settlement(self):
        self.assertEqual(await capacity_service.reserve_publish_capacity(7, 'acct', 1), 'reserved')
        await capacity_service.settle_publish_capacity(1, 'failed', error_message='rejected')
        self.assertEqual(await self.snapshot(1), (2, 0, 'released'))
        self.assertEqual(await capacity_service.reserve_publish_capacity(7, 'acct', 1), 'reserved')
        await capacity_service.settle_publish_capacity(1, 'success', item_id='platform-1')
        await capacity_service.settle_publish_capacity(1, 'success', item_id='platform-1')
        self.assertEqual(await self.snapshot(1), (1, 0, 'succeeded'))
        with self.assertRaises(capacity_service.PublishCapacityError):
            await capacity_service.settle_publish_capacity(1, 'failed')

    async def test_unknown_holds_slot_until_manual_reconciliation(self):
        await capacity_service.reserve_publish_capacity(7, 'acct', 1)
        await capacity_service.settle_publish_capacity(1, 'unknown', error_message='timeout')
        self.assertEqual(await self.snapshot(1), (2, 1, 'unknown'))
        result = await capacity_service.resolve_unknown_publish_reservation(
            7, 'acct', await self.reservation_id(1), 'success', item_id='verified-item'
        )
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(await self.snapshot(1), (1, 0, 'succeeded'))
        async with self.maker() as session:
            log = (await session.execute(select(PublishLog).where(PublishLog.id == 1))).scalar_one()
            self.assertEqual((log.status, log.item_id), ('success', 'verified-item'))

    async def reservation_id(self, log_id):
        async with self.maker() as session:
            reservation = (await session.execute(select(PublishCapacityReservation).where(
                PublishCapacityReservation.publish_log_id == log_id
            ))).scalar_one()
            return reservation.id

    async def test_recent_unfinished_claim_cannot_be_reconciled_but_stale_one_can(self):
        await capacity_service.reserve_publish_capacity(7, 'acct', 1)
        reservation_id = await self.reservation_id(1)
        with self.assertRaises(capacity_service.PublishCapacityError):
            await capacity_service.resolve_unknown_publish_reservation(7, 'acct', reservation_id, 'failed')
        async with self.maker() as session:
            reservation = (await session.execute(select(PublishCapacityReservation).where(
                PublishCapacityReservation.id == reservation_id
            ))).scalar_one()
            reservation.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
            await session.commit()
        result = await capacity_service.resolve_unknown_publish_reservation(7, 'acct', reservation_id, 'failed')
        self.assertEqual(result['status'], 'released')
        self.assertEqual(await self.snapshot(1), (2, 0, 'released'))

    async def test_manual_failure_clears_unconfirmed_item_id(self):
        await capacity_service.reserve_publish_capacity(7, 'acct', 1)
        await capacity_service.settle_publish_capacity(1, 'unknown', item_id='unconfirmed')
        async with self.maker() as session:
            log = await session.get(PublishLog, 1)
            log.status, log.item_id, log.item_url = 'unknown', 'unconfirmed', 'https://example.invalid/item'
            await session.commit()
        await capacity_service.resolve_unknown_publish_reservation(
            7, 'acct', await self.reservation_id(1), 'failed'
        )
        async with self.maker() as session:
            log = await session.get(PublishLog, 1)
            self.assertEqual((log.status, log.item_id, log.item_url), ('failed', None, None))
        self.assertEqual(await self.snapshot(1), (2, 0, 'released'))

    async def test_unknown_reservation_survives_log_cleanup(self):
        await capacity_service.reserve_publish_capacity(7, 'acct', 1)
        await capacity_service.settle_publish_capacity(1, 'unknown')
        reservation_id = await self.reservation_id(1)
        async with self.maker() as session:
            await session.execute(delete(PublishLog).where(PublishLog.id == 1))
            await session.commit()
        result = await capacity_service.resolve_unknown_publish_reservation(
            7, 'acct', reservation_id, 'failed'
        )
        self.assertEqual(result['status'], 'released')
        self.assertEqual(await self.snapshot(1), (2, 0, 'released'))

    async def test_account_ownership_and_unconfigured_capacity(self):
        with self.assertRaises(capacity_service.PublishCapacityError):
            await capacity_service.reserve_publish_capacity(8, 'acct', 1)
        async with self.maker() as session:
            account = (await session.execute(select(XYAccount).where(XYAccount.id == 1))).scalar_one()
            account.remaining_publish_capacity = None
            await session.commit()
        self.assertEqual(await capacity_service.reserve_publish_capacity(7, 'acct', 1), 'unconfigured')
        self.assertEqual(await self.snapshot(1), (None, 0, None))


if __name__ == '__main__':
    unittest.main()
