"""Plan request start times for one internal product across its target accounts."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Protocol


WINDOW_HOURS = frozenset({1, 3, 5, 12, 24})


class _RandomSource(Protocol):
    def expovariate(self, lambd: float) -> float: ...

    def uniform(self, a: float, b: float) -> float: ...


def plan_product_offsets(
    account_count: int,
    window_hours: int,
    rng: _RandomSource | None = None,
) -> tuple[float, ...]:
    """Return start offsets in seconds for one product, within its window.

    For N > 1, neighboring starts are at least T / (2N) apart.
    Another T / (2N) is left after the last planned start.
    """
    if account_count < 1:
        raise ValueError("account_count must be positive")
    if window_hours not in WINDOW_HOURS:
        raise ValueError("window_hours must be 1, 3, 5, 12, or 24")

    window_seconds = window_hours * 3600.0
    source = rng if rng is not None else random.SystemRandom()
    if account_count == 1:
        return (source.uniform(0.0, window_seconds),)

    minimum_gap = window_seconds / (2 * account_count)
    slack = window_seconds - account_count * minimum_gap
    weights = [source.expovariate(1.0) for _ in range(account_count + 1)]
    total_weight = sum(weights)
    if total_weight <= 0:
        raise ValueError("random source produced no positive weights")

    offset = slack * weights[0] / total_weight
    offsets = [offset]
    for weight in weights[1:account_count]:
        offset += minimum_gap + slack * weight / total_weight
        offsets.append(offset)
    return tuple(offsets)


def next_allowed_start(
    planned_at: datetime,
    previous_started_at: datetime | None,
    minimum_gap: timedelta,
    deadline_at: datetime,
) -> datetime | None:
    """Delay a request after a late prior start, or reject it past deadline."""
    if minimum_gap < timedelta(0):
        raise ValueError("minimum_gap must be nonnegative")
    start_at = planned_at
    if previous_started_at is not None:
        start_at = max(start_at, previous_started_at + minimum_gap)
    return start_at if start_at <= deadline_at else None
