"""Parse "Your Whole Foods Market Receipt" emails into orders.

The HTML part is the good one: it carries quantity, unit price and per-line
totals. The plain-text part lists names only, so it is used as a fallback and
the resulting order simply has no prices.

Both parts stop at 20 line items and link out to "View All Items", so a receipt
for a bigger trip is genuinely incomplete. `Order.stated_item_count` records
what the receipt claimed so the missing tail is visible downstream rather than
being mistaken for "they did not buy it".
"""

from __future__ import annotations

import email
import html as html_module
import logging
import re
from datetime import date, datetime
from email.message import Message
from pathlib import Path
from typing import Iterable

from .model import LineItem, Order, merge_duplicate_lines

log = logging.getLogger(__name__)

RECEIPT_SENDER = "wholefoodsmarket@mail.wholefoodsmarket.com"
RECEIPT_SUBJECT = "Your Whole Foods Market Receipt"

_STYLE_RE = re.compile(r"<(style|script)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# Quote-aware: Amazon's markup carries tracking URLs with ">" inside attribute
# values, and a naive <[^>]+> splits such a tag and spills the tail as text.
_TAG_RE = re.compile(r"""<(?:"[^"]*"|'[^']*'|[^'">])*>""", re.DOTALL)
# Belt and braces for markup that still slips through: real product names are
# short and free of URL and attribute punctuation.
_JUNK_RE = re.compile(r"(?:https?%?3?a?:|href=|style=|&ref_=|font-family|border-radius|<|>)", re.IGNORECASE)
MAX_ITEM_NAME = 120
_MONEY_RE = re.compile(r"^-?\$[\d,]+\.\d{2}$")
_DATE_RE = re.compile(r"\b([A-Z][a-z]{2,8} \d{1,2}, \d{4})\b")
_STORE_RE = re.compile(r"Whole Foods Market - [A-Za-z0-9 .\x27&]+?(?=\s+Order #|\s*$)")
_ITEM_COUNT_RE = re.compile(r"Items Purchased:\s*(\d+)", re.IGNORECASE)
_PROMO_RE = re.compile(r"^\$([\d,]+\.\d{2})\s+promotions? applied$", re.IGNORECASE)
_ORDER_ID_RE = re.compile(r"\b(\d{3}-\d{7}-\d{7})\b")

# "Qty: 3 @ $1.69 each" and "Qty: 0.45 lb @ $26.99/lb"
_QTY_RE = re.compile(
    r"^Qty:\s*(?P<qty>[\d,]*\.?\d+)\s*(?P<qty_unit>[a-zA-Z]+)?\s*@\s*"
    r"\$(?P<price>[\d,]+\.\d{2})\s*(?:/\s*(?P<price_unit>[a-zA-Z]+)|each)?\s*$",
    re.IGNORECASE,
)

_END_MARKERS = ("view all items", "no barcode image", "how was your trip")


class ReceiptError(ValueError):
    """A message did not look like a Whole Foods receipt."""


def _money(text: str) -> float | None:
    cleaned = text.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def visible_lines(html: str) -> list[str]:
    """Flatten receipt HTML to the text a reader would actually see."""
    without_style = _STYLE_RE.sub(" ", html)
    without_comments = _COMMENT_RE.sub(" ", without_style)
    text = _TAG_RE.sub("\n", without_comments)
    text = html_module.unescape(text)
    return [line.strip() for line in text.split("\n") if line.strip()]


def _header_value(lines: list[str], label: str) -> str | None:
    """The first value following a label line, skipping empty cells."""
    for index, line in enumerate(lines):
        if line.strip().rstrip(":").lower() == label.lower():
            for candidate in lines[index + 1 : index + 4]:
                if candidate and candidate.strip().rstrip(":").lower() != label.lower():
                    return candidate.strip()
    return None


def _money_after(lines: list[str], label: str) -> float | None:
    for index, line in enumerate(lines):
        if line.strip().rstrip(":").lower() == label.lower():
            for candidate in lines[index + 1 : index + 4]:
                if _MONEY_RE.match(candidate.strip()):
                    return _money(candidate)
    return None


def _parse_date(lines: list[str]) -> date | None:
    for line in lines:
        match = _DATE_RE.search(line)
        if not match:
            continue
        try:
            return datetime.strptime(match.group(1), "%B %d, %Y").date()
        except ValueError:
            continue
    return None


def _find_order_id(lines: list[str]) -> str | None:
    value = _header_value(lines, "Order #")
    if value:
        match = _ORDER_ID_RE.search(value)
        if match:
            return match.group(1)
    for line in lines:
        match = _ORDER_ID_RE.search(line)
        if match:
            return match.group(1)
    return None


def _item_region(lines: list[str]) -> tuple[list[str], int | None]:
    """The slice of lines holding line items, plus the receipt's own count."""
    start = None
    stated = None
    for index, line in enumerate(lines):
        match = _ITEM_COUNT_RE.search(line)
        if match:
            start = index + 1
            stated = int(match.group(1))
            break
    if start is None:
        return [], None

    end = len(lines)
    for index in range(start, len(lines)):
        lowered = lines[index].lower()
        if any(marker in lowered for marker in _END_MARKERS):
            end = index
            break
    return lines[start:end], stated


def _looks_like_item_name(line: str) -> bool:
    """Filter out stray markup that survived tag stripping."""
    if len(line) > MAX_ITEM_NAME:
        return False
    if _JUNK_RE.search(line):
        return False
    return any(char.isalpha() for char in line)


def _parse_items(region: Iterable[str]) -> list[LineItem]:
    """Walk name / qty / total / promo groups into line items."""
    items: list[LineItem] = []
    pending_name: str | None = None
    pending: dict[str, float | str | None] = {}

    def flush() -> None:
        nonlocal pending_name, pending
        if pending_name:
            items.append(
                LineItem.from_raw(
                    pending_name,
                    quantity=float(pending.get("qty") or 1.0),
                    unit=str(pending.get("unit") or "each"),
                    unit_price=pending.get("unit_price"),  # type: ignore[arg-type]
                    line_total=pending.get("line_total"),  # type: ignore[arg-type]
                    promotion=float(pending.get("promotion") or 0.0),
                )
            )
        pending_name = None
        pending = {}

    for raw in region:
        line = raw.strip()
        if not line:
            continue

        qty_match = _QTY_RE.match(line)
        if qty_match and pending_name:
            quantity = float(qty_match.group("qty").replace(",", ""))
            unit = (qty_match.group("price_unit") or qty_match.group("qty_unit") or "each").lower()
            pending["qty"] = quantity
            pending["unit"] = unit
            pending["unit_price"] = _money(qty_match.group("price"))
            continue

        promo_match = _PROMO_RE.match(line)
        if promo_match and pending_name:
            pending["promotion"] = _money(promo_match.group(1)) or 0.0
            continue

        if _MONEY_RE.match(line) and pending_name and "line_total" not in pending:
            pending["line_total"] = _money(line)
            continue

        # Anything else starts a new item; the previous one is complete.
        flush()
        if _looks_like_item_name(line):
            pending_name = line

    flush()
    return merge_duplicate_lines(items)


def parse_receipt_html(html: str, *, source: str | None = None) -> Order:
    """Build an order from the HTML part of a receipt email."""
    lines = visible_lines(html)
    return _build_order(lines, source=source, priced=True)


def parse_receipt_text(text: str, *, source: str | None = None) -> Order:
    """Build an order from the plain-text part (names only, no prices)."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return _build_order(lines, source=source, priced=False)


def _build_order(lines: list[str], *, source: str | None, priced: bool) -> Order:
    order_id = _find_order_id(lines)
    ordered_on = _parse_date(lines)
    if not order_id or not ordered_on:
        raise ReceiptError("no Whole Foods order number and date found in this message")

    region, stated = _item_region(lines)
    if priced:
        items = _parse_items(region)
    else:
        items = merge_duplicate_lines(
            LineItem.from_raw(line)
            for line in region
            if _looks_like_item_name(line)
            and not _MONEY_RE.match(line)
            and not _QTY_RE.match(line)
        )

    store = None
    for line in lines:
        match = _STORE_RE.search(line)
        if match:
            store = match.group(0).strip()
            break

    return Order(
        order_id=order_id,
        ordered_on=ordered_on,
        items=items,
        store=store,
        subtotal=_money_after(lines, "Subtotal"),
        tax=_money_after(lines, "Sales Tax"),
        total=_money_after(lines, "Total"),
        savings=_money_after(lines, "Total Savings"),
        channel="in-store",
        source=source,
        stated_item_count=stated,
    )


def parse_email_message(message: Message, *, source: str | None = None) -> Order:
    """Parse a receipt from a parsed email message, preferring the HTML part."""
    html_body: str | None = None
    text_body: str | None = None
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            decoded = payload.decode(charset, errors="replace")
        except LookupError:
            decoded = payload.decode("utf-8", errors="replace")
        if part.get_content_subtype() == "html" and html_body is None:
            html_body = decoded
        elif part.get_content_subtype() == "plain" and text_body is None:
            text_body = decoded

    if html_body:
        return parse_receipt_html(html_body, source=source)
    if text_body:
        log.warning("%s has no HTML part; parsing names only, without prices", source)
        return parse_receipt_text(text_body, source=source)
    raise ReceiptError("message has no readable body")


def parse_file(path: Path) -> Order:
    """Parse a saved .eml, .html or .txt receipt."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()
    if suffix in {".eml", ".msg"}:
        return parse_email_message(email.message_from_string(raw), source=str(path))
    if suffix in {".html", ".htm"}:
        return parse_receipt_html(raw, source=str(path))
    return parse_receipt_text(raw, source=str(path))
