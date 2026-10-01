"""Durable execution for seller item edits.

This service deliberately has its own tables and state machine.  It does not
reuse publication or offline targets because an edit must retain its immutable
payload snapshot and must never include history/unknown catalog rows.
"""
from __future__ import annotations

import copy
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.xianyu_item_edit_service import (
    edit_seller_item,
    fetch_seller_item_edit_detail,
)
from common.db.session import async_session_maker
from common.models.managed_item_edit import (
    ManagedItemEditAttempt,
    ManagedItemEditBatch,
    ManagedItemEditTarget,
)
from common.models.xy_account import XYAccount
from common.models.xy_catalog_item import XYCatalogItem
from common.services.xianyu_publish_service import detect_publish_account_capability
from common.utils.batch_schedule import (
    minimum_gap_seconds,
    next_allowed_start,
    plan_product_offsets,
    validate_window_hours,
)
from common.utils.item_origin import origin_predicates


TERMINAL_STATES = frozenset({"success", "failed", "unknown", "skipped"})
EDITABLE_ORIGIN = frozenset({"managed", "tool_published_unlinked"})


async def database_now(session: AsyncSession) -> datetime:
    clock = func.utc_timestamp(6) if session.bind.dialect.name == "mysql" else func.now()
    value = (await session.execute(select(clock))).scalar_one()
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) + timedelta(hours=8)
    return datetime.fromisoformat(str(value)).replace(tzinfo=None)


def _serialize(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {key: _serialize(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_serialize(value) for value in obj]
    return obj


def _result_state(result: dict[str, Any] | None) -> str:
    """Accept only an explicit operation state; never infer success from shape."""
    if not isinstance(result, dict):
        return "unknown"
    state = result.get("status")
    if state in TERMINAL_STATES:
        return state
    if result.get("_request_status_unknown"):
        return "unknown"
    if result.get("success") is True:
        return "success"
    if result.get("success") is False:
        return "failed"
    return "unknown"


class ManagedItemEditService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        owner_id: int,
        account_id: str,
        item_ids: list[str],
        window_hours: int,
        payload: dict[str, Any],
        request_id: str | None = None,
    ) -> str:
        validate_window_hours(window_hours)
        if not account_id or not account_id.strip():
            raise ValueError("必须指定账号")
        ids = list(dict.fromkeys(str(item_id).strip() for item_id in item_ids if str(item_id).strip()))
        if not ids or len(ids) > 200:
            raise ValueError("请选择 1 至 200 个商品")
        snapshot = copy.deepcopy(payload)
        if "images" in snapshot and snapshot["images"] == []:
            raise ValueError("商品图片不能为空；不修改图片时请省略 images")
        if "images" in snapshot and snapshot["images"] is not None and not isinstance(snapshot["images"], list):
            raise ValueError("images 必须是图片 URL 数组")

        batch_id = request_id or str(uuid4())
        existing = await self.session.get(ManagedItemEditBatch, batch_id)
        if existing is not None:
            old_targets = list(
                await self.session.scalars(
                    select(ManagedItemEditTarget)
                    .where(ManagedItemEditTarget.batch_id == batch_id)
                    .order_by(ManagedItemEditTarget.id)
                )
            )
            old_ids = [row.item_id for row in old_targets]
            if (
                existing.owner_id,
                existing.window_hours,
                existing.payload_snapshot,
                old_ids,
            ) != (owner_id, window_hours, snapshot, ids):
                raise ValueError("请求 ID 已用于其他编辑任务")
            return batch_id

        account = await self.session.scalar(
            select(XYAccount).where(
                XYAccount.owner_id == owner_id,
                XYAccount.account_id == account_id,
            )
        )
        if account is None:
            raise ValueError("账号不存在或无权操作")

        managed, tool_published = origin_predicates()
        rows = (
            await self.session.execute(
                select(XYCatalogItem, managed, tool_published)
                .where(
                    XYCatalogItem.owner_id == owner_id,
                    XYCatalogItem.account_pk == account.id,
                    XYCatalogItem.item_id.in_(ids),
                )
            )
        ).all()
        rows_by_id = {row.item_id: (row, bool(is_managed), bool(is_tool)) for row, is_managed, is_tool in rows}
        if set(rows_by_id) != set(ids):
            raise ValueError("所选商品不存在或账号归属已改变")
        if any(not (values[1] or values[2]) for values in rows_by_id.values()):
            raise ValueError("历史或来源待确认商品不能加入批量编辑")
        unresolved = await self.session.scalar(
            select(ManagedItemEditTarget.id)
            .join(ManagedItemEditBatch, ManagedItemEditBatch.id == ManagedItemEditTarget.batch_id)
            .where(
                ManagedItemEditBatch.owner_id == owner_id,
                ManagedItemEditTarget.account_id == account_id,
                ManagedItemEditTarget.item_id.in_(ids),
                ManagedItemEditTarget.status.in_(["pending", "running", "unknown"]),
            )
            .limit(1)
        )
        if unresolved is not None:
            raise ValueError("所选商品已有待执行或结果未知的编辑任务")

        now = await database_now(self.session)
        offsets = plan_product_offsets(len(ids), window_hours)
        gap = minimum_gap_seconds(len(ids), window_hours)
        self.session.add(
            ManagedItemEditBatch(
                id=batch_id,
                owner_id=owner_id,
                window_hours=window_hours,
                payload_snapshot=snapshot,
                status="pending",
                deadline_at=now + timedelta(hours=window_hours),
            )
        )
        for item_id, offset in zip(ids, offsets):
            item = rows_by_id[item_id][0]
            planned = now + timedelta(seconds=offset)
            self.session.add(
                ManagedItemEditTarget(
                    batch_id=batch_id,
                    account_id=account_id,
                    item_id=item_id,
                    expected_updated_at=item.updated_at,
                    status="pending",
                    scheduled_at=planned,
                    available_at=planned,
                    minimum_gap_seconds=gap,
                )
            )
        await self.session.flush()
        return batch_id

    async def detail(self, *, owner_id: int, batch_id: str) -> dict[str, Any]:
        batch = await self.session.get(ManagedItemEditBatch, batch_id)
        if batch is None or batch.owner_id != owner_id:
            raise ValueError("任务不存在或无权访问")
        targets = list(
            await self.session.scalars(
                select(ManagedItemEditTarget)
                .where(ManagedItemEditTarget.batch_id == batch_id)
                .order_by(ManagedItemEditTarget.id)
            )
        )
        attempts = list(
            await self.session.scalars(
                select(ManagedItemEditAttempt)
                .where(ManagedItemEditAttempt.target_id.in_([row.id for row in targets]))
                .order_by(ManagedItemEditAttempt.id)
            )
        ) if targets else []
        return {
            "batch_id": batch.id,
            "owner_id": batch.owner_id,
            "window_hours": batch.window_hours,
            "status": batch.status,
            "deadline_at": _serialize(batch.deadline_at),
            "payload_snapshot": copy.deepcopy(batch.payload_snapshot),
            "targets": [_serialize({column.name: getattr(row, column.name) for column in row.__table__.columns if column.name not in {"lease_token", "lease_expires_at"}}) for row in targets],
            "attempts": [_serialize({column.name: getattr(row, column.name) for column in row.__table__.columns}) for row in attempts],
        }

    async def retry(
        self,
        *,
        owner_id: int,
        batch_id: str,
        target_ids: list[int],
        window_hours: int,
        request_id: str,
    ) -> str:
        validate_window_hours(window_hours)
        if request_id == batch_id:
            raise ValueError("重试必须使用新的请求 ID")
        batch = await self.session.scalar(
            select(ManagedItemEditBatch)
            .where(ManagedItemEditBatch.id == batch_id, ManagedItemEditBatch.owner_id == owner_id)
            .with_for_update()
        )
        if batch is None:
            raise ValueError("任务不存在或无权访问")
        ids = set(target_ids)
        rows = list(
            await self.session.scalars(
                select(ManagedItemEditTarget)
                .where(ManagedItemEditTarget.batch_id == batch_id, ManagedItemEditTarget.id.in_(ids))
                .with_for_update()
            )
        )
        if not ids or len(rows) != len(ids) or any(row.status != "failed" for row in rows):
            raise ValueError("只能重试明确失败项，成功/未知/跳过项不可重发")
        if any(row.retry_batch_id for row in rows):
            if all(row.retry_batch_id == request_id for row in rows):
                return await self.create(
                    owner_id=owner_id,
                    account_id=rows[0].account_id,
                    item_ids=[row.item_id for row in rows],
                    window_hours=window_hours,
                    payload=batch.payload_snapshot,
                    request_id=request_id,
                )
            raise ValueError("这些失败项已创建重试任务，请查看新任务")
        result = await self.create(
            owner_id=owner_id,
            account_id=rows[0].account_id,
            item_ids=[row.item_id for row in rows],
            window_hours=window_hours,
            payload=batch.payload_snapshot,
            request_id=request_id,
        )
        for row in rows:
            row.retry_batch_id = result
        await self.session.flush()
        return result


async def claim() -> tuple[int, str] | None:
    async with async_session_maker() as session, session.begin():
        now = await database_now(session)
        row = (
            await session.scalars(
                select(ManagedItemEditTarget)
                .where(
                    ManagedItemEditTarget.status == "pending",
                    ManagedItemEditTarget.available_at <= now,
                )
                .order_by(ManagedItemEditTarget.available_at, ManagedItemEditTarget.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).first()
        if row is None:
            return None
        token = str(uuid4())
        row.status = "running"
        row.lease_token = token
        row.lease_expires_at = now + timedelta(seconds=120)
        session.add(ManagedItemEditAttempt(target_id=row.id, lease_token=token))
        return row.id, token


@asynccontextmanager
async def request_guard(target_id: int, token: str):
    async with async_session_maker() as session, session.begin():
        row = await session.get(ManagedItemEditTarget, target_id, with_for_update=True)
        now = await database_now(session)
        if row is None or row.status != "running" or row.lease_token != token or not row.lease_expires_at or row.lease_expires_at <= now or row.request_started_at:
            raise ValueError("执行租约失效，禁止发送")
        batch = await session.get(ManagedItemEditBatch, row.batch_id)
        if batch is None or now > batch.deadline_at:
            raise ValueError("已超过编辑排程窗口，未发送请求")
        account = await session.scalar(
            select(XYAccount).where(
                XYAccount.owner_id == batch.owner_id,
                XYAccount.account_id == row.account_id,
            )
        )
        if account is None:
            raise ValueError("账号归属已改变，禁止发送")
        managed, tool_published = origin_predicates()
        item_row = (
            await session.execute(
                select(XYCatalogItem, managed, tool_published)
                .where(
                    XYCatalogItem.owner_id == batch.owner_id,
                    XYCatalogItem.account_pk == account.id,
                    XYCatalogItem.item_id == row.item_id,
                )
            )
        ).first()
        if item_row is None or not (bool(item_row[1]) or bool(item_row[2])):
            raise ValueError("商品已变为历史或来源待确认，禁止发送")
        earliest = next_allowed_start(
            row.scheduled_at,
            None,
            timedelta(seconds=row.minimum_gap_seconds),
            batch.deadline_at,
        )
        if earliest is None or now < earliest:
            raise ValueError("编辑排程尚未到可执行时间")
        row.request_started_at = now
        attempt = await session.scalar(select(ManagedItemEditAttempt).where(ManagedItemEditAttempt.lease_token == token))
        if attempt is not None:
            attempt.request_started_at = now
    yield


async def finish(target_id: int, token: str, status: str, message: str) -> None:
    if status not in TERMINAL_STATES:
        status = "unknown"
    async with async_session_maker() as session, session.begin():
        row = await session.get(ManagedItemEditTarget, target_id, with_for_update=True)
        if row is None or row.status != "running" or row.lease_token != token:
            return
        now = await database_now(session)
        row.status = status
        row.finished_at = now
        row.message = (message or "").strip()[:1000] or None
        attempt = await session.scalar(select(ManagedItemEditAttempt).where(ManagedItemEditAttempt.lease_token == token))
        if attempt is not None:
            attempt.status = status
            attempt.message = row.message
            attempt.finished_at = now
        row.lease_token = None
        row.lease_expires_at = None


async def run_one() -> bool:
    claimed = await claim()
    if claimed is None:
        return False
    target_id, token = claimed
    started = False
    try:
        async with async_session_maker() as session:
            row = await session.get(ManagedItemEditTarget, target_id)
            batch = await session.get(ManagedItemEditBatch, row.batch_id) if row else None
            account = (
                await session.scalar(
                    select(XYAccount).where(
                        XYAccount.owner_id == batch.owner_id,
                        XYAccount.account_id == row.account_id,
                    )
                )
                if row and batch else None
            )
        if row is None or batch is None or account is None or not account.cookie:
            await finish(target_id, token, "failed", "账号、任务或商品不存在，未发送请求")
            return True
        detail = await fetch_seller_item_edit_detail(
            account_id=account.account_id,
            cookie=account.cookie,
            item_id=row.item_id,
            owner_id=account.owner_id,
        )
        if not detail.get("success") or not isinstance(detail.get("data", {}).get("form"), dict):
            await finish(target_id, token, "failed", detail.get("message") or "读取商品编辑详情失败，未发送请求")
            return True
        merged = copy.deepcopy(detail["data"]["form"])
        patch = copy.deepcopy(batch.payload_snapshot or {})
        if patch.get("images") == []:
            await finish(target_id, token, "failed", "商品图片不能为空；未发送请求")
            return True
        for key, value in patch.items():
            if key == "images" and value is None:
                continue
            merged[key] = value
        if not merged.get("images"):
            await finish(target_id, token, "failed", "商品详情没有可保留的图片，未发送请求")
            return True

        def guarded_request():
            return request_guard(target_id, token)

        result = await edit_seller_item(
            account_id=account.account_id,
            cookie=account.cookie,
            item_id=row.item_id,
            item_data=merged,
            owner_id=account.owner_id,
            request_guard=guarded_request,
        )
        started = bool(result.get("request_started")) or bool(result.get("_request_status_unknown"))
        state = _result_state(result)
        await finish(target_id, token, state, result.get("message") or "编辑结果未知，请核对平台")
    except Exception as exc:  # request_guard errors are explicit failures only before send
        await finish(target_id, token, "unknown" if started else "failed", str(exc))
    return True


async def recover() -> None:
    async with async_session_maker() as session:
        now = await database_now(session)
        rows = list(
            await session.execute(
                select(ManagedItemEditTarget.id, ManagedItemEditTarget.lease_token, ManagedItemEditTarget.request_started_at)
                .where(ManagedItemEditTarget.status == "running", ManagedItemEditTarget.lease_expires_at < now)
            )
        )
    for target_id, token, started in rows:
        if token:
            await finish(target_id, token, "unknown" if started else "failed", "执行进程中断；已发起请求须核对，未发起可手动重试")


__all__ = [
    "ManagedItemEditService",
    "database_now",
    "claim",
    "request_guard",
    "finish",
    "run_one",
    "recover",
]
