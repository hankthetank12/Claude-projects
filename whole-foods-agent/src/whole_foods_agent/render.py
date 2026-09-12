"""Render a proposed order as text and as a self-contained HTML order sheet.

The HTML is one file with no external requests so it can be opened from disk,
mailed as an attachment, or put on a phone. Every line carries the reasoning
that put it there, because a list you cannot audit is a list you stop trusting.
"""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

from .basket import OrderLine, ProposedOrder
from .catalog import ItemStats

ASSETS = Path(__file__).resolve().parent / "assets"

# Whole Foods lives inside Amazon's storefront; this brand id is the one their
# own receipt emails link to, so search lands in the grocery catalogue rather
# than general Amazon results. Opens the Amazon app on a phone.
WFM_BRAND_ID = "VUZHIFdob2xlIEZvb2Rz"
SEARCH_URL = "https://www.amazon.com/s?k={query}&almBrandId=" + WFM_BRAND_ID
PRODUCT_URL = "https://www.amazon.com/dp/{product_id}"


def search_url(name: str) -> str:
    """A deep link that opens this product's search in the Amazon app."""
    return SEARCH_URL.format(query=quote_plus(name))


def item_url(name: str, product_id: str | None = None) -> str:
    """The best link available: the exact product when its id is known.

    History from an account export records an ASIN, so the link lands on the
    product itself. History from a receipt email has only a name, so the link
    can only be a search and the reader picks.
    """
    if product_id:
        return PRODUCT_URL.format(product_id=quote_plus(product_id))
    return search_url(name)


def _quantity_label(line: OrderLine) -> str:
    if line.stats.unit != "each":
        return f"{line.quantity:g} {line.stats.unit}"
    if abs(line.quantity - round(line.quantity)) < 0.01:
        return f"{int(round(line.quantity))}"
    return f"{line.quantity:g}"


def render_text(proposal: ProposedOrder, *, store_note: str | None = None) -> str:
    """The plain list, for pasting into a notes or shopping app."""
    out: list[str] = []
    out.append(f"Whole Foods order for {proposal.on_date:%A %-d %B %Y}")
    if store_note:
        out.append(store_note)
    out.append("")

    if not proposal.lines:
        out.append("Nothing is due yet.")
    for department, lines in proposal.by_department().items():
        out.append(f"{department.upper()}")
        for line in lines:
            cost = f"  ~${line.estimated_cost:.2f}" if line.estimated_cost is not None else ""
            out.append(f"  [ ] {_quantity_label(line)} x {line.name}{cost}")
            out.append(f"        {line.reason}")
        out.append("")

    if proposal.lines:
        out.append(f"Estimated total: ${proposal.estimated_total:.2f} for {len(proposal.lines)} items")
        out.append("")

    if proposal.partners:
        out.append("Often bought alongside these:")
        out.extend(f"  - {stats.name}" for stats in proposal.partners)
        out.append("")

    if proposal.suggestions:
        out.append("Bought before, no regular rhythm yet:")
        out.extend(
            f"  - {stats.name} (last {stats.last_bought:%-d %b})"
            for stats in proposal.suggestions
        )
        out.append("")

    if proposal.lapsed:
        out.append("Long overdue — dropped from the rotation?")
        out.extend(
            f"  - {stats.name} (last {stats.last_bought:%-d %b}, was every "
            f"~{round(stats.median_interval or 0)}d)"
            for stats in proposal.lapsed
        )
        out.append("")

    if proposal.notes:
        out.append("Worth knowing:")
        out.extend(f"  * {note}" for note in proposal.notes)

    return "\n".join(out).rstrip() + "\n"


def _item_li(line: OrderLine) -> str:
    cost = line.estimated_cost
    price = f"${cost:.2f}" if cost is not None else "—"
    quantity = _quantity_label(line)
    plain = f"{quantity} x {line.name}"
    chip = ""
    if line.due_ratio >= 1.5:
        chip = '<span class="chip">overdue</span>'
    return (
        f'<li class="item" data-cost="{cost or 0:.2f}" data-plain="{html.escape(plain, quote=True)}">'
        f'<input type="checkbox">'
        f'<div class="body">'
        f'<div class="name">{html.escape(line.name)}{chip}</div>'
        f'<div class="qty">{html.escape(quantity)}'
        f'{" · " + html.escape(line.stats.size) if line.stats.size else ""}</div>'
        f'<div class="why">{html.escape(line.reason)}</div>'
        f"</div>"
        f'<div class="right"><span class="price">{price}</span>'
        f'<a class="find" href="'
        f'{html.escape(item_url(line.name, line.stats.product_id), quote=True)}" '
        f'target="_blank" rel="noopener">'
        f'{"Open in app" if line.stats.product_id else "Find in app"}</a></div>'
        f"</li>"
    )


def _minor_list(title: str, entries: list[ItemStats], describe) -> str:
    if not entries:
        return ""
    rows = "".join(
        f'<div class="minor">{html.escape(stats.name)} — {html.escape(describe(stats))} '
        f'<a class="find" href="'
        f'{html.escape(item_url(stats.name, stats.product_id), quote=True)}" '
        f'target="_blank" rel="noopener">Find</a></div>'
        for stats in entries
    )
    return f"<details><summary>{html.escape(title)}</summary>{rows}</details>"


def render_html(
    proposal: ProposedOrder,
    *,
    order_count: int,
    title: str = "Whole Foods order",
    banner: str | None = None,
) -> str:
    """The full order sheet: one file, no external requests."""
    css = (ASSETS / "order.css").read_text(encoding="utf-8")
    js = (ASSETS / "order.js").read_text(encoding="utf-8")

    sections: list[str] = []
    if proposal.lines:
        for department, lines in proposal.by_department().items():
            body = "".join(_item_li(line) for line in lines)
            sections.append(f"<section><h2>{html.escape(department)}</h2><ul>{body}</ul></section>")
    else:
        sections.append(
            '<section><p class="sub">Nothing is due yet based on the usual '
            "buying rhythm.</p></section>"
        )

    extras = "".join(
        [
            _minor_list(
                f"Often bought alongside these ({len(proposal.partners)})",
                proposal.partners,
                lambda s: f"bought {s.times_bought}x",
            ),
            _minor_list(
                f"Bought before, no rhythm yet ({len(proposal.suggestions)})",
                proposal.suggestions,
                lambda s: f"last {s.last_bought:%-d %b}",
            ),
            _minor_list(
                f"Long overdue, maybe dropped ({len(proposal.lapsed)})",
                proposal.lapsed,
                lambda s: f"last {s.last_bought:%-d %b}, was every ~{round(s.median_interval or 0)}d",
            ),
        ]
    )

    notes = "".join(f'<div class="note">{html.escape(note)}</div>' for note in proposal.notes)
    banner_html = f'<div class="note">{html.escape(banner)}</div>' if banner else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>{html.escape(title)}</h1>
  <div class="sub">{proposal.on_date:%A %-d %B %Y} · built from {order_count} past orders</div>
  {banner_html}
  <div class="totals">
    <div class="stat"><div class="n">{len(proposal.lines)}</div><div class="l">items due</div></div>
    <div class="stat"><div class="n">${proposal.estimated_total:.2f}</div><div class="l">est. total</div></div>
    <div class="stat"><div class="n">{order_count}</div><div class="l">orders learned from</div></div>
  </div>
  {notes}
</header>
{"".join(sections)}
{extras}
<div class="bar"><span id="remaining"></span><button id="copy">Copy list</button></div>
<footer>
  Estimates use the most recent price paid for each item and the quantity usually
  bought; actual prices and availability are whatever the store says today.
  &ldquo;Find in app&rdquo; opens a Whole Foods search on Amazon.
</footer>
</div>
<script>{js}</script>
</body>
</html>
"""


def write_html(proposal: ProposedOrder, target: Path, *, order_count: int, **kwargs) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_html(proposal, order_count=order_count, **kwargs), encoding="utf-8")
    return target


def subject(proposal: ProposedOrder) -> str:
    if not proposal.lines:
        return f"Whole Foods: nothing due ({proposal.on_date:%-d %b})"
    return (
        f"Whole Foods: {len(proposal.lines)} items due, "
        f"about ${proposal.estimated_total:.0f} ({proposal.on_date:%-d %b})"
    )


def today() -> date:
    return date.today()
