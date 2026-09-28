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
