"""On-disk record of parsed orders.

Sources disagree and come and go — a receipt email today, an account export
next month — so orders are upserted by order id into one JSON file that is the
single thing the rest of the tool reads.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .model import Order

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class OrderStore:
    """Orders keyed by order id."""

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        self.schema_version: int = payload.get("schema_version", SCHEMA_VERSION)
        self.updated_at: str | None = payload.get("updated_at")
        self._orders: dict[str, dict[str, Any]] = payload.get("orders", {})

    @classmethod
    def load(cls, path: Path) -> "OrderStore":
        if not path.is_file():
            return cls()
        try:
            return cls(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("could not read orders at %s (%s); starting fresh", path, exc)
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": self.updated_at,
            "orders": self._orders,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def merge(self, orders: Iterable[Order]) -> int:
        """Upsert orders, returning how many were new or changed.

        A richer record wins: an export that itemises an order supersedes a
        receipt that only listed the first twenty lines of it.
        """
        changed = 0
        for order in orders:
            payload = order.to_dict()
            existing = self._orders.get(order.order_id)
            if existing == payload:
                continue
            if existing and len(existing.get("items", [])) > len(payload["items"]):
                log.info(
                    "keeping richer existing record for %s (%d items vs %d)",
                    order.order_id,
                    len(existing.get("items", [])),
                    len(payload["items"]),
                )
                continue
            self._orders[order.order_id] = payload
            changed += 1
        return changed

    def orders(self) -> list[Order]:
        """Every order, oldest first."""
        parsed = [Order.from_dict(raw) for raw in self._orders.values()]
        return sorted(parsed, key=lambda order: (order.ordered_on, order.order_id))

    def __len__(self) -> int:
        return len(self._orders)
