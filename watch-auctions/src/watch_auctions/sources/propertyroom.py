"""PropertyRoom: auctions of recovered, seized and unclaimed property for
police departments and other agencies. Watches show up here constantly and
almost nobody who collects watches looks.
"""
from __future__ import annotations

import html
import re
import sys
import time
from datetime import datetime

from watch_auctions.http import fetch
from watch_auctions.models import Lot

NAME = "propertyroom"
BASE = "https://www.propertyroom.com"
_CARD = re.compile(r'<a href="(/l/[^"]+/(\d+))" class="listing-card"(.*?)</a>', re.S)


def _first(rx: str, s: str) -> str:
    m = re.search(rx, s, re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def _ts(s: str) -> int:
    try:
        return int(datetime.fromisoformat(s[:19] + "+00:00").timestamp())
    except ValueError:
        return 0


def parse_page(page: str) -> tuple[list[Lot], int]:
    total = int((_first(r"([\d,]+) Results", page) or "0").replace(",", ""))
    lots = []
    for path, lot_id, card in _CARD.findall(page):
        price = _first(r'listing-price">\$([\d,.]+)', card)
        bids = _first(r'listing-bids">(\d+) bid', card)
        lots.append(Lot(
            source=NAME, source_id=lot_id, title=_first(r'listing-title">([^<]+)', card), url=BASE + path,
            house="PropertyRoom (police & agency property)",
            image=_first(r'<img[^>]*src="([^"]+)"', card), sale_type="timed",
            ends_at=_ts(_first(r'data-end="([^"]+)"', card)),
            current_bid=float(price.replace(",", "")) if price else 0, bid_count=int(bids or 0),
        ))
    return lots, total


def collect(now: int, days: int, max_pages: int = 30, log=print, **_) -> list[Lot]:
    out, page, pages = [], 1, 1
    while page <= min(pages, max_pages):
        try:
            lots, total = parse_page(fetch(f"{BASE}/s/watches?page={page}&sort=closingsoon"))
        except Exception as e:
            log(f"  propertyroom page {page}: {e}", file=sys.stderr)
            break
        if not lots:
            break
        out += lots
        pages = -(-total // max(len(lots), 1)) if page == 1 else pages
        page += 1
        time.sleep(0.5)
    log(f"  propertyroom: {len(out)} lots")
    return out
