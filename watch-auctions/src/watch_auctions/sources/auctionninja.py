"""AuctionNinja: online estate sales from hundreds of local estate-sale companies.

Each company runs its sales under its own page on the site (auctionninja.com/<company>).
The marketplace search is server-rendered HTML, so we parse the result cards.
"""
from __future__ import annotations

import html
import re
import sys
import time
import urllib.parse

from watch_auctions.http import fetch
from watch_auctions.models import Lot

NAME = "auctionninja"
BASE = "https://www.auctionninja.com"
PER_PAGE = 20

_CARD = re.compile(r'<div class="iteam-result-box" id="MainItmID_(\d+)_(\d+)">(.*?)(?=<div class="iteam-result-box"|</section|$)', re.S)


def page_url(keyword: str, page: int) -> str:
    return f"{BASE}/marketplace-items?" + urllib.parse.urlencode({"Page": page, "keyword": keyword})


def _first(rx: str, s: str) -> str:
    m = re.search(rx, s, re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def parse_page(page: str, now: int) -> tuple[list[Lot], int]:
    total = int((_first(r"([\d,]+) results", page) or "0").replace(",", ""))
    lots = []
    for auction_id, item_id, card in _CARD.findall(page):
        title = _first(r'class="hot-items-title"><a [^>]*>([^<]+)', card)
        url = _first(r'class="hot-items-title"><a href="([^"]+)"', card)
        if not title or not url:
            continue
        left = _first(rf'id="time_left_dff_{auction_id}_{item_id}" value="(\d+)"', page)
        price = _first(r'id="CURBIDID_[\d_]+"\s*>\$([\d,.]+)', card)
        loc = _first(r'hi-auction-company-title">.*?</div><p>([^<]*)</p>', card)
        city, _, state = loc.partition(", ")
        lots.append(Lot(
            source=NAME, source_id=item_id, title=title, url=url,
            house=_first(r'hi-auction-company-title"><a [^>]*>([^<]+)', card),
            city=city, state=state.strip()[:2], image=_first(r'<img class="hi-new thumb"[^>]*src="([^"]+)"', card),
            sale_type="timed", ends_at=now + int(left) if left else 0,
            current_bid=float(price.replace(",", "")) if price else 0,
        ))
    return lots, total


def collect(now: int, days: int, keywords=("watch", "rolex", "omega", "pocket watch"), max_pages: int = 30,
            delay: float = 1.0, log=print, **_) -> list[Lot]:
    seen: dict[str, Lot] = {}
    for kw in keywords:
        page, pages = 1, 1
        while page <= min(pages, max_pages):
            try:
                lots, total = parse_page(fetch(page_url(kw, page)), now)
            except Exception as e:
                log(f"  auctionninja '{kw}' page {page}: {e}", file=sys.stderr)
                break
            for l in lots:
                seen.setdefault(l.source_id, l)
            pages = -(-total // PER_PAGE)
            if not lots:
                break
            page += 1
            time.sleep(delay)
    log(f"  auctionninja: {len(seen)} lots from {len({l.house for l in seen.values()})} companies")
    return list(seen.values())
