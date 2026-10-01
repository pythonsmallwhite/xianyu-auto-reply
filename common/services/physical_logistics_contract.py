"""Fail-closed validation for the physical logistics contract.

No platform call is made here. Until a verified carrier/tracking protocol is
provided, callers can validate intent and safely record failed or unknown
outcomes, but this module never turns card/no-logistics delivery into physical
shipment success.
"""

from __future__ import annotations

import hashlib

from common.schemas.physical_logistics import (
    PhysicalLogisticsIdempotencyRecord,
    PhysicalLogisticsOrderContext,
    PhysicalLogisticsSubmissionRequest,
    PhysicalLogisticsSubmissionResult,
)


class PhysicalLogisticsContractError(ValueError):
    """Raised when a request/result cannot be safely associated with an order."""


ELIGIBLE_ORDER_STATUSES = frozenset({"pending_ship", "pending", "paid", "待发货"})
NON_PHYSICAL_DELIVERY_METHODS = frozenset(
    {
        "card",
        "card_only",
        "only_send_card",
        "no_logistics",
        "无物流",
        "免拼",
        "freeshipping",
        "free_shipping",
        "manual",
        "auto",
        "scheduled",
    }
)


def request_fingerprint(request: PhysicalLogisticsSubmissionRequest) -> str:
    """Return a stable digest for same-key idempotency checks."""

    canonical = "|".join(
        (
            str(request.owner_id),
            request.order_no,
            request.carrier_name,
            request.tracking_number,
            request.fulfillment_kind,
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_submission_request(
    request: PhysicalLogisticsSubmissionRequest,
    order: PhysicalLogisticsOrderContext,
    existing: PhysicalLogisticsIdempotencyRecord | None = None,
) -> None:
    """Validate owner, order state, physical mode, and same-key idempotency."""

    if request.owner_id != order.owner_id or request.order_no != order.order_no:
        raise PhysicalLogisticsContractError("request is not owned by the order owner")

    eligible_statuses = {status.casefold() for status in ELIGIBLE_ORDER_STATUSES}
    if order.status.casefold() not in eligible_statuses:
        raise PhysicalLogisticsContractError("order status is not eligible for physical shipment")

    if order.card_only_delivered:
        raise PhysicalLogisticsContractError("card-only delivery cannot be submitted as physical shipment")

    method = (order.delivery_method or "").strip().casefold()
    non_physical_methods = {value.casefold() for value in NON_PHYSICAL_DELIVERY_METHODS}
    if method in non_physical_methods:
        raise PhysicalLogisticsContractError(
            "non-physical delivery mode cannot be submitted as physical shipment"
        )

    if existing is None:
        return
    if existing.owner_id != request.owner_id or existing.order_no != request.order_no:
        raise PhysicalLogisticsContractError("idempotency record belongs to another order")
    if existing.idempotency_key != request.idempotency_key:
        return
    if existing.request_fingerprint != request_fingerprint(request):
        raise PhysicalLogisticsContractError(
            "idempotency key was reused with a different shipment"
        )


def validate_submission_result(
    request: PhysicalLogisticsSubmissionRequest,
    result: PhysicalLogisticsSubmissionResult,
) -> None:
    """Ensure a result cannot cross owner/order/idempotency boundaries."""

    if (
        result.owner_id != request.owner_id
        or result.order_no != request.order_no
        or result.idempotency_key != request.idempotency_key
    ):
        raise PhysicalLogisticsContractError("result does not match the submitted request")
    if result.fulfillment_kind != "physical_logistics":
        raise PhysicalLogisticsContractError("result is not a physical logistics result")
    if result.outcome == "submitted" and (
        result.carrier_name != request.carrier_name
        or result.tracking_number != request.tracking_number
    ):
        raise PhysicalLogisticsContractError(
            "submitted result does not match carrier/tracking intent"
        )


__all__ = [
    "ELIGIBLE_ORDER_STATUSES",
    "NON_PHYSICAL_DELIVERY_METHODS",
    "PhysicalLogisticsContractError",
    "request_fingerprint",
    "validate_submission_request",
    "validate_submission_result",
]
