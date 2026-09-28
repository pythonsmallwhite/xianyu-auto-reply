"""Classify catalog listings using exact account and platform item IDs."""
from __future__ import annotations

from sqlalchemy import select

from common.models.internal_product import InternalProductListing
from common.models.publish_log import PublishLog
from common.models.xy_account import XYAccount
from common.models.xy_catalog_item import XYCatalogItem


def origin_predicates():
    """Return correlated SQL predicates for managed and tool-published items."""
    managed = (
        select(InternalProductListing.id)
        .where(
            InternalProductListing.owner_id == XYCatalogItem.owner_id,
            InternalProductListing.account_id == XYAccount.account_id,
            InternalProductListing.item_id == XYCatalogItem.item_id,
        )
        .correlate(XYCatalogItem, XYAccount)
        .exists()
    )
    tool_published = (
        select(PublishLog.id)
        .where(
            PublishLog.user_id == XYCatalogItem.owner_id,
            PublishLog.account_id == XYAccount.account_id,
            PublishLog.item_id == XYCatalogItem.item_id,
            PublishLog.status == "success",
        )
        .correlate(XYCatalogItem, XYAccount)
        .exists()
    )
    return managed, tool_published


def origin_name(managed: bool, tool_published: bool) -> str:
    if managed:
        return "managed"
    if tool_published:
        return "tool_published_unlinked"
    return "history_or_unknown"