"""Request models for durable linked-listing operations."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


ListingActionOperation = Literal["offline", "relist"]


class ListingActionBatchRequest(BaseModel):
    listing_ids: list[int] = Field(min_length=1, max_length=200)
    window_hours: Literal[1, 3, 5, 12, 24]
    request_id: UUID
    confirmed: Literal[True]


class ListingActionRetryRequest(BaseModel):
    target_ids: list[int] = Field(min_length=1, max_length=200)
    window_hours: Literal[1, 3, 5, 12, 24]
    request_id: UUID
    confirmed: Literal[True]


class ListingActionReconcileRequest(BaseModel):
    platform_state: Literal["offline", "active"]
    note: str = Field(min_length=1, max_length=500)
    confirmed: Literal[True]

    @field_validator("note")
    @classmethod
    def _note_must_carry_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请填写核对依据")
        return value.strip()