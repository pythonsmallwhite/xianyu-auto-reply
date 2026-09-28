"""Durable publish-capacity reservations, independent of deletable publish logs."""

from __future__ import annotations

from sqlalchemy import BigInteger, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from common.db.base_class import Base, TimestampMixin


class PublishCapacityReservation(TimestampMixin, Base):
    __tablename__ = "xy_publish_capacity_reservations"
    __table_args__ = (
        UniqueConstraint("publish_log_id", name="uk_publish_capacity_log"),
        Index("idx_publish_capacity_owner_account", "owner_id", "account_id"),
        Index("idx_publish_capacity_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_id: Mapped[str] = mapped_column(String(80), nullable=False)
    publish_log_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="reserved")
    item_id: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
