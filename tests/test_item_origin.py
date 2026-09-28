"""Exact source classification: history is hidden even when titles match."""
from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime
from pathlib import Path

try:
    import aiosqlite  # noqa: F401
    from sqlalchemy import BigInteger, or_, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.ext.compiler import compiles
except ImportError:
    async_sessionmaker = None

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(async_sessionmaker is None, "SQLAlchemy and aiosqlite are required")
class ItemOriginTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        from common.db.base_class import Base
        from common.models.internal_product import InternalProductListing
        from common.models.publish_log import PublishLog
        from common.models.xy_account import XYAccount
        from common.models.xy_catalog_item import XYCatalogItem

        @compiles(BigInteger, "sqlite")
        def _bigint_sqlite(_type, _compiler, **_kwargs):
            return "INTEGER"

        spec = importlib.util.spec_from_file_location(
            "_item_origin_under_test", ROOT / "common/utils/item_origin.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.origin_predicates = staticmethod(module.origin_predicates)
        cls.origin_name = staticmethod(module.origin_name)
        cls.Base = Base
        cls.Account = XYAccount
        cls.Catalog = XYCatalogItem
        cls.PublishLog = PublishLog
        cls.Listing = InternalProductListing

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(lambda sync_connection: self.Base.metadata.create_all(
                sync_connection, tables=[
                    self.Account.__table__, self.Catalog.__table__,
                    self.PublishLog.__table__, self.Listing.__table__,
                ]
            ))
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_exact_ids_hide_history_and_similar_titles(self):
        async with self.sessions() as session:
            session.add(self.Account(
                id=1, owner_id=7, account_id="seller-a", cookie="offline-test",
                login_method="cookie", status="active",
            ))
            for number, item_id in enumerate(("managed", "tool", "history", "similar"), 1):
                session.add(self.Catalog(
                    id=number, owner_id=7, account_pk=1, item_id=item_id,
                    title="same title", created_at=datetime.utcnow(),
                ))
            session.add(self.PublishLog(
                id=10, user_id=7, account_id="seller-a", title="same title",
                item_id="tool", status="success",
            ))
            session.add(self.PublishLog(
                id=11, user_id=7, account_id="another-seller", title="same title",
                item_id="history", status="success",
            ))
            session.add(self.Listing(
                id=20, owner_id=7, internal_product_id=5,
                account_id="seller-a", item_id="managed", publish_log_id=12,
                state="active", state_version=0,
            ))
            await session.commit()

            managed, published = self.origin_predicates()
            base = select(self.Catalog.item_id, managed, published).outerjoin(
                self.Account, self.Catalog.account_pk == self.Account.id
            ).where(self.Catalog.owner_id == 7)
            rows = (await session.execute(base)).all()
            categories = {
                item_id: self.origin_name(bool(is_managed), bool(is_published))
                for item_id, is_managed, is_published in rows
            }
            self.assertEqual(categories, {
                "managed": "managed",
                "tool": "tool_published_unlinked",
                "history": "history_or_unknown",
                "similar": "history_or_unknown",
            })
            visible = set((await session.execute(
                base.where(or_(managed, published))
            )).scalars().all())
            self.assertEqual(visible, {"managed", "tool"})