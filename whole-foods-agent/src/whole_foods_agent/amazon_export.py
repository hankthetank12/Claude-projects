"""Read an Amazon account data export into orders.

Amazon's "Request My Data" (Your Account -> Data and Privacy) returns the
account's own order history as CSV. It is the fuller source: it itemises
delivery orders, which the confirmation emails never do, it is not capped at
twenty lines the way a receipt email is, and crucially it records an **ASIN**
per line. A receipt email gives a product name only, and a name is ambiguous;
an ASIN is not.

The export's column names have changed between vintages (the current
`Retail.OrderHistory` export and the older order history report disagree on
nearly every heading), so columns are matched by alias rather than by position
and a file missing something essential says which heading it could not find.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from .model import LineItem, Order, merge_duplicate_lines

log = logging.getLogger(__name__)

# Heading aliases, lower-cased and stripped of punctuation for matching.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "order_id": ("order id", "orderid", "amazon order id"),
    "ordered_on": ("order date", "order placed date", "shipment date", "ship date"),
    "name": ("product name", "title", "item name", "description"),
    "quantity": ("original quantity", "quantity", "qty", "item quantity"),
    "unit_price": ("unit price", "purchase price per unit", "per unit price", "item price"),
    "line_total": ("total amount", "total owed", "item subtotal", "item total"),
    "product_id": ("asin", "asin isbn", "asin/isbn", "product id"),
    "website": ("website", "store", "marketplace"),
    "status": ("order status", "shipment status"),
}

# Rows in these states were never actually bought.
CANCELLED_STATES = ("cancelled", "canceled")

# Which storefronts count as grocery. The export covers every Amazon purchase,
# and a year of books and batteries would drown the shopping signal.
GROCERY_STORES = ("whole foods", "wholefoods", "amazon fresh", "amazon go")

_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%B %d, %Y",
    "%d %B %Y",
)

_MONEY_CHARS = re.compile(r"[^\d.\-]")


class ExportError(ValueError):
    """The file did not look like an Amazon order export."""


def _normalise(heading: str) -> str:
    cleaned = heading.replace("﻿", "").strip().lower()
    return re.sub(r"[^a-z0-9]+", " ", cleaned).strip()


def map_columns(headings: Sequence[str]) -> dict[str, str]:
    """Map our field names onto this file's actual column headings."""
    normalised = {_normalise(heading): heading for heading in headings if heading}
    mapping: dict[str, str] = {}
    for field, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            key = _normalise(alias)
            if key in normalised:
                mapping[field] = normalised[key]
                break
    return mapping


def _parse_date(raw: str) -> date | None:
    value = (raw or "").strip()
    if not value:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    # Fall back to a leading ISO date inside a longer timestamp.
    match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    if match:
        try:
            return date.fromisoformat(match.group(1))
        except ValueError:
            return None
    return None


def _parse_money(raw: str) -> float | None:
    value = _MONEY_CHARS.sub("", (raw or "").strip())
    if not value or value in {"-", "."}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_quantity(raw: str) -> float:
    value = (raw or "").strip()
    if not value:
        return 1.0
    try:
        return float(value)
    except ValueError:
        return 1.0


def _is_grocery(website: str, stores: Iterable[str]) -> bool:
    lowered = (website or "").lower()
    return any(store in lowered for store in stores)


def parse_rows(
    rows: Iterable[dict[str, str]],
    mapping: dict[str, str],
    *,
    stores: Sequence[str] | None = GROCERY_STORES,
    source: str | None = None,
) -> list[Order]:
    """Group export rows into orders.

    One order spans several rows, one per product, so rows are collected by
    order id and the order's date is the earliest date seen on its rows.
    """
    grouped: dict[str, list[LineItem]] = {}
    dates: dict[str, date] = {}
    websites: dict[str, str] = {}
    skipped_store = 0
    skipped_unusable = 0

    for row in rows:
        website = row.get(mapping.get("website", ""), "") or ""
        if stores and not _is_grocery(website, stores):
            skipped_store += 1
            continue

        status = (row.get(mapping.get("status", ""), "") or "").strip().lower()
        if any(state in status for state in CANCELLED_STATES):
            skipped_unusable += 1
            continue

        order_id = (row.get(mapping.get("order_id", ""), "") or "").strip()
        name = (row.get(mapping.get("name", ""), "") or "").strip()
        ordered_on = _parse_date(row.get(mapping.get("ordered_on", ""), ""))
        if not order_id or not name or ordered_on is None:
            skipped_unusable += 1
            continue

        quantity = _parse_quantity(row.get(mapping.get("quantity", ""), ""))
        unit_price = _parse_money(row.get(mapping.get("unit_price", ""), ""))
        line_total = _parse_money(row.get(mapping.get("line_total", ""), ""))
        if unit_price is None and line_total is not None and quantity:
            unit_price = round(line_total / quantity, 2)
        if line_total is None and unit_price is not None:
            line_total = round(unit_price * quantity, 2)

        product_id = (row.get(mapping.get("product_id", ""), "") or "").strip() or None

        grouped.setdefault(order_id, []).append(
            LineItem.from_raw(
                name,
                quantity=quantity,
                unit="each",
                unit_price=unit_price,
                line_total=line_total,
                product_id=product_id,
            )
        )
        # An order's rows can carry different shipment dates; the earliest is
        # when it was actually bought.
        if order_id not in dates or ordered_on < dates[order_id]:
            dates[order_id] = ordered_on
        websites.setdefault(order_id, website)

    if skipped_store:
        log.info("skipped %d rows from non-grocery storefronts", skipped_store)
    if skipped_unusable:
        log.warning("skipped %d rows missing an id, name or date", skipped_unusable)

    orders: list[Order] = []
    for order_id, items in grouped.items():
        merged = merge_duplicate_lines(items)
        _repair_order_level_totals(order_id, merged)
        subtotal = sum(item.line_total or 0.0 for item in merged)
        orders.append(
            Order(
                order_id=order_id,
                ordered_on=dates[order_id],
                items=merged,
                store=websites.get(order_id) or None,
                subtotal=round(subtotal, 2) if subtotal else None,
                total=round(subtotal, 2) if subtotal else None,
                channel="delivery",
                source=source,
                # The export lists every line, so nothing is missing.
                stated_item_count=None,
            )
        )
    return sorted(orders, key=lambda order: order.ordered_on)


def _repair_order_level_totals(order_id: str, items: list[LineItem]) -> None:
    """Undo a total column that is really the order subtotal.

    The current export repeats the order's subtotal on every row of the order.
    Taken at face value that multiplies an order's spend by its line count, so
    a value identical across lines whose unit prices differ is treated as
    order-level and each line is recomputed from its own price.
    """
    if len(items) < 2:
        return
    totals = {item.line_total for item in items if item.line_total is not None}
    prices = {item.unit_price for item in items if item.unit_price is not None}
    if len(totals) != 1 or len(prices) < 2:
        return
    log.info("%s: total column looks order-level; recomputing line totals", order_id)
    for item in items:
        if item.unit_price is not None:
            item.line_total = round(item.unit_price * item.quantity, 2)


def _open_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ExportError(f"{path} has no header row")
        return list(reader), list(reader.fieldnames)


def parse_export(
    path: Path,
    *,
    stores: Sequence[str] | None = GROCERY_STORES,
) -> list[Order]:
    """Parse one export CSV into orders."""
    rows, headings = _open_rows(path)
    mapping = map_columns(headings)

    missing = [field for field in ("order_id", "ordered_on", "name") if field not in mapping]
    if missing:
        raise ExportError(
            f"{path.name} does not look like an Amazon order export: no column "
            f"for {', '.join(missing)}. Found: {', '.join(headings[:12])}"
        )
    if "website" not in mapping and stores:
        log.warning(
            "%s has no storefront column, so every row is kept; pass --all-stores "
            "deliberately or filter the file first",
            path.name,
        )
        stores = None

    return parse_rows(rows, mapping, stores=stores, source=str(path))


def find_exports(root: Path) -> Iterator[Path]:
    """Order-history CSVs inside an unzipped export, ignoring the rest."""
    if root.is_file():
        yield root
        return
    for candidate in sorted(root.rglob("*.csv")):
        name = candidate.name.lower()
        if "order" in name and "history" in name:
            yield candidate
        elif name.startswith("retail.orderhistory"):
            yield candidate
