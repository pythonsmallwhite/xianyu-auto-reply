"""Transport-neutral schemas for a future physical-logistics adapter.

This module deliberately does not describe a platform endpoint or request body.
The current repository has no verified carrier/tracking submission protocol, so
an adapter must supply an independently verified receipt before reporting a
successful submission.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _strip_required(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("value must not be blank")
    return normalized


class PhysicalLogisticsSubmissionRequest(BaseModel):
    """Normalized physical shipment intent; no platform payload fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    owner_id: int = Field(gt=0)
    order_no: str = Field(min_length=1, max_length=64)
    carrier_name: str = Field(min_length=1, max_length=120)
    tracking_number: str = Field(min_length=1, max_length=128)
    idempotency_key: UUID
    fulfillment_kind: Literal["physical_logistics"]

    _required_text = field_validator("order_no", "carrier_name", "tracking_number")(_strip_required)


class PhysicalLogisticsOrderContext(BaseModel):
    """Owner/status snapshot read from the local order store before submission."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    owner_id: int = Field(gt=0)
    order_no: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=32)
    delivery_method: str | None = Field(default=None, max_length=32)
    card_only_delivered: bool = False

    _required_text = field_validator("order_no", "status")(_strip_required)


class PhysicalLogisticsSubmissionResult(BaseModel):
    """Result envelope with explicit unknown/failed outcomes.

    A submitted outcome requires an opaque adapter receipt and exact physical
    request identifiers. The receipt is intentionally not modeled because its
    shape belongs to a future verified platform protocol.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    owner_id: int = Field(gt=0)
    order_no: str = Field(min_length=1, max_length=64)
    idempotency_key: UUID
    fulfillment_kind: Literal["physical_logistics"]
    outcome: Literal["submitted", "failed", "unknown"]
    carrier_name: str | None = Field(default=None, max_length=120)
    tracking_number: str | None = Field(default=None, max_length=128)
    platform_reference: str | None = Field(default=None, max_length=256)
    protocol_receipt: str | None = Field(default=None, max_length=4096)
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=1000)

    _required_text = field_validator("order_no")(_strip_required)

    @model_validator(mode="after")
    def validate_outcome(self) -> "PhysicalLogisticsSubmissionResult":
        if self.outcome == "submitted":
            missing = [
                name
                for name, value in (
                    ("carrier_name", self.carrier_name),
                    ("tracking_number", self.tracking_number),
                    ("platform_reference", self.platform_reference),
                    ("protocol_receipt", self.protocol_receipt),
                )
                if not value or not value.strip()
            ]
            if missing:
                raise ValueError(
                    "submitted physical logistics result requires " + ", ".join(missing)
                )
        elif self.outcome == "failed" and not (self.error_code or self.error_message):
            raise ValueError("failed physical logistics result requires an error")
        elif self.outcome == "unknown" and not (self.error_code or self.error_message):
            raise ValueError("unknown physical logistics result requires an explanation")
        return self


class PhysicalLogisticsIdempotencyRecord(BaseModel):
    """The immutable request identity retained by an adapter or persistence layer."""

    model_config = ConfigDict(extra="forbid")

    owner_id: int = Field(gt=0)
    order_no: str = Field(min_length=1, max_length=64)
    idempotency_key: UUID
    request_fingerprint: str = Field(min_length=64, max_length=64)
