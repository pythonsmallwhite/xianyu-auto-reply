"""Durable operations on exact, explicitly linked platform listings."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from common.db.base_class import Base, TimestampMixin
from common.models.publish_batch import SCHEDULE_DATETIME

# Keep the operation persisted on each batch so recovery is never represented
# as a disguised publish or an implicit side effect of an offline task.
LISTING_ACTION_OPERATIONS = frozenset({"offline", "relist"})

class ListingActionBatch(TimestampMixin, Base):
    __tablename__ = "xy_listing_action_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    internal_product_id: Mapped[int] = mapped_column(BigInteger)
    operation: Mapped[str] = mapped_column(String(20))
    window_hours: Mapped[int] = mapped_column(Integer)
    deadline_at: Mapped[datetime] = mapped_column(SCHEDULE_DATETIME)

class ListingActionTarget(TimestampMixin, Base):
    __tablename__ = "xy_listing_action_targets"
    __table_args__ = (
        UniqueConstraint("batch_id", "listing_id", name="uk_listing_action_target"),
        Index("idx_listing_action_due", "status", "available_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(36), index=True)
    listing_id: Mapped[int] = mapped_column(BigInteger)
    expected_version: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[str] = mapped_column(String(80))
    item_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    scheduled_at: Mapped[datetime] = mapped_column(SCHEDULE_DATETIME)
    available_at: Mapped[datetime] = mapped_column(SCHEDULE_DATETIME)
    minimum_gap_seconds: Mapped[float] = mapped_column(Float)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    request_started_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    finished_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    message: Mapped[str | None] = mapped_column(String(1000))
    schedule_error: Mapped[str | None] = mapped_column(String(1000))
    retry_batch_id: Mapped[str | None] = mapped_column(String(36))
    reconciled_state: Mapped[str | None] = mapped_column(String(20))
    reconciled_note: Mapped[str | None] = mapped_column(String(500))
    reconciled_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    reconciled_conflict: Mapped[bool | None] = mapped_column(Boolean)

class ListingActionAttempt(TimestampMixin, Base):
    __tablename__ = "xy_listing_action_attempts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    target_id: Mapped[int] = mapped_column(BigInteger, index=True)
    lease_token: Mapped[str] = mapped_column(String(36), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    request_started_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    finished_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    message: Mapped[str | None] = mapped_column(String(1000))
