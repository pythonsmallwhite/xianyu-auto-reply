"""Classify platform publish results before writing task or publish-log status."""

from __future__ import annotations

from typing import Any


def classify_publish_result(
    result: Any,
    *,
    request_started: bool,
    raised: bool = False,
) -> str:
    """Return success, failed, or unknown.

    Once a platform call starts, a missing response or exception cannot prove
    that no item was created. A contradictory response also needs reconciliation.
    """
    if raised or not isinstance(result, dict):
        return "unknown" if request_started else "failed"
    if request_started and (result.get("unknown") or result.get("_request_status_unknown")):
        return "unknown"

    success = bool(result.get("success"))
    item_id = str(result.get("item_id") or "").strip()
    if request_started and ((success and not item_id) or (not success and item_id)):
        return "unknown"
    return "success" if success else "failed"
