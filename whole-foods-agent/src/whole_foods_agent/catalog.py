"""What the household buys, how much of it, and how often.

Everything here is derived from order history alone. The useful signal is the
gap between repeat purchases: an item bought every 8 days that was last bought
11 days ago has run out, and that is the whole basis for proposing it.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Sequence

from .model import Order

# Below this many purchases there is no gap to measure, so cadence is unknown
# and the item is only ever offered as a suggestion, never auto-included.
MIN_PURCHASES_FOR_CADENCE = 2


@dataclass
class ItemStats:
    """One product's buying history."""

    key: str
    name: str
    department: str
    size: str | None = None
    dates: list[date] = field(default_factory=list)
    quantities: list[float] = field(default_factory=list)
    unit_prices: list[float] = field(default_factory=list)
    unit: str = "each"
    total_spend: float = 0.0

    @property
    def times_bought(self) -> int:
        return len(self.dates)

    @property
    def first_bought(self) -> date:
        return min(self.dates)

    @property
    def last_bought(self) -> date:
        return max(self.dates)

    @property
    def typical_quantity(self) -> float:
        return statistics.median(self.quantities) if self.quantities else 1.0

    @property
    def last_price(self) -> float | None:
        """Most recent unit price, which is the best guess at today's."""
        return self.unit_prices[-1] if self.unit_prices else None

    @property
    def intervals(self) -> list[int]:
        """Days between consecutive purchases."""
        ordered = sorted(set(self.dates))
        return [(b - a).days for a, b in zip(ordered, ordered[1:])]

    @property
    def median_interval(self) -> float | None:
        gaps = [gap for gap in self.intervals if gap > 0]
        if len(gaps) < 1:
            return None
        return float(statistics.median(gaps))

    @property
    def has_cadence(self) -> bool:
        return self.times_bought >= MIN_PURCHASES_FOR_CADENCE and self.median_interval is not None

    def days_since(self, today: date) -> int:
        return (today - self.last_bought).days

    def due_ratio(self, today: date) -> float | None:
        """How far through its usual gap this item is. 1.0 means due today."""
        interval = self.median_interval
        if not interval:
            return None
        return self.days_since(today) / interval

    @property
    def confidence(self) -> str:
        if self.times_bought >= 5:
            return "high"
        if self.times_bought >= 3:
            return "medium"
        return "low"

    def estimated_cost(self) -> float | None:
        price = self.last_price
        if price is None:
            return None
        return round(price * self.typical_quantity, 2)


@dataclass
class Catalog:
    """The full picture built from order history."""

    items: dict[str, ItemStats] = field(default_factory=dict)
    orders: list[Order] = field(default_factory=list)
    # Pairs of item keys that tend to be bought on the same trip.
    co_occurrence: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def last_order_date(self) -> date | None:
        return max((order.ordered_on for order in self.orders), default=None)

    @property
    def truncated_orders(self) -> list[Order]:
        """Orders the source could not fully itemise."""
        return [order for order in self.orders if order.truncated]

    def ranked(self) -> list[ItemStats]:
        return sorted(self.items.values(), key=lambda s: (-s.times_bought, s.name))

    def staples(self) -> list[ItemStats]:
        return [stats for stats in self.ranked() if stats.has_cadence]

    def partners(self, key: str, minimum: int = 2) -> list[str]:
        """Item keys bought alongside this one at least `minimum` times."""
        pairs = self.co_occurrence.get(key, {})
        return [other for other, count in sorted(pairs.items(), key=lambda kv: -kv[1]) if count >= minimum]


def build(orders: Sequence[Order]) -> Catalog:
    """Aggregate orders into a catalog."""
    catalog = Catalog(orders=list(orders))
    for order in sorted(orders, key=lambda o: o.ordered_on):
        keys_in_order: list[str] = []
        for item in order.grocery_items:
            stats = catalog.items.get(item.key)
            if stats is None:
                stats = ItemStats(
                    key=item.key,
                    name=item.name,
                    department=item.department,
                    size=item.size,
                    unit=item.unit,
                )
                catalog.items[item.key] = stats
            # Keep the most recent spelling and size; packaging changes.
            stats.name = item.name
            stats.department = item.department
            stats.size = item.size or stats.size
            stats.unit = item.unit
            stats.dates.append(order.ordered_on)
            stats.quantities.append(item.quantity)
            if item.unit_price is not None:
                stats.unit_prices.append(item.unit_price)
            stats.total_spend += item.line_total or 0.0
            keys_in_order.append(item.key)

        for key in keys_in_order:
            bucket = catalog.co_occurrence.setdefault(key, {})
            for other in keys_in_order:
                if other != key:
                    bucket[other] = bucket.get(other, 0) + 1

    return catalog
