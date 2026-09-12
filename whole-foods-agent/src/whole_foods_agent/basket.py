"""Turn the catalog into a concrete proposed order.

The rule is deliberately one a person can check: an item goes on the list when
enough of its usual gap between purchases has elapsed that it should be running
out. Every line carries the numbers behind that call, so a wrong suggestion is
obvious rather than mysterious.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

from .catalog import Catalog, ItemStats

# Past this multiple of its usual gap, an item looks abandoned rather than due:
# suggesting it every week forever is how these lists lose trust.
STALE_RATIO = 3.0

# A single purchase with nothing to compare it to is a suggestion at best.
SUGGESTION_RECENT_DAYS = 120


@dataclass
class OrderLine:
    """One proposed item, with the evidence for proposing it."""

    stats: ItemStats
    due_ratio: float
    days_since: int
    interval: float
    quantity: float
    estimated_cost: float | None

    @property
    def name(self) -> str:
        return self.stats.name

    @property
    def department(self) -> str:
        return self.stats.department

    @property
    def reason(self) -> str:
        every = round(self.interval)
        return (
            f"bought {self.stats.times_bought}x, about every {every} "
            f"day{'s' if every != 1 else ''}; last {self.days_since} days ago"
        )


@dataclass
class ProposedOrder:
    """What to buy, what it should cost, and what was left off."""

    on_date: date
    lines: list[OrderLine] = field(default_factory=list)
    # Bought before but not on a measurable rhythm.
    suggestions: list[ItemStats] = field(default_factory=list)
    # Usually bought alongside something already on the list.
    partners: list[ItemStats] = field(default_factory=list)
    # Dropped to stay under budget or the item cap.
    trimmed: list[OrderLine] = field(default_factory=list)
    # Long overdue: probably no longer bought, worth a glance.
    lapsed: list[ItemStats] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def estimated_total(self) -> float:
        return round(sum(line.estimated_cost or 0.0 for line in self.lines), 2)

    @property
    def priced_lines(self) -> int:
        return sum(1 for line in self.lines if line.estimated_cost is not None)

    def by_department(self) -> dict[str, list[OrderLine]]:
        """Lines grouped for shopping, departments in a sensible walk order."""
        order = [
            "Produce",
            "Meat & seafood",
            "Dairy & eggs",
            "Bakery",
            "Pantry",
            "Frozen",
            "Beverages",
            "Snacks",
            "Household",
            "Other",
        ]
        grouped: dict[str, list[OrderLine]] = {}
        for line in self.lines:
            grouped.setdefault(line.department, []).append(line)
        for lines in grouped.values():
            lines.sort(key=lambda line: -line.due_ratio)
        return {name: grouped[name] for name in order if name in grouped}


def build(
    catalog: Catalog,
    *,
    on_date: date | None = None,
    due_threshold: float = 0.8,
    budget: float | None = None,
    max_items: int | None = None,
) -> ProposedOrder:
    """Propose the next order from buying history."""
    today = on_date or date.today()
    proposal = ProposedOrder(on_date=today)

    candidates: list[OrderLine] = []
    for stats in catalog.items.values():
        if not stats.has_cadence:
            # No rhythm to measure: offer it only if it was bought recently.
            if stats.days_since(today) <= SUGGESTION_RECENT_DAYS:
                proposal.suggestions.append(stats)
            continue

        ratio = stats.due_ratio(today)
        interval = stats.median_interval
        if ratio is None or interval is None:
            continue

        if ratio >= STALE_RATIO:
            proposal.lapsed.append(stats)
            continue

        if ratio >= due_threshold:
            candidates.append(
                OrderLine(
                    stats=stats,
                    due_ratio=ratio,
                    days_since=stats.days_since(today),
                    interval=interval,
                    quantity=stats.typical_quantity,
                    estimated_cost=stats.estimated_cost(),
                )
            )

    # Most overdue first, then the items bought most often.
    candidates.sort(key=lambda line: (-line.due_ratio, -line.stats.times_bought))

    kept: list[OrderLine] = []
    running = 0.0
    for line in candidates:
        if max_items is not None and len(kept) >= max_items:
            proposal.trimmed.append(line)
            continue
        cost = line.estimated_cost or 0.0
        if budget is not None and running + cost > budget:
            proposal.trimmed.append(line)
            continue
        kept.append(line)
        running += cost

    proposal.lines = kept

    chosen_keys = {line.stats.key for line in kept}
    partner_keys: dict[str, int] = {}
    for line in kept:
        for other in catalog.partners(line.stats.key):
            if other not in chosen_keys:
                partner_keys[other] = partner_keys.get(other, 0) + 1
    proposal.partners = [
        catalog.items[key]
        for key, _ in sorted(partner_keys.items(), key=lambda kv: -kv[1])
        if key in catalog.items
    ][:8]

    suggestion_keys = {stats.key for stats in proposal.suggestions}
    proposal.partners = [stats for stats in proposal.partners if stats.key not in suggestion_keys]
    proposal.suggestions.sort(key=lambda stats: stats.last_bought, reverse=True)
    proposal.suggestions = proposal.suggestions[:10]
    proposal.lapsed.sort(key=lambda stats: -stats.times_bought)
    proposal.lapsed = proposal.lapsed[:8]

    proposal.notes.extend(_notes(catalog, proposal, budget))
    return proposal


def _notes(catalog: Catalog, proposal: ProposedOrder, budget: float | None) -> list[str]:
    """Things the reader needs to know to trust or distrust the list."""
    notes: list[str] = []

    truncated = catalog.truncated_orders
    if truncated:
        missing = sum(
            (order.stated_item_count or 0) - len(order.items) for order in truncated
        )
        notes.append(
            f"{len(truncated)} of {len(catalog.orders)} orders were only partly "
            f"itemised by the source (about {missing} lines missing), so some "
            "regulars may be under-counted."
        )

    unpriced = len(proposal.lines) - proposal.priced_lines
    if unpriced:
        notes.append(
            f"{unpriced} item{'s' if unpriced != 1 else ''} had no price in the "
            "history, so the estimated total is low."
        )

    if budget is not None and proposal.trimmed:
        notes.append(
            f"{len(proposal.trimmed)} item{'s' if len(proposal.trimmed) != 1 else ''} "
            f"left off to stay under ${budget:.0f}."
        )

    if len(catalog.orders) < 4:
        notes.append(
            f"Only {len(catalog.orders)} orders in history — cadence estimates "
            "get materially better past about 6."
        )

    return notes
