"""Durable per-internal-product coordination for batch publish requests."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from common.db.base_class import Base, TimestampMixin
from common.models.publish_batch import SCHEDULE_DATETIME


class PublishProductSchedule(TimestampMixin, Base):
    __tablename__ = "xy_publish_product_schedules"
    __table_args__ = (
        UniqueConstraint("owner_id", "internal_product_id", name="uk_publish_product_schedule"),
        Index("idx_publish_product_schedule_lease", "lease_expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    internal_product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_request_started_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_target_id: Mapped[int | None] = mapped_column(BigInteger)
    lease_expires_at: Mapped[datetime | None] = mapped_column(SCHEDULE_DATETIME)
