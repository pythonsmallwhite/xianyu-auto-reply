"""Owner-scoped internal products and exact publish-log mappings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from common.models.user import User
from common.schemas.common import ApiResponse
from common.schemas.internal_product import (
    InternalProductBindPublishLog,
    InternalProductCreate,
    InternalProductStockUpdate,
)
from common.services.internal_product_service import InternalProductService


router = APIRouter(prefix="/internal-products")


@router.get("", response_model=ApiResponse)
async def list_internal_products(
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session),
) -> ApiResponse:
    products = await InternalProductService(session).list_products(current_user.id)
    return ApiResponse(success=True, data=products)


@router.post("", response_model=ApiResponse)
async def create_internal_product(
    payload: InternalProductCreate,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session),
) -> ApiResponse:
    service = InternalProductService(session)
    try:
        product = await service.create_product(
            current_user.id, payload.title, payload.total_stock
        )
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(
        success=True,
        data=await service.snapshot(current_user.id, product.id),
    )


@router.post("/bind-publish-log", response_model=ApiResponse)
async def bind_publish_log(
    payload: InternalProductBindPublishLog,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session),
) -> ApiResponse:
    service = InternalProductService(session)
    try:
        listing = await service.bind_successful_publish_log(
            current_user.id,
            payload.publish_log_id,
            payload.internal_product_id,
        )
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(
        success=True,
        data={
            "listing_id": listing.id,
            "internal_product_id": listing.internal_product_id,
            "account_id": listing.account_id,
            "item_id": listing.item_id,
        },
    )


@router.get("/{product_id}", response_model=ApiResponse)
async def get_internal_product(
    product_id: int,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session),
) -> ApiResponse:
    try:
        data = await InternalProductService(session).snapshot(current_user.id, product_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(success=True, data=data)


@router.put("/{product_id}/stock", response_model=ApiResponse)
async def update_internal_product_stock(
    product_id: int,
    payload: InternalProductStockUpdate,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session),
) -> ApiResponse:
    try:
        data = await InternalProductService(session).update_total_stock(
            current_user.id, product_id, payload.total_stock
        )
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(success=True, data=data)


@router.get("/{product_id}/reconcile-plan", response_model=ApiResponse)
async def get_reconcile_plan(
    product_id: int,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session),
) -> ApiResponse:
    try:
        data = await InternalProductService(session).reconcile_plan(
            current_user.id, product_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(success=True, data=data)


# 持久下架只接受明确关联列表；历史商品沿用原有单件确认入口。
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from common.models.listing_action import ListingActionBatch
from common.services.listing_action_service import ListingActionService
from common.schemas.listing_action import (
    ListingActionBatchRequest as RelistBatchRequest,
    ListingActionRetryRequest as RelistRetryRequest,
    ListingActionReconcileRequest as RelistReconcileRequest,
)

class OfflineBatchRequest(BaseModel):
    listing_ids: list[int] = Field(min_length=1, max_length=200)
    window_hours: Literal[1, 3, 5, 12, 24]
    request_id: UUID
    confirmed: Literal[True]

class OfflineRetryRequest(BaseModel):
    target_ids: list[int] = Field(min_length=1, max_length=200)
    window_hours: Literal[1, 3, 5, 12, 24]
    request_id: UUID
    confirmed: Literal[True]

class OfflineReconcileRequest(BaseModel):
    platform_state: Literal["offline", "active"]
    note: str = Field(min_length=1, max_length=500)
    confirmed: Literal[True]

    @field_validator("note")
    @classmethod
    def _note_must_carry_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请填写核对依据")
        return value.strip()

@router.post("/{product_id}/offline-batches", response_model=ApiResponse)
async def create_offline_batch(product_id: int, payload: OfflineBatchRequest,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session)):
    try:
        batch_id = await ListingActionService(session).create(current_user.id, product_id,
            payload.listing_ids, payload.window_hours, str(payload.request_id))
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(400, str(exc)) from exc
    return ApiResponse(success=True, data={"batch_id": batch_id})

@router.get("/{product_id}/offline-batches", response_model=ApiResponse)
async def list_offline_batches(product_id: int,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session)):
    rows = (await session.scalars(select(ListingActionBatch).where(
        ListingActionBatch.owner_id == current_user.id, ListingActionBatch.internal_product_id == product_id,
    ).order_by(ListingActionBatch.created_at.desc()).limit(50))).all()
    return ApiResponse(success=True, data=[{"batch_id": r.id, "window_hours": r.window_hours,
        "deadline_at": r.deadline_at.isoformat()} for r in rows])

@router.get("/offline-batches/{batch_id}", response_model=ApiResponse)
async def offline_batch_detail(batch_id: str,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session)):
    try:
        data = await ListingActionService(session).detail(current_user.id, batch_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return ApiResponse(success=True, data=data)

@router.post("/offline-batches/{batch_id}/retry", response_model=ApiResponse)
async def retry_offline_batch(batch_id: str, payload: OfflineRetryRequest,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session)):
    try:
        result = await ListingActionService(session).retry(current_user.id, batch_id,
            payload.target_ids, payload.window_hours, str(payload.request_id))
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(400, str(exc)) from exc
    return ApiResponse(success=True, data={"batch_id": result})

@router.post("/offline-batches/{batch_id}/targets/{target_id}/reconcile", response_model=ApiResponse)
async def reconcile_offline_target(batch_id: str, target_id: int, payload: OfflineReconcileRequest,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session)):
    try:
        data = await ListingActionService(session).reconcile(current_user.id, batch_id, target_id,
            payload.platform_state, payload.note)
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(400, str(exc)) from exc
    return ApiResponse(success=True, data=data)
@router.post("/{product_id}/relist-batches", response_model=ApiResponse)
@router.post("/{product_id}/recovery-batches", response_model=ApiResponse)
async def create_relist_batch(product_id: int, payload: RelistBatchRequest,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session)):
    try:
        batch_id = await ListingActionService(session).create(current_user.id, product_id,
            payload.listing_ids, payload.window_hours, str(payload.request_id), operation="relist")
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(400, str(exc)) from exc
    return ApiResponse(success=True, data={"batch_id": batch_id, "operation": "relist"})


@router.get("/{product_id}/relist-batches", response_model=ApiResponse)
@router.get("/{product_id}/recovery-batches", response_model=ApiResponse)
async def list_relist_batches(product_id: int,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session)):
    rows = (await session.scalars(select(ListingActionBatch).where(
        ListingActionBatch.owner_id == current_user.id,
        ListingActionBatch.internal_product_id == product_id,
        ListingActionBatch.operation == "relist",
    ).order_by(ListingActionBatch.created_at.desc()).limit(50))).all()
    return ApiResponse(success=True, data=[{"batch_id": r.id, "operation": r.operation,
        "window_hours": r.window_hours, "deadline_at": r.deadline_at.isoformat()} for r in rows])


@router.get("/relist-batches/{batch_id}", response_model=ApiResponse)
@router.get("/recovery-batches/{batch_id}", response_model=ApiResponse)
async def relist_batch_detail(batch_id: str,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session)):
    try:
        data = await ListingActionService(session).detail(current_user.id, batch_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if data.get("operation") != "relist":
        raise HTTPException(404, "恢复任务不存在或类型不匹配")
    return ApiResponse(success=True, data=data)


@router.post("/relist-batches/{batch_id}/retry", response_model=ApiResponse)
@router.post("/recovery-batches/{batch_id}/retry", response_model=ApiResponse)
async def retry_relist_batch(batch_id: str, payload: RelistRetryRequest,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session)):
    try:
        result = await ListingActionService(session).retry(current_user.id, batch_id,
            payload.target_ids, payload.window_hours, str(payload.request_id))
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(400, str(exc)) from exc
    return ApiResponse(success=True, data={"batch_id": result, "operation": "relist"})


@router.post("/relist-batches/{batch_id}/targets/{target_id}/reconcile", response_model=ApiResponse)
@router.post("/recovery-batches/{batch_id}/targets/{target_id}/reconcile", response_model=ApiResponse)
async def reconcile_relist_target(batch_id: str, target_id: int, payload: RelistReconcileRequest,
    current_user: User = Depends(deps.get_current_active_user),
    session: AsyncSession = Depends(deps.get_db_session)):
    try:
        data = await ListingActionService(session).reconcile(current_user.id, batch_id, target_id,
            payload.platform_state, payload.note)
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(400, str(exc)) from exc
    return ApiResponse(success=True, data=data)
