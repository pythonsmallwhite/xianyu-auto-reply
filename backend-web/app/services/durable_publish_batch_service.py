"""Database-backed publish jobs; uncertain platform requests are never replayed."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import timedelta
from typing import Any
from uuid import uuid4

from loguru import logger
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.session import async_session_maker
from common.models.publish_batch import PublishBatch, PublishBatchAccount, PublishBatchAttempt, PublishBatchTarget
from common.models.publish_log import PublishLog
from common.models.xy_account import XYAccount
from common.services.publish_capacity_service import settle_publish_capacity
from common.services.publish_execution_service import execute_single_publish
from common.utils.publish_outcome import classify_publish_result
from common.utils.time_utils import get_beijing_now_naive, safe_isoformat

LEASE_SECONDS = 120
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

    async def create_batch(self, *, owner_id: int, account_ids: list[str],
                           materials: list[dict[str, Any]], batch_id: str) -> PublishBatch:
        accounts = list(dict.fromkeys(account_ids))
        materials = list({int(item["id"]): dict(item) for item in materials}.values())
        if not accounts or not materials:
            raise ValueError("批量发布至少需要一个账号和一条素材")
        owned = set((await self.session.execute(select(XYAccount.account_id).where(
            XYAccount.owner_id == owner_id, XYAccount.account_id.in_(accounts),
        ))).scalars())
        if set(accounts) != owned:
            raise ValueError("包含不存在或无权使用的账号")
        batch = PublishBatch(id=batch_id, owner_id=owner_id, material_count=len(materials),
                             account_count=len(accounts), total_count=len(accounts) * len(materials))
        self.session.add(batch)
        self.session.add_all([
            PublishBatchAccount(batch_id=batch_id, owner_id=owner_id, account_id=account,
                                material_count=len(materials), sync_message="等待发布完成")
            for account in accounts
        ])
        self.session.add_all([
            PublishBatchTarget(batch_id=batch_id, owner_id=owner_id, account_id=account,
                               material_id=int(material["id"]), material_payload=material)
            for account in accounts for material in materials
        ])
        await self.session.commit()
        return batch

    @staticmethod
    async def find_next_batch() -> str | None:
        async with async_session_maker() as session:
            return (await session.execute(select(PublishBatchTarget.batch_id).where(
                PublishBatchTarget.status == "pending",
                or_(PublishBatchTarget.scheduled_at.is_(None),
                    PublishBatchTarget.scheduled_at <= get_beijing_now_naive()),
            ).order_by(PublishBatchTarget.id).limit(1))).scalar_one_or_none()

    @staticmethod
    async def _claim_next_target(batch_id: str) -> dict[str, Any] | None:
        async with async_session_maker() as session, session.begin():
            batch = (await session.execute(select(PublishBatch).where(
                PublishBatch.id == batch_id,
            ).with_for_update())).scalar_one_or_none()
            if batch is None:
                return None
            now = get_beijing_now_naive()
            target = (await session.execute(select(PublishBatchTarget).where(
                PublishBatchTarget.batch_id == batch_id,
                PublishBatchTarget.status == "pending",
                or_(PublishBatchTarget.scheduled_at.is_(None), PublishBatchTarget.scheduled_at <= now),
            ).order_by(PublishBatchTarget.scheduled_at, PublishBatchTarget.id).limit(1)
                .with_for_update())).scalar_one_or_none()
            if target is None:
                return None
            token = str(uuid4())
            claimed = await session.execute(update(PublishBatchTarget).where(
                PublishBatchTarget.id == target.id, PublishBatchTarget.status == "pending",
            ).values(status="publishing", lease_token=token,
                     lease_expires_at=now + timedelta(seconds=LEASE_SECONDS)),
                execution_options={"synchronize_session": False})
            if claimed.rowcount != 1:
                return None
            target.attempt_count += 1
            target.started_at, target.finished_at, target.error_message = now, None, None
            payload = dict(target.material_payload)
            # Log and attempt are committed together, before any platform request.
            log = PublishLog(user_id=target.owner_id, account_id=target.account_id,
                             batch_id=batch_id, material_id=target.material_id,
                             title=str(payload.get("title") or "")[:200],
                             description=payload.get("description"), price=str(payload.get("price") or ""),
                             publish_request_id=f"batch:{target.id}:{target.attempt_count}", status="pending")
            session.add(log)
            await session.flush()
            target.publish_log_id = log.id
            attempt = PublishBatchAttempt(batch_id=batch_id, target_id=target.id,
                                          attempt_no=target.attempt_count, publish_log_id=log.id,
                                          status="publishing", started_at=now)
            session.add(attempt)
            batch.status, batch.finished_at = "running", None
            batch.started_at = batch.started_at or now
            await session.flush()
            return {"target_id": target.id, "attempt_id": attempt.id, "token": token,
                    "owner_id": target.owner_id, "account_id": target.account_id,
                    "material_payload": payload, "log_id": log.id, "batch_id": batch_id}

    @staticmethod
    async def _renew(target: dict, *, start_request: bool = False) -> None:
        async with async_session_maker() as session, session.begin():
            now = get_beijing_now_naive()
            changed = await session.execute(update(PublishBatchTarget).where(
                PublishBatchTarget.id == target["target_id"],
                PublishBatchTarget.status == "publishing",
                PublishBatchTarget.lease_token == target["token"],
                PublishBatchTarget.lease_expires_at > now,
            ).values(lease_expires_at=now + timedelta(seconds=LEASE_SECONDS)))
            if changed.rowcount != 1:
                raise RuntimeError("发布执行权已失效，禁止继续发起请求")
            if start_request:
                changed = await session.execute(update(PublishLog).where(
                    PublishLog.id == target["log_id"], PublishLog.status == "pending",
                ).values(status="publishing"))
                if changed.rowcount != 1:
                    raise RuntimeError("发布尝试已经发起，禁止重复请求")

    @staticmethod
    async def _heartbeat(target: dict) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await DurablePublishBatchService._renew(target)

    @staticmethod
    async def run_batch(batch_id: str) -> None:
        # One target per turn lets other workers claim independently; no terminal batch scan.
        target = await DurablePublishBatchService._claim_next_target(batch_id)
        if target is None:
            return

        async def execute():
            from app.core.paths import STATIC_ROOT
            async with async_session_maker() as session:
                return await execute_single_publish(
                    session=session, user_id=target["owner_id"], account_id=target["account_id"],
                    item_data=target["material_payload"], static_root=STATIC_ROOT,
                    batch_id=batch_id, prepared_log_id=target["log_id"],
                    before_publish=lambda: DurablePublishBatchService._renew(target, start_request=True),
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
                await heartbeat  # Lease/database failure cancels the still-running platform coroutine.
            result = await execution
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("批量发布尝试中断: target_id={}", target["target_id"])
            result = None
        finally:
            execution.cancel()
            heartbeat.cancel()
            await asyncio.gather(execution, heartbeat, return_exceptions=True)
        # Outcome storage is outside the platform try/except: a local failure cannot overwrite success.
        await DurablePublishBatchService._finish_target(target, result)

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
                    log.status, log.error_message = "failed", "发布前执行中断，平台发布请求尚未发起"
                result = _log_result(log)
            # A persisted confirmed result wins over a later sync/local error.
            if log and log.status in {"success", "failed", "skipped"}:
                result = {**result, **_log_result(log)}
            status = _result_status(result)
            await DurablePublishBatchService._record_result(session, row, status, result)
            await DurablePublishBatchService._recompute_batch(session, batch)
        await DurablePublishBatchService._settle_capacity(target["log_id"], status, result)

    @staticmethod
    async def _record_result(session: AsyncSession, target: PublishBatchTarget,
                             status: str, result: dict) -> None:
        target.status, target.finished_at = status, get_beijing_now_naive()
        target.lease_token, target.lease_expires_at = None, None
        target.error_message = None if status == "success" else str(result.get("message") or "发布结果未知，请先对账")[:1000]
        attempt = (await session.execute(select(PublishBatchAttempt).where(
            PublishBatchAttempt.target_id == target.id,
            PublishBatchAttempt.attempt_no == target.attempt_count,
        ))).scalar_one()
        attempt.status, attempt.finished_at = status, target.finished_at
        attempt.item_id, attempt.error_message = result.get("item_id"), target.error_message
        log = await session.get(PublishLog, target.publish_log_id)
        if log and log.status in ACTIVE:
            log.status, log.error_message = status, target.error_message
            log.item_id = result.get("item_id") or log.item_id
            log.item_url = result.get("item_url") or log.item_url
        account = (await session.execute(select(PublishBatchAccount).where(
            PublishBatchAccount.batch_id == target.batch_id,
            PublishBatchAccount.account_id == target.account_id,
        ))).scalar_one()
        # Sync is a separate outcome. An early validation failure must also finish its progress.
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
            await settle_publish_capacity(log_id, "failed" if status == "skipped" else status,
                                          item_id=result.get("item_id"), error_message=result.get("message"))
        except Exception:
            # Keep the already confirmed platform outcome; the reservation remains available for reconciliation.
            logger.exception("批次容量结算待对账: log_id={}", log_id)

    @staticmethod
    async def recover_interrupted_targets() -> int:
        now = get_beijing_now_naive()
        async with async_session_maker() as session:
            confirmed_log = select(PublishLog.id).where(
                PublishLog.id == PublishBatchTarget.publish_log_id,
                PublishLog.status.in_({"success", "failed", "skipped"}),
            ).exists()
            candidates = (await session.execute(
                select(PublishBatchTarget.id, PublishBatchTarget.batch_id).where(or_(
                    and_(
                        PublishBatchTarget.status == "publishing",
                        or_(PublishBatchTarget.lease_expires_at.is_(None),
                            PublishBatchTarget.lease_expires_at <= now),
                    ),
                    and_(PublishBatchTarget.status == "unknown", confirmed_log),
                ))
            )).all()
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
                if target.lease_expires_at and target.lease_expires_at > get_beijing_now_naive():
                    continue
                log = await session.get(PublishLog, target.publish_log_id)
                if target.status == "unknown" and (log is None or log.status not in {"success", "failed", "skipped"}):
                    continue
                if log and log.status == "pending":
                    log.status, log.error_message = "failed", "服务中断，尚未发起平台发布请求，可手动重试"
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
        counts = dict((await session.execute(select(PublishBatchTarget.status, func.count()).where(
            PublishBatchTarget.batch_id == batch.id,
        ).group_by(PublishBatchTarget.status))).all())
        if counts.get("pending") or counts.get("publishing"):
            batch.status, batch.finished_at = "running", None
            return
        if counts.get("unknown"):
            batch.status = "unknown"
        elif counts.get("failed") or counts.get("skipped"):
            batch.status = "partial" if counts.get("success") else "failed"
        else:
            batch.status = "success"
        batch.finished_at = get_beijing_now_naive()

    async def retry_failed(self, owner_id: int, batch_id: str, target_ids: list[int]) -> int:
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
        for target in targets:
            target.status, target.finished_at, target.error_message = "pending", None, None
            target.publish_log_id, target.scheduled_at = None, None
        await self.session.execute(update(PublishBatchAccount).where(
            PublishBatchAccount.batch_id == batch_id,
            PublishBatchAccount.account_id.in_({t.account_id for t in targets}),
        ).values(sync_status="pending", sync_message="等待重试后同步商品",
                 sync_total_count=0, sync_saved_count=0))
        batch.status, batch.finished_at = "pending", None
        await self.session.commit()
        return len(targets)

    @staticmethod
    async def get_status(session: AsyncSession, owner_id: int, batch_id: str) -> dict | None:
        batch = (await session.execute(select(PublishBatch).where(
            PublishBatch.id == batch_id, PublishBatch.owner_id == owner_id,
        ))).scalar_one_or_none()
        if batch is None:
            return None
        rows = (await session.execute(select(PublishBatchTarget.account_id, PublishBatchTarget.status, func.count()).where(
            PublishBatchTarget.batch_id == batch_id,
        ).group_by(PublishBatchTarget.account_id, PublishBatchTarget.status))).all()
        counts = dict.fromkeys(ACTIVE | TERMINAL, 0)
        per_account: dict[str, dict] = {}
        for account_id, status, count in rows:
            counts[status] = counts.get(status, 0) + count
            per_account.setdefault(account_id, {})[status] = count
        accounts = (await session.execute(select(PublishBatchAccount).where(
            PublishBatchAccount.batch_id == batch_id,
        ).order_by(PublishBatchAccount.id))).scalars().all()
        statuses = []
        for account in accounts:
            status = {key: per_account.get(account.account_id, {}).get(key, 0) for key in ACTIVE | TERMINAL}
            statuses.append({"account_id": account.account_id, "total": sum(status.values()), **status,
                             "sync_status": account.sync_status, "sync_message": account.sync_message,
                             "sync_total_count": account.sync_total_count, "sync_saved_count": account.sync_saved_count})
        return {"batch_id": batch.id, "total": batch.total_count, **counts,
                "status": batch.status, "finished": not (counts["pending"] or counts["publishing"]),
                "snapshot_available": True, "account_statuses": statuses,
                "created_at": safe_isoformat(batch.created_at), "started_at": safe_isoformat(batch.started_at),
                "finished_at": safe_isoformat(batch.finished_at)}

    async def list_batches(self, owner_id: int, page: int, page_size: int) -> dict:
        cond = PublishBatch.owner_id == owner_id
        total = (await self.session.execute(select(func.count()).select_from(PublishBatch).where(cond))).scalar_one()
        ids = (await self.session.execute(select(PublishBatch.id).where(cond).order_by(
            PublishBatch.created_at.desc(), PublishBatch.id.desc(),
        ).offset((page - 1) * page_size).limit(page_size))).scalars().all()
        return {"list": [await self.get_status(self.session, owner_id, bid) for bid in ids],
                "total": total, "page": page, "page_size": page_size}

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
        ).order_by(PublishBatchAttempt.attempt_no))).scalars().all()
        history: dict[int, list] = {}
        for attempt in attempts:
            history.setdefault(attempt.target_id, []).append({
                "id": attempt.id, "attempt_no": attempt.attempt_no, "status": attempt.status,
                "publish_log_id": attempt.publish_log_id, "item_id": attempt.item_id,
                "error_message": attempt.error_message, "started_at": safe_isoformat(attempt.started_at),
                "finished_at": safe_isoformat(attempt.finished_at),
            })
        return {"list": [{
            "id": t.id, "account_id": t.account_id, "material_id": t.material_id,
            "title": t.material_payload.get("title", ""), "status": t.status,
            "publish_log_id": t.publish_log_id, "attempt_count": t.attempt_count,
            "scheduled_at": safe_isoformat(t.scheduled_at), "started_at": safe_isoformat(t.started_at),
            "finished_at": safe_isoformat(t.finished_at), "error_message": t.error_message,
            "attempts": history.get(t.id, []),
        } for t in targets], "total": batch.total_count, "page": page, "page_size": page_size}


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
