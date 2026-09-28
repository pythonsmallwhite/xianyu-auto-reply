"""User-managed stock shared by explicitly linked account listings."""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from common.db.base_class import Base, TimestampMixin


class InternalProduct(TimestampMixin, Base):
    __tablename__ = "xy_internal_products"
    __table_args__ = (
        Index("idx_internal_product_owner", "owner_id"),
        UniqueConstraint("owner_id", "material_id", name="uk_internal_product_material"),
        CheckConstraint("total_stock IS NULL OR total_stock >= 0", name="ck_internal_product_stock"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    material_id: Mapped[int | None] = mapped_column(BigInteger)
    total_stock: Mapped[int | None] = mapped_column(Integer)


class InternalProductListing(TimestampMixin, Base):
    """Only confirmed tool publications may enter this mapping."""

    __tablename__ = "xy_internal_product_listings"
    __table_args__ = (
        UniqueConstraint("owner_id", "account_id", "item_id", name="uk_internal_listing_platform"),
        UniqueConstraint("publish_log_id", name="uk_internal_listing_publish_log"),
        Index("idx_internal_listing_product", "internal_product_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    internal_product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_id: Mapped[str] = mapped_column(String(80), nullable=False)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    publish_log_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    offline_reason: Mapped[str | None] = mapped_column(String(20))
    pending_action: Mapped[str | None] = mapped_column(String(20))
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class InventoryOrderHold(TimestampMixin, Base):
    """One order occupies stock once; cancellation is terminal for that order key."""

    __tablename__ = "xy_inventory_order_holds"
    __table_args__ = (
        UniqueConstraint("owner_id", "account_id", "order_no", name="uk_inventory_order_account"),
        Index("idx_inventory_hold_product_status", "internal_product_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    internal_product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    listing_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_id: Mapped[str] = mapped_column(String(80), nullable=False)
    order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="reserved")
