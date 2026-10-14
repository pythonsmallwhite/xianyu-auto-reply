from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from loguru import logger

from app.api import deps
from common.models.user import User
from common.schemas.common import ApiResponse
from common.schemas.order import OrderOut
from common.utils.auth_scope import resolve_owner_scope
from app.services.account_service import AccountService
from app.services.order_service import OrderService
from app.services.websocket_client import websocket_client
from common.services.order_service import OrderDetailService
from common.models.xy_account import XYAccount
from sqlalchemy import select as order_select

from common.utils.time_utils import safe_isoformat
router = APIRouter(tags=["orders"])


class NoLogisticsDeliveryRequest(BaseModel):
    order_no: str


class CancelOrderRequest(BaseModel):
    order_no: str


class FetchXianyuOrdersRequest(BaseModel):
    """获取闲鱼订单请求"""
    cookie_id: str | None = None


class BatchDeleteOrdersRequest(BaseModel):
    """批量删除订单请求"""
    ids: list[int]


def _format_decimal(value: Decimal | None) -> str:
    if value is None:
        return "0.00"
    return format(value, "f")


@router.get("")
async def list_orders(
    cookie_id: str | None = Query(default=None, alias="cookie_id"),
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, description="搜索关键词（订单号、商品ID、买家ID）"),
    delivery_method: str | None = Query(default=None, description="发货方式筛选：manual/auto/scheduled/none"),
    is_bargain: bool | None = Query(default=None, description="是否小刀筛选"),
    is_rated: bool | None = Query(default=None, description="是否已评价筛选"),
    start_date: str | None = Query(default=None, description="开始日期，格式：YYYY-MM-DD"),
    end_date: str | None = Query(default=None, description="结束日期，格式：YYYY-MM-DD"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    current_user: User = Depends(deps.get_current_active_user),
    account_service: AccountService = Depends(deps.get_account_service),
    order_service: OrderService = Depends(deps.get_order_service),
):
    """获取订单列表，支持多条件筛选
    
    管理员可查看所有订单。
    
    筛选条件：
    - delivery_method: 发货方式（manual=手动发货, auto=自动发货, scheduled=定时发货, none=未发货）
    - is_bargain: 是否小刀（true/false）
    - is_rated: 是否已评价（true/false）
    - start_date: 开始日期（YYYY-MM-DD）
    - end_date: 结束日期（YYYY-MM-DD）
    """
    owner_id, is_admin = resolve_owner_scope(current_user)

    if cookie_id and not is_admin:
        account = await account_service.get_account_for_user(current_user.id, cookie_id)
        if not account:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")

    # 管理员查看所有订单，普通用户只看自己的
    orders, total, item_titles = await order_service.list_orders(
        owner_id,
        account_id=cookie_id,
        status=status_filter,
        search=search,
        delivery_method=delivery_method,
        is_bargain=is_bargain,
        is_rated=is_rated,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )

    payload = []
    for order in orders:
        spec_parts = [part for part in [order.spec_name, order.spec_value] if part]
        sku_info = " / ".join(spec_parts) if spec_parts else None
        # 从关联查询结果获取商品标题
        item_title = item_titles.get(order.item_id, "") if order.item_id else ""
        payload.append(
            OrderOut(
                id=str(order.id),
                order_id=order.order_no,
                cookie_id=order.account_id or "",
                item_id=order.item_id or "",
                item_title=item_title,
                buyer_id=order.buyer_id or "",
                buyer_fish_nick=order.buyer_fish_nick or "",
                chat_id=order.chat_id or "",
                sku_info=sku_info,
                quantity=order.quantity or 0,
                amount=_format_decimal(order.amount),
                status=(order.status or "unknown").lower(),
                is_bargain=order.is_bargain or False,
                is_rated=order.is_rated or False,
                is_red_flower=order.is_red_flower or False,
                is_unregistered=order.is_unregistered or False,
                unregister_error_reason=order.unregister_error_reason or None,
                receiver_name=order.receiver_name or "",
                receiver_phone=order.receiver_phone or "",
                receiver_address=order.receiver_address or "",
                delivery_method=order.delivery_method or "",
                delivery_content=order.delivery_content or "",
                delivery_fail_reason=order.delivery_fail_reason or "",
                card_only_delivered=bool(order.card_only_delivered),
                source=order.source or "",
                placed_at=order.placed_at,
                created_at=order.created_at,
                updated_at=order.updated_at,
            )
        )

    return {
        "success": True,
        "data": payload,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
    }


@router.post("/fetch-xianyu")
async def fetch_xianyu_orders(
    request: FetchXianyuOrdersRequest,
    current_user: User = Depends(deps.get_current_active_user),
    account_service: AccountService = Depends(deps.get_account_service),
    order_service: OrderService = Depends(deps.get_order_service),
):
    """获取闲鱼卖家订单并同步到数据库"""
    owner_id, _ = resolve_owner_scope(current_user)

    if request.cookie_id:
        account = await account_service.get_account_for_user(owner_id, request.cookie_id)
        if not account:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
        accounts = [account]
    else:
        accounts = await account_service.list_accounts(owner_id)
        inactive_statuses = {"inactive", "disabled", "suspended", "deleted"}
        accounts = [acc for acc in accounts if (acc.status or "active") not in inactive_statuses]

    if not accounts:
        return {
            "success": True,
            "message": "没有可同步的账号",
            "data": {
                "total_fetched": 0,
                "new_inserted": 0,
                "updated": 0,
                "failed": 0,
                "accounts_processed": 0,
                "errors": [],
            },
        }

    total_fetched = 0
    new_inserted = 0
    updated = 0
    failed = 0
    errors: list[str] = []

    for account in accounts:
        try:
            logger.info(f"开始同步闲鱼订单: account_id={account.account_id}")
            result = await order_service.fetch_xianyu_orders(account)
            total_fetched += result.get("total_fetched", 0)
            new_inserted += result.get("new_inserted", 0)
            updated += result.get("updated", 0)
            failed += result.get("failed", 0)
            for error in result.get("errors", []):
                errors.append(f"{account.account_id}: {error}")
        except Exception as e:
            logger.error(f"同步闲鱼订单失败: account_id={account.account_id}, error={e}")
            errors.append(f"{account.account_id}: {str(e)}")

    return {
        "success": True,
        "message": f"同步完成，共处理 {len(accounts)} 个账号",
        "data": {
            "total_fetched": total_fetched,
            "new_inserted": new_inserted,
            "updated": updated,
            "failed": failed,
            "accounts_processed": len(accounts),
            "errors": errors,
        },
    }


@router.get("/{order_no}")
async def get_order_detail(
    order_no: str,
    refresh: bool = Query(default=False),
    current_user: User = Depends(deps.get_current_active_user),
    order_service: OrderService = Depends(deps.get_order_service),
):
    """获取订单详情，管理员可查看所有订单"""
    order = await order_service.get_order_by_id(order_no)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")

    # 验证订单属于当前用户（管理员可查看所有）
    _, is_admin = resolve_owner_scope(current_user)
    if not is_admin and order.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看此订单")
    
    if refresh and order.account_id:
        try:
            account_result = await order_service.session.execute(
                order_select(XYAccount).where(XYAccount.account_id == order.account_id)
            )
            account = account_result.scalar_one_or_none()
            if account and account.cookie:
                await OrderDetailService(order.account_id, account.cookie).fetch_and_update_order_detail(
                    order_id=order.order_no,
                    item_id=order.item_id,
                    buyer_id=order.buyer_id,
                )
                order_service.session.expire_all()
                order = await order_service.get_order_by_id(order_no)
        except Exception as e:
            logger.warning(f"刷新订单详情失败，返回本地数据: order_no={order_no}, error={e}")

    spec_parts = [part for part in [order.spec_name, order.spec_value] if part]
    sku_info = " / ".join(spec_parts) if spec_parts else None
    
    # 关联查询商品标题
    item_title = await order_service.get_item_title(order.owner_id, order.item_id)
    
    return {
        "success": True,
        "data": {
            "id": str(order.id),
            "order_id": order.order_no,
            "cookie_id": order.account_id or "",
            "item_id": order.item_id or "",
            "item_title": item_title,
            "buyer_id": order.buyer_id or "",
            "buyer_fish_nick": order.buyer_fish_nick or "",
            "chat_id": order.chat_id or "",
            "spec_name": order.spec_name or "",
            "spec_value": order.spec_value or "",
            "sku_info": sku_info,
            "quantity": order.quantity or 0,
            "amount": _format_decimal(order.amount),
            "status": (order.status or "unknown").lower(),
            "is_bargain": order.is_bargain or False,
            "is_rated": order.is_rated or False,
            "is_red_flower": order.is_red_flower or False,
            "is_unregistered": order.is_unregistered or False,
            "unregister_error_reason": order.unregister_error_reason or None,
            "receiver_name": order.receiver_name or "",
            "receiver_phone": order.receiver_phone or "",
            "receiver_address": order.receiver_address or "",
            "delivery_method": order.delivery_method or "",
            "delivery_content": order.delivery_content or "",
            "delivery_fail_reason": order.delivery_fail_reason or "",
            "card_only_delivered": bool(order.card_only_delivered),
            "source": order.source or "",
            "placed_at": safe_isoformat(order.placed_at),
            "created_at": safe_isoformat(order.created_at),
            "updated_at": safe_isoformat(order.updated_at),
        }
    }


@router.post("/batch-delete")
async def batch_delete_orders(
    request: BatchDeleteOrdersRequest,
    current_user: User = Depends(deps.get_current_active_user),
    order_service: OrderService = Depends(deps.get_order_service),
):
    """批量删除订单"""
    if not request.ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择要删除的订单")

    owner_id, _ = resolve_owner_scope(current_user)

    result = await order_service.batch_delete_orders(request.ids, owner_id)
    return {
        "success": True,
        "message": f"删除完成，成功{result['deleted']}条" + (f"，失败{result['failed']}条" if result['failed'] else ""),
        "data": result,
    }


@router.delete("/{order_id}")
async def delete_order(
    order_id: int,
    current_user: User = Depends(deps.get_current_active_user),
    order_service: OrderService = Depends(deps.get_order_service),
):
    """删除订单"""
    success = await order_service.delete_order(order_id, current_user.id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在或无权删除")
    return ApiResponse(success=True, message="删除成功")


@router.post("/no-logistics-delivery")
async def no_logistics_delivery(
    request: NoLogisticsDeliveryRequest,
    current_user: User = Depends(deps.get_current_active_user),
    order_service: OrderService = Depends(deps.get_order_service),
    account_service: AccountService = Depends(deps.get_account_service),
):
    """无物流发货：仅在闲鱼确认发货，不发送任何卡券或聊天内容"""
    order = await order_service.get_order_by_no(request.order_no)
    if not order:
        return ApiResponse(success=False, message="订单不存在")

    owner_id, is_admin = resolve_owner_scope(current_user)
    if not is_admin and order.owner_id != current_user.id:
        return ApiResponse(success=False, message="无权操作此订单")
    if order.status not in {"pending_ship", "pending", "paid", "待发货"}:
        return ApiResponse(success=False, message="只有待发货订单可以发货")
    if not order.account_id or not order.item_id or not order.buyer_id:
        return ApiResponse(success=False, message="订单缺少账号、商品或买家信息")

    account = await account_service.get_account_for_user(owner_id, order.account_id)
    if not account:
        return ApiResponse(success=False, message="账号不存在")

    status_result = await websocket_client.get_account_status(order.account_id)
    if not status_result.get("success") or not status_result.get("data", {}).get("is_connected"):
        return ApiResponse(success=False, message="账号未连接，请先启动账号")

    result = await websocket_client.confirm_no_logistics(
        account_id=order.account_id,
        order_no=order.order_no,
        item_id=order.item_id,
        buyer_id=order.buyer_id,
        is_bargain=bool(order.is_bargain),
    )
    if not result.get("success"):
        return ApiResponse(success=False, message=result.get("message", "无物流发货失败"))
    return ApiResponse(success=True, message="无物流发货成功", data=result.get("data"))


@router.post("/cancel")
async def cancel_order(
    request: CancelOrderRequest,
    current_user: User = Depends(deps.get_current_active_user),
    order_service: OrderService = Depends(deps.get_order_service),
    account_service: AccountService = Depends(deps.get_account_service),
):
    """卖家关闭（取消）一笔待处理订单"""
    order = await order_service.get_order_by_no(request.order_no)
    if not order:
        return ApiResponse(success=False, message="订单不存在")
    owner_id, is_admin = resolve_owner_scope(current_user)
    if not is_admin and order.owner_id != current_user.id:
        return ApiResponse(success=False, message="无权操作此订单")
    if order.status not in {"pending_payment", "pending_ship", "pending", "paid", "待付款", "待发货"}:
        return ApiResponse(success=False, message="当前订单状态不可取消")
    if not order.account_id:
        return ApiResponse(success=False, message="订单缺少账号信息")
    if not await account_service.get_account_for_user(owner_id, order.account_id):
        return ApiResponse(success=False, message="账号不存在")

    status_result = await websocket_client.get_account_status(order.account_id)
    if not status_result.get("success") or not status_result.get("data", {}).get("is_connected"):
        return ApiResponse(success=False, message="账号未连接，请先启动账号")
    result = await websocket_client.cancel_order(order.account_id, order.order_no)
    if not result.get("success"):
        return ApiResponse(success=False, message=result.get("message", "取消订单失败"))
    return ApiResponse(success=True, message="订单已取消", data=result.get("data"))
