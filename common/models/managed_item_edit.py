"""Durable, owner-scoped batch seller edits."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Float, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from common.db.base_class import Base, TimestampMixin
from common.models.publish_batch import SCHEDULE_DATETIME


class ManagedItemEditBatch(TimestampMixin, Base):
    __tablename__ = "xy_managed_item_edit_batches"
    __table_args__ = (Index("idx_managed_item_edit_batch_owner", "owner_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    deadline_at: Mapped[datetime] = mapped_column(SCHEDULE_DATETIME, nullable=False)


class ManagedItemEditTarget(TimestampMixin, Base):
    __tablename__ = "xy_managed_item_edit_targets"
    __table_args__ = (
        UniqueConstraint("batch_id", "account_id", "item_id", name="uk_managed_item_edit_target"),
        Index("idx_managed_item_edit_due", "status", "available_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(80), nullable=False)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_updated_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    scheduled_at: Mapped[datetime] = mapped_column(SCHEDULE_DATETIME, nullable=False)
    available_at: Mapped[datetime] = mapped_column(SCHEDULE_DATETIME, nullable=False)
    minimum_gap_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    request_started_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    finished_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    message: Mapped[str | None] = mapped_column(String(1000))
    retry_batch_id: Mapped[str | None] = mapped_column(String(36))


class ManagedItemEditAttempt(TimestampMixin, Base):
    __tablename__ = "xy_managed_item_edit_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    lease_token: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    request_started_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    finished_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    message: Mapped[str | None] = mapped_column(String(1000))


__all__ = [
    "ManagedItemEditBatch",
    "ManagedItemEditTarget",
    "ManagedItemEditAttempt",
]
