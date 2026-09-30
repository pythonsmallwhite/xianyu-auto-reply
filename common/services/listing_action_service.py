"""Durable manual offline batches, independent from new-item publication logs."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy import select, func
from common.db.session import async_session_maker
from common.models.internal_product import InternalProduct, InternalProductListing
from common.models.listing_action import ListingActionBatch as Batch, ListingActionTarget as Target, ListingActionAttempt as Attempt
from common.models.publish_batch_schedule import PublishProductSchedule as Schedule
from common.models.xy_account import XYAccount
from common.services.listing_action_platform import offline_listing
from common.utils.batch_schedule import plan_product_offsets, minimum_gap_seconds, validate_window_hours, next_allowed_start

class Deferred(Exception):
    def __init__(self, when):
        self.when = when

async def database_now(session):
    clock = func.utc_timestamp(6) if session.bind.dialect.name == "mysql" else func.now()
    value = (await session.execute(select(clock))).scalar_one()
    if not isinstance(value, datetime):
        value = datetime.fromisoformat(str(value))
    return value.replace(tzinfo=None) + timedelta(hours=8)

class ListingActionService:
    def __init__(self, session):
        self.session = session

    async def create(self, owner_id, product_id, listing_ids, window_hours, request_id, operation="offline"):
        validate_window_hours(window_hours)
        if operation != "offline":
            raise ValueError("恢复接口尚未核验，暂不能创建恢复任务")
        ids = sorted(set(listing_ids))
        if not ids or len(ids) > 200:
            raise ValueError("请选择 1 至 200 个关联商品")
        product = (await self.session.scalars(select(InternalProduct).where(
            InternalProduct.id == product_id, InternalProduct.owner_id == owner_id,
        ).with_for_update())).one_or_none()
        if product is None:
            raise ValueError("内部商品不存在或无权操作")
        old = await self.session.get(Batch, request_id)
        if old is not None:
            old_ids = sorted((await self.session.scalars(select(Target.listing_id).where(Target.batch_id == old.id))).all())
            if (old.owner_id, old.internal_product_id, old.operation, old.window_hours, old_ids) != (owner_id, product_id, operation, window_hours, ids):
                raise ValueError("请求 ID 已用于其他任务")
            return old.id
        unresolved = await self.session.scalar(select(Target.id).join(Batch, Batch.id == Target.batch_id).where(
            Batch.owner_id == owner_id, Target.listing_id.in_(ids),
            Target.status.in_(["pending", "running", "unknown"]),
        ).limit(1))
        if unresolved is not None:
            raise ValueError("所选商品已有待执行或未知任务，请先完成或核对原任务")
        listings = (await self.session.scalars(select(InternalProductListing).where(
            InternalProductListing.id.in_(ids), InternalProductListing.owner_id == owner_id,
            InternalProductListing.internal_product_id == product_id,
        ).order_by(InternalProductListing.id).with_for_update())).all()
        if len(listings) != len(ids):
            raise ValueError("只能选择本内部商品的明确关联项，历史商品不能加入")
        if len({r.account_id for r in listings}) != len(listings):
            raise ValueError("同一账号每批仅允许一个关联商品")
        if any(r.state != "active" for r in listings):
            raise ValueError("仅在售关联商品可以创建下架任务")
        accounts = set((await self.session.scalars(select(XYAccount.account_id).where(
            XYAccount.owner_id == owner_id, XYAccount.account_id.in_([r.account_id for r in listings]),
        ))).all())
        if accounts != {r.account_id for r in listings}:
            raise ValueError("账号不存在或归属已改变")
        schedule = (await self.session.scalars(select(Schedule).where(
            Schedule.owner_id == owner_id, Schedule.internal_product_id == product_id,
        ).with_for_update())).one_or_none()
        if schedule is None:
            self.session.add(Schedule(owner_id=owner_id, internal_product_id=product_id))
        now = await database_now(self.session)
        self.session.add(Batch(id=request_id, owner_id=owner_id, internal_product_id=product_id,
            operation=operation, window_hours=window_hours, deadline_at=now + timedelta(hours=window_hours)))
        offsets = plan_product_offsets(len(listings), window_hours)
        for row, offset in zip(listings, offsets):
            planned = now + timedelta(seconds=offset)
            self.session.add(Target(batch_id=request_id, listing_id=row.id,
                expected_version=row.state_version, account_id=row.account_id, item_id=row.item_id,
                scheduled_at=planned, available_at=planned,
                minimum_gap_seconds=minimum_gap_seconds(len(listings), window_hours)))
        await self.session.flush()
        return request_id

    async def detail(self, owner_id, batch_id):
        batch = await self.session.get(Batch, batch_id)
        if batch is None or batch.owner_id != owner_id:
            raise ValueError("任务不存在或无权访问")
        rows = (await self.session.scalars(select(Target).where(Target.batch_id == batch_id).order_by(Target.id))).all()
        attempts = (await self.session.scalars(select(Attempt).where(Attempt.target_id.in_([r.id for r in rows])).order_by(Attempt.id))).all()
        def serialize(row):
            return {c.name: (getattr(row, c.name).isoformat() if isinstance(getattr(row, c.name), datetime) else getattr(row, c.name))
                    for c in row.__table__.columns if c.name not in {"lease_token", "lease_expires_at"}}
        return {**serialize(batch), "finished": all(r.status not in {"pending", "running"} for r in rows),
                "targets": [serialize(r) for r in rows], "attempts": [serialize(a) for a in attempts]}

    async def reconcile(self, owner_id, batch_id, target_id, platform_state, note):
        """Record a human-confirmed platform outcome for an unknown target.

        Never infers the platform state, never rewrites unknown as failed, and
        never resends a request. Only an explicit human report is accepted.
        """
        if platform_state not in {"offline", "active"}:
            raise ValueError("必须明确选择平台实际状态：已下架或仍在售")
        note = (note or "").strip()
        if not note:
            raise ValueError("请填写核对依据")
        target = await self.session.get(Target, target_id, with_for_update=True)
        if target is None or target.batch_id != batch_id:
            raise ValueError("目标不存在或不属于该任务")
        batch = await self.session.get(Batch, batch_id)
        if batch is None or batch.owner_id != owner_id:
            raise ValueError("任务不存在或无权访问")
        account_id = await self.session.scalar(select(XYAccount.id).where(
            XYAccount.owner_id == owner_id, XYAccount.account_id == target.account_id))
        if account_id is None:
            raise ValueError("账号归属已改变，不能核对")
        if target.status == "reconciled":
            if target.reconciled_state != platform_state:
                raise ValueError(f"该目标已核对为{'已下架' if target.reconciled_state == 'offline' else '仍在售'}，不能改成相反结论")
            listing = await self.session.get(InternalProductListing, target.listing_id)
            return {"status": "reconciled",
                    "listing_state": listing.state if listing is not None else None,
                    # Older records predate the persisted conflict flag.
                    "conflict": target.reconciled_conflict if target.reconciled_conflict is not None else
                        target.message == "人工核对平台已下架，但本地状态已变更，请同步核对",
                    "message": target.message}
        if target.status != "unknown":
            raise ValueError("只有结果未知的目标需要人工核对")
        listing = await self.session.get(InternalProductListing, target.listing_id, with_for_update=True)
        conflict = False
        message = f"人工核对为{'已下架' if platform_state == 'offline' else '仍在售'}：{note}"
        if platform_state == "offline" and listing is not None:
            if (listing.owner_id, listing.internal_product_id, listing.account_id, listing.item_id) != (
                batch.owner_id, batch.internal_product_id, target.account_id, target.item_id):
                raise ValueError("商品关联已改变，不能按旧任务核对")
            if listing.state_version == target.expected_version:
                listing.state, listing.offline_reason, listing.pending_action = "offline", "manual", None
                listing.state_version += 1
            else:
                conflict = True
                message = "人工核对平台已下架，但本地状态已变更，请同步核对"
        target.status, target.reconciled_state, target.reconciled_note = "reconciled", platform_state, note[:500]
        target.reconciled_at, target.message = await database_now(self.session), message
        target.reconciled_conflict = conflict
        target.lease_token = target.lease_expires_at = None
        await self.session.flush()
        return {"status": "reconciled", "listing_state": listing.state if listing else None,
                "conflict": conflict, "message": message}

    async def retry(self, owner_id, batch_id, target_ids, window_hours, request_id):
        batch = (await self.session.scalars(select(Batch).where(Batch.id == batch_id, Batch.owner_id == owner_id).with_for_update())).one_or_none()
        if batch is None:
            raise ValueError("任务不存在或无权访问")
        if request_id == batch_id:
            raise ValueError("重试必须使用新的请求 ID")
        ids = set(target_ids)
        rows = (await self.session.scalars(select(Target).where(Target.batch_id == batch_id, Target.id.in_(ids)).with_for_update())).all()
        if not ids or len(rows) != len(ids) or any(r.status != "failed" for r in rows):
            raise ValueError("只能重试明确失败项，成功/未知/跳过项不可重发")
        if any(r.retry_batch_id for r in rows):
            if all(r.retry_batch_id == request_id for r in rows):
                return await self.create(owner_id, batch.internal_product_id, [r.listing_id for r in rows], window_hours, request_id)
            raise ValueError("这些失败项已创建重试任务，请查看新任务")
        result = await self.create(owner_id, batch.internal_product_id, [r.listing_id for r in rows], window_hours, request_id)
        for row in rows:
            row.retry_batch_id = result
        await self.session.flush()
        return result

async def claim():
    async with async_session_maker() as session, session.begin():
        now = await database_now(session)
        row = (await session.scalars(select(Target).where(Target.status == "pending", Target.available_at <= now)
            .order_by(Target.available_at, Target.id).limit(1).with_for_update(skip_locked=True))).first()
        if row is None:
            return None
        token = str(uuid4())
        row.status, row.lease_token, row.lease_expires_at = "running", token, now + timedelta(seconds=120)
        session.add(Attempt(target_id=row.id, lease_token=token))
        return row.id, token

@asynccontextmanager
async def request_guard(target_id, token):
    async with async_session_maker() as session, session.begin():
        row = await session.get(Target, target_id, with_for_update=True)
        now = await database_now(session)
        if row is None or row.status != "running" or row.lease_token != token or row.lease_expires_at <= now or row.request_started_at:
            raise ValueError("执行租约失效，禁止发送")
        batch = await session.get(Batch, row.batch_id)
        account_id = await session.scalar(select(XYAccount.id).where(
            XYAccount.owner_id == batch.owner_id, XYAccount.account_id == row.account_id))
        if account_id is None:
            raise ValueError("账号归属已改变，禁止发送")
        listing = await session.get(InternalProductListing, row.listing_id, with_for_update=True)
        if listing is None or (listing.owner_id, listing.internal_product_id, listing.account_id, listing.item_id, listing.state_version, listing.state) != (
            batch.owner_id, batch.internal_product_id, row.account_id, row.item_id, row.expected_version, "active"):
            raise ValueError("商品状态或关联已改变，禁止执行旧任务")
        schedule = (await session.scalars(select(Schedule).where(Schedule.owner_id == batch.owner_id,
            Schedule.internal_product_id == batch.internal_product_id).with_for_update())).one()
        earliest = next_allowed_start(row.scheduled_at, schedule.last_request_started_at,
            timedelta(seconds=row.minimum_gap_seconds), batch.deadline_at)
        if earliest is None or now > batch.deadline_at:
            raise ValueError("已超过排程窗口，未发送请求")
        if schedule.lease_token and schedule.lease_expires_at and schedule.lease_expires_at > now:
            earliest = max(earliest, schedule.lease_expires_at)
        if earliest > batch.deadline_at:
            raise ValueError("商品占用已超过排程窗口，未发送请求")
        if now < earliest:
            raise Deferred(earliest)
        schedule.lease_token, schedule.lease_expires_at = token, now + timedelta(seconds=120)
        schedule.last_request_started_at = row.request_started_at = now
        attempt = (await session.scalars(select(Attempt).where(Attempt.lease_token == token))).one()
        attempt.request_started_at = now
    yield

async def finish(target_id, token, status, message, retry_at=None):
    async with async_session_maker() as session, session.begin():
        row = await session.get(Target, target_id, with_for_update=True)
        if row is None or row.status != "running" or row.lease_token != token:
            return
        now = await database_now(session)
        batch = await session.get(Batch, row.batch_id)
        attempt = (await session.scalars(select(Attempt).where(Attempt.lease_token == token))).one()
        if status == "deferred" and row.request_started_at is None:
            row.status, row.available_at = "pending", retry_at
        else:
            row.status, row.finished_at = status, now
            if now > batch.deadline_at:
                row.schedule_error = "结果收尾超过排程窗口；保留实际结果"
            if status == "success":
                listing = await session.get(InternalProductListing, row.listing_id, with_for_update=True)
                if listing and listing.state_version == row.expected_version:
                    listing.state, listing.offline_reason, listing.pending_action = "offline", "manual", None
                    listing.state_version += 1
                else:
                    message = "平台已确认下架，但本地状态已变更，请同步核对"
        row.message = message[:1000]
        attempt.status, attempt.message, attempt.finished_at = status, row.message, now
        schedule = (await session.scalars(select(Schedule).where(Schedule.owner_id == batch.owner_id,
            Schedule.internal_product_id == batch.internal_product_id).with_for_update())).one_or_none()
        if schedule and schedule.lease_token == token:
            schedule.lease_token = schedule.lease_target_id = schedule.lease_expires_at = None
        row.lease_token = row.lease_expires_at = None

async def run_one():
    claimed = await claim()
    if claimed is None:
        return False
    target_id, token = claimed
    try:
        async with async_session_maker() as session:
            row = await session.get(Target, target_id)
            batch = await session.get(Batch, row.batch_id)
            account = (await session.scalars(select(XYAccount).where(XYAccount.owner_id == batch.owner_id,
                XYAccount.account_id == row.account_id))).one_or_none()
            if not account or not account.cookie:
                raise ValueError("账号不存在或未登录，未发送请求")
            result = await asyncio.wait_for(offline_listing(row.account_id, account.cookie, row.item_id,
                batch.owner_id, lambda: request_guard(target_id, token)), timeout=60)
        status = result.get("status", "unknown")
        if status not in {"success", "failed", "unknown"}:
            status = "unknown"
        await finish(target_id, token, status, result.get("message", "请核对平台结果"))
    except Deferred as exc:
        await finish(target_id, token, "deferred", "等待同商品请求间隔", exc.when)
    except Exception:
        async with async_session_maker() as session:
            row = await session.get(Target, target_id)
            started = row is not None and row.request_started_at is not None
        await finish(target_id, token, "unknown" if started else "failed",
            "请求已发起，结果未知，请核对平台" if started else "请求未发起：检查账号、商品状态或排程窗口")
    return True

async def recover():
    async with async_session_maker() as session:
        now = await database_now(session)
        rows = (await session.execute(select(Target.id, Target.lease_token, Target.request_started_at).where(
            Target.status == "running", Target.lease_expires_at < now))).all()
    for target_id, token, started in rows:
        await finish(target_id, token, "unknown" if started else "failed", "执行进程中断；已发起请求须核对，未发起可手动重试")

async def run_forever(stop):
    from loguru import logger
    while not stop.is_set():
        try:
            await recover()
            if await run_one():
                continue
        except Exception:
            logger.exception("持久商品操作执行器异常")
        try:
            await asyncio.wait_for(stop.wait(), timeout=3)
        except asyncio.TimeoutError:
            pass
