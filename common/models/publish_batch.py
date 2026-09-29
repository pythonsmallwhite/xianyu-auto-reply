"""Durable batch publish jobs and their per-target execution state."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import DATETIME

SCHEDULE_DATETIME = DateTime().with_variant(DATETIME(fsp=6), "mysql")

from common.db.base_class import Base, TimestampMixin


BATCH_STATUS_PENDING = "pending"
BATCH_STATUS_RUNNING = "running"
BATCH_STATUS_SUCCESS = "success"
BATCH_STATUS_PARTIAL = "partial"
BATCH_STATUS_FAILED = "failed"
BATCH_STATUS_UNKNOWN = "unknown"

TARGET_STATUS_PENDING = "pending"
TARGET_STATUS_PUBLISHING = "publishing"
TARGET_STATUS_SUCCESS = "success"
TARGET_STATUS_FAILED = "failed"
TARGET_STATUS_UNKNOWN = "unknown"
TARGET_STATUS_SKIPPED = "skipped"


class PublishBatch(TimestampMixin, Base):
    __tablename__ = "xy_publish_batches"
    __table_args__ = (
        Index("idx_publish_batch_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    material_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    account_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_hours: Mapped[int | None] = mapped_column(Integer)
    window_started_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    deadline_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=BATCH_STATUS_PENDING)
    error_message: Mapped[str | None] = mapped_column(String(1000))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class PublishBatchAccount(TimestampMixin, Base):
    __tablename__ = "xy_publish_batch_accounts"
    __table_args__ = (
        UniqueConstraint("batch_id", "account_id", name="uk_publish_batch_account"),
        Index("idx_publish_batch_account_batch", "batch_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_id: Mapped[str] = mapped_column(String(80), nullable=False)
    material_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sync_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    sync_message: Mapped[str | None] = mapped_column(String(1000))
    sync_total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sync_saved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PublishBatchTarget(TimestampMixin, Base):
    __tablename__ = "xy_publish_batch_targets"
    __table_args__ = (
        UniqueConstraint("batch_id", "account_id", "material_id", name="uk_publish_batch_target"),
        Index("idx_publish_batch_target_batch_status", "batch_id", "status"),
        Index("idx_publish_batch_target_claim", "status", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_id: Mapped[str] = mapped_column(String(80), nullable=False)
    material_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    internal_product_id: Mapped[int | None] = mapped_column(BigInteger)
    material_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    window_hours: Mapped[int | None] = mapped_column(Integer)
    window_started_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    deadline_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    minimum_gap_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    available_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    request_started_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    schedule_error: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TARGET_STATUS_PENDING)
    publish_log_id: Mapped[int | None] = mapped_column(BigInteger)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    scheduled_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(String(1000))


class PublishBatchAttempt(TimestampMixin, Base):
    __tablename__ = "xy_publish_batch_attempts"
    __table_args__ = (
        Index("idx_publish_batch_attempt_target", "target_id", "attempt_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TARGET_STATUS_PUBLISHING)
    publish_log_id: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    window_hours: Mapped[int | None] = mapped_column(Integer)
    window_started_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    scheduled_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    deadline_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    minimum_gap_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    request_started_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    schedule_error: Mapped[str | None] = mapped_column(String(1000))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    item_id: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(1000))
