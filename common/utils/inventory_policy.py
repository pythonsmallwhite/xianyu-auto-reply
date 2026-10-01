"""Pure inventory decisions for explicitly linked marketplace listings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping


OrderState = Literal["reserved", "released"]
OrderEvent = Literal["placed", "paid", "cancelled"]
InventoryOrderEvent = Literal["placed", "paid", "cancelled", "refunding", "refunded"]


def inventory_event_for_status(
    status: str | None, previous_status: str | None = None
) -> InventoryOrderEvent | None:
    """把订单状态转成一次库存事件；退款状态优先保留占用。"""
    if (previous_status or "").lower() in {"refunding", "refunded", "refund_closed"}:
        return "refunding"
    return {
        "pending_payment": "placed",
        "pending_ship": "paid",
        "pending": "paid",
        "paid": "paid",
        "shipped": "paid",
        "completed": "paid",
        "cancelled": "cancelled",
        "closed": "cancelled",
        "refunding": "refunding",
        "refunded": "refunded",
    }.get((status or "").lower())
ListingState = Literal["active", "sold", "offline"]
OfflineReason = Literal["inventory", "manual", "other", None]
PendingAction = Literal["offline", "relist", None]
ActionKind = Literal["schedule_offline", "schedule_relist", "cancel_offline", "cancel_relist"]


@dataclass(frozen=True)
class LinkedListing:
    listing_id: int
    source: Literal["managed", "historical", "unknown"]
    state: ListingState
    offline_reason: OfflineReason = None
    pending_action: PendingAction = None


@dataclass(frozen=True)
class InventoryAction:
    listing_id: int
    kind: ActionKind

    @property
    def operation(self) -> Literal["offline", "relist"]:
        """The durable listing-action operation represented by this decision."""
        return "relist" if self.kind in {"schedule_relist", "cancel_relist"} else "offline"


def apply_order_event(
    states: Mapping[str, OrderState],
    order_id: str,
    event: OrderEvent,
) -> dict[str, OrderState]:
    """Deduplicate placed/paid events and make cancellation terminal."""
    if not order_id:
        raise ValueError("order_id is required")
    if event not in ("placed", "paid", "cancelled"):
        raise ValueError("unsupported order event")
    updated = dict(states)
    if event == "cancelled":
        updated[order_id] = "released"
    elif order_id not in updated:
        updated[order_id] = "reserved"
    elif updated[order_id] == "released":
        return updated
    return updated


def available_stock(total_stock: int, order_states: Mapping[str, OrderState]) -> int:
    if total_stock < 0:
        raise ValueError("total_stock cannot be negative")
    reserved = sum(state == "reserved" for state in order_states.values())
    return total_stock - reserved


def reconcile_listings(
    total_stock: int,
    order_states: Mapping[str, OrderState],
    listings: list[LinkedListing],
) -> tuple[InventoryAction, ...]:
    """Return actions only for listings explicitly managed by this tool."""
    available = available_stock(total_stock, order_states)
    actions: list[InventoryAction] = []
    for listing in listings:
        if listing.source != "managed" or listing.state == "sold":
            continue
        if available <= 0:
            if listing.pending_action == "relist":
                actions.append(InventoryAction(listing.listing_id, "cancel_relist"))
            if listing.state == "active" and listing.pending_action != "offline":
                actions.append(InventoryAction(listing.listing_id, "schedule_offline"))
        else:
            if listing.pending_action == "offline":
                actions.append(InventoryAction(listing.listing_id, "cancel_offline"))
            if (
                listing.state == "offline"
                and listing.offline_reason == "inventory"
                and listing.pending_action != "relist"
            ):
                actions.append(InventoryAction(listing.listing_id, "schedule_relist"))
    return tuple(actions)
