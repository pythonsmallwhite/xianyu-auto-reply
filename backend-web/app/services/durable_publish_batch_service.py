"""Database-backed publish jobs; uncertain platform requests are never replayed."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from loguru import logger
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.session import async_session_maker
from common.models.publish_batch import (
    PublishBatch,
    PublishBatchAccount,
    PublishBatchAttempt,
    PublishBatchTarget,
)
from common.models.publish_batch_schedule import PublishProductSchedule
from common.models.publish_log import PublishLog
from common.models.xy_account import XYAccount
from common.services.internal_product_service import InternalProductService
from common.services.publish_capacity_service import settle_publish_capacity
from common.services.publish_execution_service import execute_single_publish
from common.utils.batch_schedule import (
    PublishScheduleDeferred,
    PublishWindowExpired,
    minimum_gap_seconds,
    next_allowed_start,
    plan_product_offsets,
    validate_window_hours,
)
from common.utils.publish_outcome import classify_publish_result
from common.utils.time_utils import get_beijing_now_naive, safe_isoformat

LEASE_SECONDS = 120
PRODUCT_LEASE_SECONDS = 90
HEARTBEAT_SECONDS = 20
ATTEMPT_TIMEOUT_SECONDS = 600
ACTIVE = {"pending", "publishing"}
TERMINAL = {"success", "failed", "unknown", "skipped"}


def _result_status(result: dict[str, Any]) -> str:
    """Keep explicit preflight failures retryable and platform contradictions unknown."""
    status = classify_publish_result(result, request_started=True)
    if status == "failed" and result.get("skipped"):
        return "skipped"
    return status


def _log_result(log: PublishLog | None) -> dict[str, Any]:
    if log is None:
        return {"unknown": True, "message": "尝试日志缺失，请先对账"}
    return {
        "success": log.status == "success",
        "unknown": log.status not in {"success", "failed", "skipped"},
        "skipped": log.status == "skipped",
        "item_id": log.item_id,
        "log_id": log.id,
        "message": log.error_message,
    }


class DurablePublishBatchService:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    async def _database_now(session: AsyncSession) -> datetime:
        """数据库 UTC 时钟统一换算为项目使用的北京时间，不依赖 worker 时钟。"""
        clock = func.utc_timestamp(6) if session.bind.dialect.name == "mysql" else func.now()
        value = (await session.execute(select(clock))).scalar_one()
        if not isinstance(value, datetime):
            value = datetime.fromisoformat(str(value))
        return value.replace(tzinfo=None) + timedelta(hours=8)

    @staticmethod
    async def _ensure_product_schedule(session: AsyncSession, owner_id: int, product_id: int) -> None:
        row = (await session.execute(select(PublishProductSchedule).where(
            PublishProductSchedule.owner_id == owner_id,
            PublishProductSchedule.internal_product_id == product_id,
        ).with_for_update())).scalar_one_or_none()
        if row is None:
            session.add(PublishProductSchedule(
                owner_id=owner_id,
                internal_product_id=product_id,
            ))
            await session.flush()

    @staticmethod
    def _schedule_groups(targets: list[PublishBatchTarget]) -> dict[int, list[PublishBatchTarget]]:
        groups: dict[int, list[PublishBatchTarget]] = {}
        for target in targets:
            if target.internal_product_id is None:
                raise ValueError("目标缺少内部商品，无法创建持久排程")
            groups.setdefault(target.internal_product_id, []).append(target)
        return groups

    @staticmethod
    def _apply_schedule(
        targets: list[PublishBatchTarget],
        *,
        window_hours: int,
        window_started_at: datetime,
        deadline_at: datetime,
    ) -> None:
        for group in DurablePublishBatchService._schedule_groups(targets).values():
            gap = minimum_gap_seconds(len(group), window_hours)
            offsets = plan_product_offsets(len(group), window_hours)
            for target, offset in zip(group, offsets):
                planned = window_started_at + timedelta(seconds=offset)
                target.window_hours = window_hours
                target.window_started_at = window_started_at
                target.deadline_at = deadline_at
                target.minimum_gap_seconds = gap
                target.scheduled_at = planned
                target.available_at = planned
                target.request_started_at = None
                target.schedule_error = None

    async def create_batch(
        self,
        *,
        owner_id: int,
        account_ids: list[str],
        materials: list[dict[str, Any]],
        batch_id: str,
        window_hours: int,
    ) -> PublishBatch:
        if type(window_hours) is not int:
            raise ValueError("请显式选择 1、3、5、12 或 24 小时窗口")
        validate_window_hours(window_hours)
        accounts = list(dict.fromkeys(account_ids))
        materials = list({int(item["id"]): dict(item) for item in materials}.values())
        if not accounts or not materials:
            raise ValueError("批量发布至少需要一个账号和一条素材")
        window_started_at = await self._database_now(self.session)
        deadline_at = window_started_at + timedelta(hours=window_hours)
        owned = set((await self.session.execute(select(XYAccount.account_id).where(
            XYAccount.owner_id == owner_id, XYAccount.account_id.in_(accounts),
        ))).scalars())
        if set(accounts) != owned:
            raise ValueError("包含不存在或无权使用的账号")

        product_service = InternalProductService(self.session)
        product_ids: dict[int, int] = {}
        for material in sorted(materials, key=lambda item: int(item["id"])):
            product = await product_service._product_for_material(owner_id, int(material["id"]))
            product_ids[int(material["id"])] = product.id
            await self._ensure_product_schedule(self.session, owner_id, product.id)

        batch = PublishBatch(
            id=batch_id,
            owner_id=owner_id,
            material_count=len(materials),
            account_count=len(accounts),
            total_count=len(accounts) * len(materials),
            window_hours=window_hours,
            window_started_at=window_started_at,
            deadline_at=deadline_at,
        )
        self.session.add(batch)
        self.session.add_all([
            PublishBatchAccount(
                batch_id=batch_id,
                owner_id=owner_id,
                account_id=account,
                material_count=len(materials),
                sync_message="等待发布完成",
            )
            for account in accounts
        ])
        targets = [
            PublishBatchTarget(
                batch_id=batch_id,
                owner_id=owner_id,
                account_id=account,
                material_id=int(material["id"]),
                internal_product_id=product_ids[int(material["id"])],
                material_payload=material,
            )
            for account in accounts
            for material in materials
        ]
        self.session.add_all(targets)
        await self.session.flush()
        self._apply_schedule(
            targets,
            window_hours=window_hours,
            window_started_at=window_started_at,
            deadline_at=deadline_at,
        )
        await self.session.commit()
        return batch

    @staticmethod
    async def find_next_batch() -> str | None:
        async with async_session_maker() as session:
            now = await DurablePublishBatchService._database_now(session)
            return (await session.execute(select(PublishBatchTarget.batch_id).where(
                PublishBatchTarget.status == "pending",
                or_(PublishBatchTarget.scheduled_at.is_(None), PublishBatchTarget.scheduled_at <= now),
                or_(
                    PublishBatchTarget.available_at.is_(None),
                    PublishBatchTarget.available_at <= now,
                ),
            ).order_by(PublishBatchTarget.available_at, PublishBatchTarget.id).limit(1))).scalar_one_or_none()

    @staticmethod
    async def _claim_next_target(batch_id: str) -> dict[str, Any] | None:
        async with async_session_maker() as session, session.begin():
            batch = (await session.execute(select(PublishBatch).where(
                PublishBatch.id == batch_id,
            ).with_for_update())).scalar_one_or_none()
            if batch is None:
                return None
            now = await DurablePublishBatchService._database_now(session)
            target = (await session.execute(select(PublishBatchTarget).where(
                PublishBatchTarget.batch_id == batch_id,
                PublishBatchTarget.status == "pending",
                or_(PublishBatchTarget.scheduled_at.is_(None), PublishBatchTarget.scheduled_at <= now),
                or_(
                    PublishBatchTarget.available_at.is_(None),
                    PublishBatchTarget.available_at <= now,
                ),
            ).order_by(PublishBatchTarget.available_at, PublishBatchTarget.id).limit(1)
                .with_for_update())).scalar_one_or_none()
            if target is None:
                return None
            if target.deadline_at is None or now > target.deadline_at:
                await DurablePublishBatchService._expire_target(session, target, now)
                await DurablePublishBatchService._recompute_batch(session, batch)
                return None

            token = str(uuid4())
            claimed = await session.execute(update(PublishBatchTarget).where(
                PublishBatchTarget.id == target.id,
                PublishBatchTarget.status == "pending",
            ).values(
                status="publishing",
                lease_token=token,
                lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
            ), execution_options={"synchronize_session": False})
            if claimed.rowcount != 1:
                return None
            target.attempt_count += 1
            target.started_at, target.finished_at = now, None
            target.error_message = None
            target.schedule_error = None
            target.request_started_at = None
            payload = dict(target.material_payload)
            log = PublishLog(
                user_id=target.owner_id,
                account_id=target.account_id,
                batch_id=batch_id,
                material_id=target.material_id,
                title=str(payload.get("title") or "")[:200],
                description=payload.get("description"),
                price=str(payload.get("price") or ""),
                publish_request_id=f"batch:{target.id}:{target.attempt_count}",
                status="pending",
            )
            session.add(log)
            await session.flush()
            target.publish_log_id = log.id
            attempt = PublishBatchAttempt(
                batch_id=batch_id,
                target_id=target.id,
                attempt_no=target.attempt_count,
                publish_log_id=log.id,
                status="publishing",
                started_at=now,
                window_hours=target.window_hours,
                window_started_at=target.window_started_at,
                scheduled_at=target.scheduled_at,
                deadline_at=target.deadline_at,
                minimum_gap_seconds=target.minimum_gap_seconds,
            )
            session.add(attempt)
            batch.status, batch.finished_at = "running", None
            batch.started_at = batch.started_at or now
            await session.flush()
            return {
                "target_id": target.id,
                "attempt_id": attempt.id,
                "token": token,
                "owner_id": target.owner_id,
                "account_id": target.account_id,
                "internal_product_id": target.internal_product_id,
                "material_payload": payload,
                "log_id": log.id,
                "batch_id": batch_id,
                "scheduled_at": target.scheduled_at,
                "deadline_at": target.deadline_at,
                "minimum_gap_seconds": target.minimum_gap_seconds,
            }

    @staticmethod
    async def _renew(target: dict, *, start_request: bool = False) -> None:
        async with async_session_maker() as session, session.begin():
            now = await DurablePublishBatchService._database_now(session)
            changed = await session.execute(update(PublishBatchTarget).where(
                PublishBatchTarget.id == target["target_id"],
                PublishBatchTarget.status == "publishing",
                PublishBatchTarget.lease_token == target["token"],
                PublishBatchTarget.lease_expires_at > now,
            ).values(lease_expires_at=now + timedelta(seconds=LEASE_SECONDS)))
            if changed.rowcount != 1:
                raise RuntimeError("发布执行权已失效，禁止继续发起请求")
            if target.get("product_lease_active"):
                product_changed = await session.execute(update(PublishProductSchedule).where(
                    PublishProductSchedule.lease_target_id == target["target_id"],
                    PublishProductSchedule.lease_token == target["token"],
                    PublishProductSchedule.lease_expires_at > now,
                ).values(lease_expires_at=now + timedelta(seconds=PRODUCT_LEASE_SECONDS)))
                if product_changed.rowcount != 1:
                    raise RuntimeError("商品发布执行权已失效，禁止继续发起请求")
            if start_request:
                changed = await session.execute(update(PublishLog).where(
                    PublishLog.id == target["log_id"], PublishLog.status == "pending",
                ).values(status="publishing"))
                if changed.rowcount != 1:
                    raise RuntimeError("发布尝试已经发起，禁止重复请求")

    @staticmethod
    @asynccontextmanager
    async def _request_guard(target: dict):
        product_token = target["token"]
        async with async_session_maker() as session, session.begin():
            target_row = (await session.execute(select(PublishBatchTarget).where(
                PublishBatchTarget.id == target["target_id"],
            ).with_for_update())).scalar_one_or_none()
            if target_row is None or target_row.status != "publishing" or target_row.lease_token != target["token"]:
                raise RuntimeError("发布执行权已失效，禁止继续发起请求")
            if target_row.request_started_at is not None:
                raise RuntimeError("发布尝试已经发起，禁止重复请求")
            deadline_at = target_row.deadline_at
            if deadline_at is None or target_row.internal_product_id is None:
                raise PublishWindowExpired("目标缺少显式排程窗口，请手动选择窗口重试")

            schedule = (await session.execute(select(PublishProductSchedule).where(
                PublishProductSchedule.owner_id == target_row.owner_id,
                PublishProductSchedule.internal_product_id == target_row.internal_product_id,
            ).with_for_update())).scalar_one_or_none()
            if schedule is None:
                raise RuntimeError("商品排程协调记录缺失，禁止发起请求")
            now = await DurablePublishBatchService._database_now(session)
            if target_row.lease_expires_at is None or target_row.lease_expires_at <= now:
                raise RuntimeError("发布执行权已失效，禁止继续发起请求")
            if now > deadline_at:
                raise PublishWindowExpired("目标已超过排程窗口，未发起平台请求")
            earliest = next_allowed_start(
                target_row.scheduled_at or now,
                schedule.last_request_started_at,
                timedelta(seconds=target_row.minimum_gap_seconds),
                deadline_at,
            )
            if earliest is None or earliest > deadline_at:
                raise PublishWindowExpired("延误后的最早请求时间已超过排程窗口")
            if schedule.lease_token and schedule.lease_expires_at and schedule.lease_expires_at > now:
                # lease 可能提前释放，轮询等待，不能把 lease 的保守上限当成必然超窗。
                earliest = max(earliest, min(schedule.lease_expires_at, now + timedelta(seconds=2)))
            if now < earliest:
                raise PublishScheduleDeferred(
                    retry_at=earliest,
                    message=f"发布排程尚未到可执行时间，最早可在 {earliest.isoformat()} 发起",
                )

            changed = await session.execute(update(PublishLog).where(
                PublishLog.id == target["log_id"], PublishLog.status == "pending",
            ).values(status="publishing"))
            if changed.rowcount != 1:
                raise RuntimeError("发布尝试已经发起，禁止重复请求")
            schedule.lease_token = product_token
            schedule.lease_target_id = target_row.id
            schedule.lease_expires_at = now + timedelta(seconds=PRODUCT_LEASE_SECONDS)
            schedule.last_request_started_at = now
            target_row.request_started_at = now
            attempt = (await session.execute(select(PublishBatchAttempt).where(
                PublishBatchAttempt.id == target["attempt_id"],
                PublishBatchAttempt.target_id == target_row.id,
            ).with_for_update())).scalar_one()
            attempt.request_started_at = now
            target["product_lease_active"] = True

        try:
            yield
        finally:
            # The product lease only protects the final request guard.  Post-request
            # sync work must not try to renew a lease that was already released.
            target["product_lease_active"] = False
            async with async_session_maker() as release_session, release_session.begin():
                schedule = (await release_session.execute(select(PublishProductSchedule).where(
                    PublishProductSchedule.owner_id == target["owner_id"],
                    PublishProductSchedule.internal_product_id == target["internal_product_id"],
                ).with_for_update())).scalar_one_or_none()
                if schedule and schedule.lease_token == product_token:
                    schedule.lease_token = None
                    schedule.lease_target_id = None
                    schedule.lease_expires_at = None

    @staticmethod
    async def _heartbeat(target: dict) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await DurablePublishBatchService._renew(target)

    @staticmethod
    async def run_batch(batch_id: str) -> None:
        target = await DurablePublishBatchService._claim_next_target(batch_id)
        if target is None:
            return

        async def execute():
            from app.core.paths import STATIC_ROOT
            async with async_session_maker() as session:
                return await execute_single_publish(
                    session=session,
                    user_id=target["owner_id"],
                    account_id=target["account_id"],
                    item_data=target["material_payload"],
                    static_root=STATIC_ROOT,
                    batch_id=batch_id,
                    prepared_log_id=target["log_id"],
                    request_guard=lambda: DurablePublishBatchService._request_guard(target),
                )

        execution = asyncio.create_task(execute())
        heartbeat = asyncio.create_task(DurablePublishBatchService._heartbeat(target))
        try:
            done, _ = await asyncio.wait(
                {execution, heartbeat}, return_when=asyncio.FIRST_COMPLETED,
                timeout=ATTEMPT_TIMEOUT_SECONDS,
            )
            if not done:
                raise TimeoutError("单项发布执行超时，请核对平台结果")
            if heartbeat in done:
                await heartbeat
            result = await execution
        except asyncio.CancelledError:
            raise
        except PublishScheduleDeferred as exc:
            await DurablePublishBatchService._defer_target(target, exc)
            return
        except PublishWindowExpired as exc:
            result = {
                "success": False,
                "message": str(exc),
                "schedule_error": str(exc),
            }
        except Exception:
            logger.exception("批量发布尝试中断: target_id={}", target["target_id"])
            result = None
        finally:
            execution.cancel()
            heartbeat.cancel()
            await asyncio.gather(execution, heartbeat, return_exceptions=True)
        await DurablePublishBatchService._finish_target(target, result)

    @staticmethod
    async def _defer_target(target: dict, error: PublishScheduleDeferred) -> None:
        # 释放成功才重新排队；结算失败时保留 publishing，由恢复流程安全收尾。
        await settle_publish_capacity(target["log_id"], "failed", error_message=str(error))
        async with async_session_maker() as session, session.begin():
            batch = (await session.execute(select(PublishBatch).where(
                PublishBatch.id == target["batch_id"],
            ).with_for_update())).scalar_one()
            row = (await session.execute(select(PublishBatchTarget).where(
                PublishBatchTarget.id == target["target_id"],
            ).with_for_update())).scalar_one_or_none()
            if row is None or row.status != "publishing" or row.lease_token != target["token"]:
                return
            now = await DurablePublishBatchService._database_now(session)
            retry_at = error.retry_at or now + timedelta(seconds=1)
            message = str(error)
            attempt = (await session.execute(select(PublishBatchAttempt).where(
                PublishBatchAttempt.id == target["attempt_id"],
            ).with_for_update())).scalar_one()
            row.status = "pending"
            row.lease_token = None
            row.lease_expires_at = None
            row.publish_log_id = None
            row.finished_at = None
            row.request_started_at = None
            row.available_at = retry_at
            row.schedule_error = message[:1000]
            row.error_message = None
            attempt.status = "deferred"
            attempt.finished_at = now
            attempt.schedule_error = message[:1000]
            attempt.error_message = message[:1000]
            log = await session.get(PublishLog, target["log_id"])
            if log and log.status in ACTIVE:
                log.status, log.error_message = "failed", message[:1000]
            if row.deadline_at and max(now, retry_at) > row.deadline_at:
                row.status, row.finished_at = "failed", now
                row.schedule_error = "延误后的最早请求时间已超过排程窗口"
                row.error_message = row.schedule_error
                attempt.status = "failed"
                attempt.schedule_error = row.schedule_error
                attempt.error_message = row.error_message
            await DurablePublishBatchService._recompute_batch(session, batch)

    @staticmethod
    async def _finish_target(target: dict, result: dict | None) -> None:
        async with async_session_maker() as session, session.begin():
            batch = (await session.execute(select(PublishBatch).where(
                PublishBatch.id == target["batch_id"],
            ).with_for_update())).scalar_one()
            row = (await session.execute(select(PublishBatchTarget).where(
                PublishBatchTarget.id == target["target_id"],
            ).with_for_update())).scalar_one()
            if row.status != "publishing" or row.lease_token != target["token"]:
                return
            log = await session.get(PublishLog, row.publish_log_id)
            if result is None:
                if log and log.status == "pending":
                    log.status = "unknown" if row.request_started_at else "failed"
                    log.error_message = "发布请求可能已提交，请先对账" if row.request_started_at else "发布前执行中断，平台发布请求尚未发起"
                result = _log_result(log)
            if log and log.status in {"success", "failed", "skipped"}:
                result = {**result, **_log_result(log)}
            status = _result_status(result)
            await DurablePublishBatchService._record_result(session, row, status, result)
            await DurablePublishBatchService._recompute_batch(session, batch)
        await DurablePublishBatchService._settle_capacity(target["log_id"], status, result)

    @staticmethod
    async def _record_result(session: AsyncSession, target: PublishBatchTarget,
                             status: str, result: dict) -> None:
        target.status, target.finished_at = status, await DurablePublishBatchService._database_now(session)
        target.lease_token, target.lease_expires_at = None, None
        target.schedule_error = str(result.get("schedule_error") or "")[:1000] or None
        if (target.request_started_at is not None and target.deadline_at is not None
                and target.finished_at > target.deadline_at):
            # 超窗是排程异常，不把平台已确认成功改成可重试失败。
            late = "请求已发起，但结果收尾超过排程窗口；保留实际平台结果"
            target.schedule_error = f"{target.schedule_error}；{late}"[:1000] if target.schedule_error else late
        target.error_message = None if status == "success" else str(
            result.get("message") or "发布结果未知，请先对账"
        )[:1000]
        attempt = (await session.execute(select(PublishBatchAttempt).where(
            PublishBatchAttempt.target_id == target.id,
            PublishBatchAttempt.attempt_no == target.attempt_count,
        ))).scalar_one()
        attempt.status, attempt.finished_at = status, target.finished_at
        attempt.item_id, attempt.error_message = result.get("item_id"), target.error_message
        attempt.request_started_at = target.request_started_at
        attempt.schedule_error = target.schedule_error
        log = await session.get(PublishLog, target.publish_log_id)
        if log and log.status in ACTIVE:
            log.status, log.error_message = status, target.error_message
            log.item_id = result.get("item_id") or log.item_id
            log.item_url = result.get("item_url") or log.item_url
        account = (await session.execute(select(PublishBatchAccount).where(
            PublishBatchAccount.batch_id == target.batch_id,
            PublishBatchAccount.account_id == target.account_id,
        ))).scalar_one()
        sync = result.get("sync_status")
        if sync in TERMINAL:
            account.sync_status = sync
            account.sync_message = str(result.get("sync_message") or "商品同步已结束")[:1000]
            account.sync_total_count = int(result.get("sync_total_count") or 0)
            account.sync_saved_count = int(result.get("sync_saved_count") or 0)
        elif status in {"success", "unknown"}:
            account.sync_status, account.sync_message = "unknown", "自动获取商品未确认，请手动同步"
        elif account.sync_status == "pending":
            account.sync_status, account.sync_message = "skipped", "发布未成功，未触发自动获取商品"
        await session.flush()

    @staticmethod
    async def _settle_capacity(log_id: int, status: str, result: dict) -> None:
        try:
            await settle_publish_capacity(
                log_id,
                "failed" if status == "skipped" else status,
                item_id=result.get("item_id"),
                error_message=result.get("message"),
            )
        except Exception:
            logger.exception("批次容量结算待对账: log_id={}", log_id)

    @staticmethod
    async def expire_pending_targets() -> int:
        async with async_session_maker() as session, session.begin():
            now = await DurablePublishBatchService._database_now(session)
            await session.execute(update(PublishProductSchedule).where(
                PublishProductSchedule.lease_expires_at.is_not(None),
                PublishProductSchedule.lease_expires_at <= now,
            ).values(lease_token=None, lease_target_id=None, lease_expires_at=None))
            batch_ids = (await session.scalars(select(PublishBatchTarget.batch_id).where(
                PublishBatchTarget.status == "pending",
                or_(PublishBatchTarget.deadline_at < now, PublishBatchTarget.deadline_at.is_(None)),
            ).distinct())).all()
        expired = 0
        for batch_id in batch_ids:
            async with async_session_maker() as session, session.begin():
                batch = (await session.execute(select(PublishBatch).where(
                    PublishBatch.id == batch_id,
                ).with_for_update())).scalar_one()
                now = await DurablePublishBatchService._database_now(session)
                rows = (await session.scalars(select(PublishBatchTarget).where(
                    PublishBatchTarget.batch_id == batch_id,
                    PublishBatchTarget.status == "pending",
                    or_(PublishBatchTarget.deadline_at < now, PublishBatchTarget.deadline_at.is_(None)),
                ).with_for_update())).all()
                for target in rows:
                    await DurablePublishBatchService._expire_target(session, target, now)
                await DurablePublishBatchService._recompute_batch(session, batch)
                expired += len(rows)
        return expired

    @staticmethod
    async def _expire_target(session: AsyncSession, target: PublishBatchTarget, now: datetime) -> None:
        message = "发布目标超过排程窗口，未发起平台请求" if target.deadline_at else "目标缺少显式排程窗口，请手动选择窗口重试"
        target.status, target.finished_at = "failed", now
        target.schedule_error = target.error_message = message
        target.attempt_count += 1
        session.add(PublishBatchAttempt(
            batch_id=target.batch_id, target_id=target.id, attempt_no=target.attempt_count,
            status="failed", started_at=now, finished_at=now,
            window_hours=target.window_hours, window_started_at=target.window_started_at,
            scheduled_at=target.scheduled_at, deadline_at=target.deadline_at,
            minimum_gap_seconds=target.minimum_gap_seconds,
            schedule_error=message, error_message=message,
        ))
        await session.execute(update(PublishBatchAccount).where(
            PublishBatchAccount.batch_id == target.batch_id,
            PublishBatchAccount.account_id == target.account_id,
            PublishBatchAccount.sync_status == "pending",
        ).values(sync_status="skipped", sync_message="排程窗口未完成，未触发商品同步"))

    @staticmethod
    async def recover_interrupted_targets() -> int:
        await DurablePublishBatchService.expire_pending_targets()
        async with async_session_maker() as session:
            now = await DurablePublishBatchService._database_now(session)
            confirmed_log = select(PublishLog.id).where(
                PublishLog.id == PublishBatchTarget.publish_log_id,
                PublishLog.status.in_({"success", "failed", "skipped"}),
            ).exists()
            candidates = (await session.execute(select(
                PublishBatchTarget.id, PublishBatchTarget.batch_id,
            ).where(or_(
                and_(
                    PublishBatchTarget.status == "publishing",
                    or_(PublishBatchTarget.lease_expires_at.is_(None),
                        PublishBatchTarget.lease_expires_at <= now),
                ),
                and_(PublishBatchTarget.status == "unknown", confirmed_log),
            )))).all()
        recovered = 0
        for target_id, batch_id in candidates:
            async with async_session_maker() as session, session.begin():
                batch = (await session.execute(select(PublishBatch).where(
                    PublishBatch.id == batch_id,
                ).with_for_update())).scalar_one()
                target = (await session.execute(select(PublishBatchTarget).where(
                    PublishBatchTarget.id == target_id,
                ).with_for_update())).scalar_one()
                if target.status not in {"publishing", "unknown"}:
                    continue
                now = await DurablePublishBatchService._database_now(session)
                if target.lease_expires_at and target.lease_expires_at > now:
                    continue
                log = await session.get(PublishLog, target.publish_log_id)
                if target.status == "unknown" and (log is None or log.status not in {"success", "failed", "skipped"}):
                    continue
                if log and log.status == "pending":
                    log.status = "unknown" if target.request_started_at else "failed"
                    log.error_message = "发布请求可能已提交，请先对账" if target.request_started_at else "服务中断，尚未发起平台发布请求，可手动重试"
                result = _log_result(log)
                status = _result_status(result)
                if status == "unknown":
                    result["message"] = "发布请求可能已提交，结果未知，请先对账"
                await DurablePublishBatchService._record_result(session, target, status, result)
                await DurablePublishBatchService._recompute_batch(session, batch)
                log_id = target.publish_log_id
            if log_id:
                await DurablePublishBatchService._settle_capacity(log_id, status, result)
            recovered += 1
        return recovered

    @staticmethod
    async def _recompute_batch(session: AsyncSession, batch: PublishBatch) -> None:
        counts = dict((await session.execute(select(
            PublishBatchTarget.status, func.count(),
        ).where(PublishBatchTarget.batch_id == batch.id).group_by(PublishBatchTarget.status))).all())
        if counts.get("pending") or counts.get("publishing"):
            batch.status, batch.finished_at = "running", None
            return
        if counts.get("unknown"):
            batch.status = "unknown"
        elif counts.get("failed") or counts.get("skipped"):
            batch.status = "partial" if counts.get("success") else "failed"
        else:
            batch.status = "success"
        timed_out = (await session.execute(select(func.count()).where(
            PublishBatchTarget.batch_id == batch.id,
            or_(PublishBatchTarget.schedule_error.contains("窗口"),
                PublishBatchTarget.schedule_error.contains("超时")),
        ))).scalar_one()
        batch.error_message = (
            f"存在排程窗口或超时异常的目标：{timed_out} 个，请查看各项实际结果" if timed_out else None
        )
        batch.finished_at = get_beijing_now_naive()

    async def retry_failed(
        self,
        owner_id: int,
        batch_id: str,
        target_ids: list[int],
        window_hours: int,
    ) -> int:
        if type(window_hours) is not int:
            raise ValueError("请显式选择 1、3、5、12 或 24 小时窗口")
        validate_window_hours(window_hours)
        window_started_at = await self._database_now(self.session)
        deadline_at = window_started_at + timedelta(hours=window_hours)
        batch = (await self.session.execute(select(PublishBatch).where(
            PublishBatch.id == batch_id, PublishBatch.owner_id == owner_id,
        ).with_for_update())).scalar_one_or_none()
        if batch is None:
            raise ValueError("批量任务不存在或无权访问")
        active = (await self.session.execute(select(func.count()).select_from(PublishBatchTarget).where(
            PublishBatchTarget.batch_id == batch_id, PublishBatchTarget.status.in_(ACTIVE),
        ))).scalar_one()
        if active:
            raise ValueError("请等待当前批次结束后再重试失败项")
        ids = set(target_ids)
        if not ids:
            raise ValueError("请明确选择需要重试的失败项")
        targets = (await self.session.execute(select(PublishBatchTarget).where(
            PublishBatchTarget.batch_id == batch_id, PublishBatchTarget.id.in_(ids),
        ).with_for_update())).scalars().all()
        if len(targets) != len(ids) or any(t.status != "failed" for t in targets):
            raise ValueError("只能重试本批次明确失败的项目，成功、未知和跳过项不可重试")
        product_service = InternalProductService(self.session)
        for target in targets:
            if target.internal_product_id is None:
                target.internal_product_id = (
                    await product_service._product_for_material(owner_id, target.material_id)
                ).id
            await self._ensure_product_schedule(self.session, owner_id, target.internal_product_id)
            target.status = "pending"
            target.finished_at = None
            target.error_message = None
            target.schedule_error = None
            target.request_started_at = None
            target.publish_log_id = None
        self._apply_schedule(
            targets,
            window_hours=window_hours,
            window_started_at=window_started_at,
            deadline_at=deadline_at,
        )
        batch.window_hours = window_hours
        batch.window_started_at = window_started_at
        batch.deadline_at = deadline_at
        await self.session.execute(update(PublishBatchAccount).where(
            PublishBatchAccount.batch_id == batch_id,
            PublishBatchAccount.account_id.in_({t.account_id for t in targets}),
        ).values(
            sync_status="pending",
            sync_message="等待重试后同步商品",
            sync_total_count=0,
            sync_saved_count=0,
        ))
        batch.status, batch.finished_at, batch.error_message = "pending", None, None
        await self.session.commit()
        return len(targets)

    @staticmethod
    async def get_status(session: AsyncSession, owner_id: int, batch_id: str) -> dict | None:
        batch = (await session.execute(select(PublishBatch).where(
            PublishBatch.id == batch_id, PublishBatch.owner_id == owner_id,
        ))).scalar_one_or_none()
        if batch is None:
            return None
        rows = (await session.execute(select(
            PublishBatchTarget.account_id, PublishBatchTarget.status, func.count(),
        ).where(PublishBatchTarget.batch_id == batch_id).group_by(
            PublishBatchTarget.account_id, PublishBatchTarget.status,
        ))).all()
        counts = dict.fromkeys(ACTIVE | TERMINAL, 0)
        per_account: dict[str, dict] = {}
        for account_id, status, count in rows:
            counts[status] = counts.get(status, 0) + count
            per_account.setdefault(account_id, {})[status] = count
        targets = (await session.execute(select(PublishBatchTarget).where(
            PublishBatchTarget.batch_id == batch_id,
        ))).scalars().all()
        timed_out = sum(1 for target in targets if target.schedule_error and (
            "窗口" in target.schedule_error or "超时" in target.schedule_error
        ))
        accounts = (await session.execute(select(PublishBatchAccount).where(
            PublishBatchAccount.batch_id == batch_id,
        ).order_by(PublishBatchAccount.id))).scalars().all()
        statuses = []
        for account in accounts:
            status = {key: per_account.get(account.account_id, {}).get(key, 0) for key in ACTIVE | TERMINAL}
            statuses.append({
                "account_id": account.account_id,
                "total": sum(status.values()),
                **status,
                "sync_status": account.sync_status,
                "sync_message": account.sync_message,
                "sync_total_count": account.sync_total_count,
                "sync_saved_count": account.sync_saved_count,
            })
        return {
            "batch_id": batch.id,
            "total": batch.total_count,
            **counts,
            "status": batch.status,
            "finished": not (counts["pending"] or counts["publishing"]),
            "timed_out": timed_out,
            "error_message": batch.error_message,
            "window_hours": batch.window_hours,
            "window_started_at": safe_isoformat(batch.window_started_at),
            "deadline_at": safe_isoformat(batch.deadline_at),
            "snapshot_available": True,
            "account_statuses": statuses,
            "created_at": safe_isoformat(batch.created_at),
            "started_at": safe_isoformat(batch.started_at),
            "finished_at": safe_isoformat(batch.finished_at),
        }

    async def list_batches(self, owner_id: int, page: int, page_size: int) -> dict:
        cond = PublishBatch.owner_id == owner_id
        total = (await self.session.execute(select(func.count()).select_from(PublishBatch).where(cond))).scalar_one()
        ids = (await self.session.execute(select(PublishBatch.id).where(cond).order_by(
            PublishBatch.created_at.desc(), PublishBatch.id.desc(),
        ).offset((page - 1) * page_size).limit(page_size))).scalars().all()
        return {
            "list": [await self.get_status(self.session, owner_id, bid) for bid in ids],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def list_targets(self, owner_id: int, batch_id: str, page: int, page_size: int) -> dict | None:
        batch = (await self.session.execute(select(PublishBatch).where(
            PublishBatch.id == batch_id, PublishBatch.owner_id == owner_id,
        ))).scalar_one_or_none()
        if batch is None:
            return None
        targets = (await self.session.execute(select(PublishBatchTarget).where(
            PublishBatchTarget.batch_id == batch_id,
        ).order_by(PublishBatchTarget.id).offset((page - 1) * page_size).limit(page_size))).scalars().all()
        attempts = (await self.session.execute(select(PublishBatchAttempt).where(
            PublishBatchAttempt.target_id.in_([t.id for t in targets]),
        ).order_by(PublishBatchAttempt.target_id, PublishBatchAttempt.attempt_no))).scalars().all()
        history: dict[int, list] = {}
        for attempt in attempts:
            history.setdefault(attempt.target_id, []).append({
                "id": attempt.id,
                "attempt_no": attempt.attempt_no,
                "status": attempt.status,
                "publish_log_id": attempt.publish_log_id,
                "item_id": attempt.item_id,
                "error_message": attempt.error_message,
                "window_hours": attempt.window_hours,
                "window_started_at": safe_isoformat(attempt.window_started_at),
                "scheduled_at": safe_isoformat(attempt.scheduled_at),
                "deadline_at": safe_isoformat(attempt.deadline_at),
                "minimum_gap_seconds": attempt.minimum_gap_seconds,
                "request_started_at": safe_isoformat(attempt.request_started_at),
                "schedule_error": attempt.schedule_error,
                "started_at": safe_isoformat(attempt.started_at),
                "finished_at": safe_isoformat(attempt.finished_at),
            })
        return {
            "list": [{
                "id": t.id,
                "account_id": t.account_id,
                "material_id": t.material_id,
                "internal_product_id": t.internal_product_id,
                "title": t.material_payload.get("title", ""),
                "status": t.status,
                "publish_log_id": t.publish_log_id,
                "attempt_count": t.attempt_count,
                "window_hours": t.window_hours,
                "window_started_at": safe_isoformat(t.window_started_at),
                "scheduled_at": safe_isoformat(t.scheduled_at),
                "deadline_at": safe_isoformat(t.deadline_at),
                "minimum_gap_seconds": t.minimum_gap_seconds,
                "available_at": safe_isoformat(t.available_at),
                "request_started_at": safe_isoformat(t.request_started_at),
                "schedule_error": t.schedule_error,
                "started_at": safe_isoformat(t.started_at),
                "finished_at": safe_isoformat(t.finished_at),
                "error_message": t.error_message,
                "attempts": history.get(t.id, []),
            } for t in targets],
            "total": batch.total_count,
            "page": page,
            "page_size": page_size,
        }


async def run_pending_batches_forever(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await DurablePublishBatchService.recover_interrupted_targets()
            batch_id = await DurablePublishBatchService.find_next_batch()
            if batch_id:
                await DurablePublishBatchService.run_batch(batch_id)
                continue
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("批量发布工作循环异常，稍后重新读取持久队列")
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=2)
