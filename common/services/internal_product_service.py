"""Explicit internal-product mapping and idempotent stock ledger.

No function in this module sends a marketplace request. Callers must persist
confirmed marketplace outcomes before binding a listing or changing its state.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.internal_product import (
    InternalProduct,
    InternalProductListing,
    InventoryOrderHold,
)
from common.models.product_material import ProductMaterial
from common.models.publish_log import PublishLog
from common.models.xy_account import XYAccount
from common.utils.inventory_policy import LinkedListing, reconcile_listings


class InternalProductService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_product(
        self, owner_id: int, title: str, total_stock: int | None = None
    ) -> InternalProduct:
        title = title.strip()
        if not title:
            raise ValueError("商品名称不能为空")
        if total_stock is not None and total_stock < 0:
            raise ValueError("内部库存不能为负数")
        product = InternalProduct(owner_id=owner_id, title=title, total_stock=total_stock)
        self.session.add(product)
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def _locked_product(self, owner_id: int, product_id: int) -> InternalProduct:
        product = (
            await self.session.execute(
                select(InternalProduct)
                .where(
                    InternalProduct.id == product_id,
                    InternalProduct.owner_id == owner_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if product is None:
            raise ValueError("内部商品不存在")
        return product

    async def _occupied(self, product_id: int) -> int:
        value = await self.session.scalar(
            select(func.coalesce(func.sum(InventoryOrderHold.quantity), 0)).where(
                InventoryOrderHold.internal_product_id == product_id,
                InventoryOrderHold.status.in_(["reserved", "refund_hold"]),
            )
        )
        return int(value or 0)

    async def update_total_stock(
        self, owner_id: int, product_id: int, total_stock: int
    ) -> dict:
        if total_stock < 0:
            raise ValueError("内部库存不能为负数")
        product = await self._locked_product(owner_id, product_id)
        occupied = await self._occupied(product.id)
        if total_stock < occupied:
            raise ValueError(f"内部库存不能小于当前有效占用 {occupied}")
        product.total_stock = total_stock
        await self.session.commit()
        return await self.reconcile_plan(owner_id, product_id)

    async def list_products(self, owner_id: int) -> list[dict]:
        products = (
            await self.session.execute(
                select(InternalProduct)
                .where(InternalProduct.owner_id == owner_id)
                .order_by(InternalProduct.id.desc())
            )
        ).scalars().all()
        result = []
        for product in products:
            result.append(await self.snapshot(owner_id, product.id))
        return result

    async def snapshot(self, owner_id: int, product_id: int) -> dict:
        product = await self._locked_product(owner_id, product_id)
        occupied = await self._occupied(product.id)
        listings = (
            await self.session.execute(
                select(InternalProductListing)
                .where(
                    InternalProductListing.owner_id == owner_id,
                    InternalProductListing.internal_product_id == product.id,
                )
                .order_by(InternalProductListing.id)
            )
        ).scalars().all()
        return {
            "id": product.id,
            "title": product.title,
            "material_id": product.material_id,
            "total_stock": product.total_stock,
            "occupied": occupied,
            "available": None if product.total_stock is None else product.total_stock - occupied,
            "listings": [
                {
                    "id": listing.id,
                    "account_id": listing.account_id,
                    "item_id": listing.item_id,
                    "publish_log_id": listing.publish_log_id,
                    "state": listing.state,
                    "offline_reason": listing.offline_reason,
                    "pending_action": listing.pending_action,
                    "state_version": listing.state_version,
                }
                for listing in listings
            ],
        }

    async def _product_for_material(
        self, owner_id: int, material_id: int
    ) -> InternalProduct:
        # Lock the source row to serialize first-time creation for this material.
        material = (
            await self.session.execute(
                select(ProductMaterial)
                .where(
                    ProductMaterial.id == material_id,
                    ProductMaterial.user_id == owner_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if material is None:
            raise ValueError("素材不存在或无权使用")
        product = (
            await self.session.execute(
                select(InternalProduct).where(
                    InternalProduct.owner_id == owner_id,
                    InternalProduct.material_id == material_id,
                )
            )
        ).scalar_one_or_none()
        if product is None:
            product = InternalProduct(
                owner_id=owner_id,
                material_id=material_id,
                title=material.title,
                total_stock=None,
            )
            self.session.add(product)
            await self.session.flush()
        return product

    async def bind_successful_publish_log(
        self,
        owner_id: int,
        publish_log_id: int,
        internal_product_id: int | None = None,
    ) -> InternalProductListing | None:
        """Bind only exact successful tool publications, never by title.

        A successful log without a material needs an explicit internal product.
        A material-backed log creates/reuses one product for the material.
        Stock stays unconfigured until the owner enters it.
        """
        log = (
            await self.session.execute(
                select(PublishLog).where(
                    PublishLog.id == publish_log_id,
                    PublishLog.user_id == owner_id,
                )
            )
        ).scalar_one_or_none()
        if log is None or log.status != "success" or not log.item_id:
            raise ValueError("只能关联已确认成功且包含平台商品 ID 的发布日志")
        account = (
            await self.session.execute(
                select(XYAccount.id).where(
                    XYAccount.owner_id == owner_id,
                    XYAccount.account_id == log.account_id,
                )
            )
        ).scalar_one_or_none()
        if account is None:
            raise ValueError("发布账号不存在或不属于当前用户")
        existing = (
            await self.session.execute(
                select(InternalProductListing).where(
                    InternalProductListing.owner_id == owner_id,
                    InternalProductListing.account_id == log.account_id,
                    InternalProductListing.item_id == log.item_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.publish_log_id != log.id:
                raise ValueError("该平台商品已关联其他发布记录")
            if internal_product_id is not None and existing.internal_product_id != internal_product_id:
                raise ValueError("该平台商品已关联其他内部商品")
            return existing

        if internal_product_id is None:
            if log.material_id is None:
                raise ValueError("该发布日志无素材，请指定内部商品")
            product = await self._product_for_material(owner_id, log.material_id)
        else:
            product = await self._locked_product(owner_id, internal_product_id)
            if log.material_id is not None and product.material_id != log.material_id:
                raise ValueError("素材与内部商品不匹配")
        listing = InternalProductListing(
            owner_id=owner_id,
            internal_product_id=product.id,
            account_id=log.account_id,
            item_id=log.item_id,
            publish_log_id=log.id,
            state="active",
            state_version=0,
        )
        self.session.add(listing)
        await self.session.commit()
        await self.session.refresh(listing)
        return listing

    async def apply_order_event(
        self,
        owner_id: int,
        account_id: str,
        item_id: str,
        order_no: str,
        event: str,
        quantity: int = 1,
        *,
        commit: bool = True,
        sync_quantity: bool = False,
    ) -> dict | None:
        """幂等记录订单占用；退款保留占用，不能自动恢复可售。

        未关联商品返回 None。commit=False 由订单落库事务统一提交；
        sync_quantity 仅供已确认数量的订单同步使用。返回计划不调用平台。
        """
        if event not in {"placed", "paid", "cancelled", "refunding", "refunded"}:
            raise ValueError("不支持的订单事件")
        if event in {"refunding", "refunded"} and not sync_quantity:
            sync_quantity = True
        if not order_no.strip() or quantity < 1:
            raise ValueError("订单号和数量无效")
        listing = (
            await self.session.execute(
                select(InternalProductListing).where(
                    InternalProductListing.owner_id == owner_id,
                    InternalProductListing.account_id == account_id,
                    InternalProductListing.item_id == item_id,
                )
            )
        ).scalar_one_or_none()
        if listing is None:
            return None
        product = await self._locked_product(owner_id, listing.internal_product_id)
        hold = (
            await self.session.execute(
                select(InventoryOrderHold).where(
                    InventoryOrderHold.owner_id == owner_id,
                    InventoryOrderHold.account_id == account_id,
                    InventoryOrderHold.order_no == order_no,
                )
            )
        ).scalar_one_or_none()
        changed = False
        if hold is None:
            hold = InventoryOrderHold(
                owner_id=owner_id,
                internal_product_id=product.id,
                listing_id=listing.id,
                account_id=account_id,
                order_no=order_no,
                quantity=quantity,
                status="released" if event == "cancelled" else "refund_hold" if event in {"refunding", "refunded"} else "reserved",
            )
            self.session.add(hold)
            changed = True
            if event != "cancelled" and listing.state == "active":
                listing.state = "sold"
                listing.state_version += 1
        else:
            if hold.listing_id != listing.id:
                raise ValueError("同一订单的商品与已记录事件不一致")
            if hold.quantity != quantity:
                if not sync_quantity:
                    raise ValueError("同一订单的数量与已记录事件不一致")
                hold.quantity = quantity
                changed = True
            if event in {"refunding", "refunded"} and hold.status != "refund_hold":
                # 退款证据优先于泛化的交易关闭，需人工确认退回实物后再处理库存。
                hold.status = "refund_hold"
                changed = True
            elif event == "cancelled" and hold.status == "reserved":
                hold.status = "released"
                changed = True

        if changed:
            await self.session.flush()
        plan = await self.reconcile_plan(owner_id, product.id)
        if commit:
            await self.session.commit()
        return plan

    async def reconcile_plan(self, owner_id: int, product_id: int) -> dict:
        """Read-only desired actions; this does not schedule or call Xianyu."""
        snapshot = await self.snapshot(owner_id, product_id)
        if snapshot["total_stock"] is None:
            snapshot["actions"] = []
            return snapshot
        holds = (
            await self.session.execute(
                select(InventoryOrderHold).where(
                    InventoryOrderHold.owner_id == owner_id,
                    InventoryOrderHold.internal_product_id == product_id,
                    InventoryOrderHold.status.in_(["reserved", "refund_hold"]),
                )
            )
        ).scalars().all()
        # The existing pure policy counts one unit per key.
        order_states = {
            f"{hold.id}:{unit}": "reserved"
            for hold in holds
            for unit in range(hold.quantity)
        }
        listings = [
            LinkedListing(
                listing_id=entry["id"],
                source="managed",
                state=entry["state"],
                offline_reason=entry["offline_reason"],
                pending_action=entry["pending_action"],
            )
            for entry in snapshot["listings"]
        ]
        snapshot["actions"] = [
            {"listing_id": action.listing_id, "kind": action.kind}
            for action in reconcile_listings(
                snapshot["total_stock"], order_states, listings
            )
        ]
        return snapshot

    async def mark_manual_offline(
        self, owner_id: int, account_id: str, item_id: str
    ) -> bool:
        """Call only after confirmed manual platform offline success."""
        listing = (
            await self.session.execute(
                select(InternalProductListing).where(
                    InternalProductListing.owner_id == owner_id,
                    InternalProductListing.account_id == account_id,
                    InternalProductListing.item_id == item_id,
                )
            )
        ).scalar_one_or_none()
        if listing is None:
            return False
        await self._locked_product(owner_id, listing.internal_product_id)
        listing.state = "offline"
        listing.offline_reason = "manual"
        listing.pending_action = None
        listing.state_version += 1
        await self.session.commit()
        return True

    async def can_run_inventory_action(
        self,
        owner_id: int,
        listing_id: int,
        action: str,
        expected_version: int,
    ) -> bool:
        """Recheck a delayed action immediately before its platform request."""
        if action not in {"offline", "relist"}:
            raise ValueError("不支持的库存动作")
        listing = (
            await self.session.execute(
                select(InternalProductListing).where(
                    InternalProductListing.id == listing_id,
                    InternalProductListing.owner_id == owner_id,
                )
            )
        ).scalar_one_or_none()
        if listing is None or listing.state_version != expected_version:
            return False
        product = await self._locked_product(owner_id, listing.internal_product_id)
        if product.total_stock is None:
            return False
        available = product.total_stock - await self._occupied(product.id)
        if action == "offline":
            return available <= 0 and listing.state == "active"
        return (
            available > 0
            and listing.state == "offline"
            and listing.offline_reason == "inventory"
        )

    async def confirm_inventory_action(
        self,
        owner_id: int,
        listing_id: int,
        action: str,
        expected_version: int,
    ) -> dict | None:
        """Record a confirmed platform outcome; stale manual edits win.

        A stock change during an in-flight request may require a counteraction.
        The returned plan exposes it for the delayed task executor.
        """
        if action not in {"offline", "relist"}:
            raise ValueError("不支持的库存动作")
        listing = (
            await self.session.execute(
                select(InternalProductListing).where(
                    InternalProductListing.id == listing_id,
                    InternalProductListing.owner_id == owner_id,
                )
            )
        ).scalar_one_or_none()
        if listing is None:
            return None
        await self._locked_product(owner_id, listing.internal_product_id)
        if listing.state_version != expected_version:
            return None
        if action == "offline" and listing.state == "active":
            listing.state = "offline"
            listing.offline_reason = "inventory"
        elif (
            action == "relist"
            and listing.state == "offline"
            and listing.offline_reason == "inventory"
        ):
            listing.state = "active"
            listing.offline_reason = None
        else:
            return None
        listing.pending_action = None
        listing.state_version += 1
        await self.session.commit()
        return await self.reconcile_plan(owner_id, listing.internal_product_id)
