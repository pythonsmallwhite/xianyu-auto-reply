"""Account publish-capacity reservations kept separately from deletable publish logs."""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select, update

from common.db.session import async_session_maker
from common.models.publish_capacity_reservation import PublishCapacityReservation
from common.models.xy_account import XYAccount


class PublishCapacityError(Exception):
    """The reservation cannot be safely created or settled."""


STALE_RESERVATION_AFTER = timedelta(hours=1)


async def reserve_publish_capacity(owner_id: int, account_id: str, publish_log_id: int) -> str:
    """Return reserved, unconfigured, or exhausted before any platform call.

    A guarded account update serializes concurrent batches and capacity edits.
    An unknown or unfinished reservation keeps its slot until explicit resolution.
    """
    async with async_session_maker() as session:
        async with session.begin():
            claimed = await session.execute(
                update(XYAccount).where(
                    XYAccount.owner_id == owner_id,
                    XYAccount.account_id == account_id,
                    XYAccount.remaining_publish_capacity.is_not(None),
                    XYAccount.remaining_publish_capacity > XYAccount.reserved_publish_count,
                ).values(reserved_publish_count=XYAccount.reserved_publish_count + 1)
            )
            if claimed.rowcount != 1:
                account = (await session.execute(
                    select(XYAccount).where(
                        XYAccount.owner_id == owner_id,
                        XYAccount.account_id == account_id,
                    )
                )).scalar_one_or_none()
                if account is None:
                    raise PublishCapacityError("账号不存在或无权使用")
                return "unconfigured" if account.remaining_publish_capacity is None else "exhausted"

            reservation = (await session.execute(
                select(PublishCapacityReservation).where(
                    PublishCapacityReservation.publish_log_id == publish_log_id
                ).with_for_update()
            )).scalar_one_or_none()
            if reservation is not None:
                if reservation.owner_id != owner_id or reservation.account_id != account_id:
                    raise PublishCapacityError("发布日志与容量预留账号不一致")
                if reservation.status != "released":
                    raise PublishCapacityError("发布请求已有未结算的容量预留，请先对账")
                reservation.status = "reserved"
                reservation.item_id = None
                reservation.error_message = None
            else:
                session.add(PublishCapacityReservation(
                    id=str(uuid.uuid4()),
                    owner_id=owner_id,
                    account_id=account_id,
                    publish_log_id=publish_log_id,
                    status="reserved",
                ))
    return "reserved"


async def settle_publish_capacity(
    publish_log_id: int,
    outcome: str,
    item_id: str | None = None,
    error_message: str | None = None,
) -> None:
    """Consume on success, release on explicit failure, retain on unknown."""
    if outcome not in {"success", "failed", "unknown"}:
        raise ValueError(f"unsupported publish outcome: {outcome}")
    async with async_session_maker() as session:
        async with session.begin():
            reservation = (await session.execute(
                select(PublishCapacityReservation).where(
                    PublishCapacityReservation.publish_log_id == publish_log_id
                )
            )).scalar_one_or_none()
            if reservation is None:
                return  # The account's capacity was not configured when published.
            account = (await session.execute(
                select(XYAccount).where(
                    XYAccount.owner_id == reservation.owner_id,
                    XYAccount.account_id == reservation.account_id,
                ).with_for_update()
            )).scalar_one_or_none()
            if account is None:
                raise PublishCapacityError("容量预留对应的账号不存在")
            reservation = (await session.execute(
                select(PublishCapacityReservation).where(
                    PublishCapacityReservation.id == reservation.id
                ).with_for_update()
            )).scalar_one()
            if reservation.status in {"succeeded", "released"}:
                if (reservation.status == "succeeded") != (outcome == "success"):
                    raise PublishCapacityError("容量预留已结算为另一结果")
                return
            if reservation.status not in {"reserved", "unknown"}:
                raise PublishCapacityError("容量预留状态不允许结算")
            if outcome == "unknown":
                reservation.status = "unknown"
            else:
                if account.reserved_publish_count < 1:
                    raise PublishCapacityError("账号预留数量异常，请人工核对")
                if outcome == "success":
                    if account.remaining_publish_capacity is None or account.remaining_publish_capacity < 1:
                        raise PublishCapacityError("账号剩余额度异常，请人工核对")
                    account.remaining_publish_capacity -= 1
                    reservation.status = "succeeded"
                else:
                    reservation.status = "released"
                account.reserved_publish_count -= 1
            reservation.item_id = item_id or reservation.item_id
            if error_message is not None:
                reservation.error_message = str(error_message)[:500] or None

async def list_open_publish_reservations(owner_id: int, account_id: str) -> list[dict]:
    """Show held slots even if their publish logs have been cleared."""
    from common.utils.time_utils import safe_isoformat

    async with async_session_maker() as session:
        rows = (await session.execute(
            select(PublishCapacityReservation)
            .where(
                PublishCapacityReservation.owner_id == owner_id,
                PublishCapacityReservation.account_id == account_id,
                PublishCapacityReservation.status.in_(("reserved", "unknown")),
            )
            .order_by(PublishCapacityReservation.created_at.desc())
        )).scalars().all()
        return [
            {
                "id": row.id,
                "publish_log_id": row.publish_log_id,
                "status": row.status,
                "item_id": row.item_id,
                "error_message": row.error_message,
                "created_at": safe_isoformat(row.created_at),
            }
            for row in rows
        ]


async def resolve_unknown_publish_reservation(
    owner_id: int,
    account_id: str,
    reservation_id: str,
    outcome: str,
    item_id: str | None = None,
) -> dict:
    """Record a verified result. Recent in-progress reservations stay protected."""
    if outcome not in {"success", "failed"}:
        raise ValueError("对账结果必须为 success 或 failed")
    from common.models.publish_log import PublishLog

    async with async_session_maker() as session:
        async with session.begin():
            account = (await session.execute(
                select(XYAccount).where(
                    XYAccount.owner_id == owner_id,
                    XYAccount.account_id == account_id,
                ).with_for_update()
            )).scalar_one_or_none()
            if account is None:
                raise PublishCapacityError("账号不存在或无权使用")
            reservation = (await session.execute(
                select(PublishCapacityReservation).where(
                    PublishCapacityReservation.id == reservation_id,
                    PublishCapacityReservation.owner_id == owner_id,
                    PublishCapacityReservation.account_id == account_id,
                ).with_for_update()
            )).scalar_one_or_none()
            if reservation is None:
                raise PublishCapacityError("容量预留记录不存在")
            if reservation.status == "reserved":
                created_at = reservation.created_at
                if created_at is None:
                    raise PublishCapacityError("预留时间缺失，请人工核对数据库")
                database_now = await session.scalar(select(func.now()))
                if database_now.replace(tzinfo=None) - created_at.replace(tzinfo=None) < STALE_RESERVATION_AFTER:
                    raise PublishCapacityError("发布仍可能进行中，请等待一小时后再对账")
            elif reservation.status != "unknown":
                raise PublishCapacityError("仅结果未知或超时未结算的发布可以人工对账")
            verified_item_id = (item_id or reservation.item_id or "").strip()
            if outcome == "success" and not verified_item_id:
                raise ValueError("确认发布成功时必须填写平台商品 ID")
            if account.reserved_publish_count < 1:
                raise PublishCapacityError("账号预留数量异常，请人工核对")
            if outcome == "success":
                if account.remaining_publish_capacity is None or account.remaining_publish_capacity < 1:
                    raise PublishCapacityError("账号剩余额度异常，请人工核对")
                account.remaining_publish_capacity -= 1
                reservation.status = "succeeded"
                reservation.item_id = verified_item_id
                reservation.error_message = None
            else:
                reservation.status = "released"
                reservation.error_message = "用户核对平台后确认未发布"
            account.reserved_publish_count -= 1
            log = (await session.execute(
                select(PublishLog).where(
                    PublishLog.id == reservation.publish_log_id,
                    PublishLog.user_id == owner_id,
                    PublishLog.account_id == account_id,
                ).with_for_update()
            )).scalar_one_or_none()
            if log is not None:
                log.status = outcome
                if outcome == "success":
                    log.item_id = verified_item_id
                    log.error_message = None
                else:
                    log.error_message = "用户核对平台后确认未发布"
            return {
                "id": reservation.id,
                "status": reservation.status,
                "item_id": reservation.item_id,
                "remaining_publish_capacity": account.remaining_publish_capacity,
                "reserved_publish_count": account.reserved_publish_count,
            }
