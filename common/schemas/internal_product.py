"""Request models for user-managed internal stock."""

from __future__ import annotations

from pydantic import BaseModel, Field


class InternalProductCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    total_stock: int | None = Field(default=None, ge=0)


class InternalProductStockUpdate(BaseModel):
    total_stock: int = Field(ge=0)


class InternalProductBindPublishLog(BaseModel):
    publish_log_id: int = Field(gt=0)
    internal_product_id: int | None = Field(default=None, gt=0)
