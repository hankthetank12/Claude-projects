"""LiveAuctioneers: hundreds of small US houses run their catalogs through it.

We call the same JSON search endpoint the site's own pages use. The watch
category is dominated by a handful of bulk dealers that run perpetual sales
with thousands of lots each; those are excluded server-side (by house id) so
the paging budget goes to the small houses instead.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse

from watch_auctions.classify import is_major_house
from watch_auctions.http import fetch
from watch_auctions.models import Lot

NAME = "liveauctioneers"
BASE = "https://www.liveauctioneers.com"
API = "https://search-party-prod.liveauctioneers.com/search/v4/web"
WATCHES_CATEGORY = "97"
PAGE_SIZE = 120


def search_params(page: int, exclude: list[str], page_size: int = PAGE_SIZE) -> dict:
    return {
        "analyticsTags": ["web"], "categories": [WATCHES_CATEGORY], "distance": {},
        "options": {"status": ["upcoming", "live", "online"], "countryCode": ["US"],
                    "saleType": ["liveAuction", "timedAuction", "timedPlusAuction"],
                    "auctionHouse": [{"exclude": exclude, "include": []}]},
        "page": page, "pageSize": page_size, "publishDate": {}, "ranges": {}, "saleDate": {},
        "searchTerm": "", "sort": "saleStart", "facetOverrides": {"auctionHouse": {"size": 300}},
    }


def search(params: dict) -> dict:
    url = f"{API}?parameters={urllib.parse.quote(json.dumps(params))}"
    d = json.loads(fetch(url, headers={"Referer": BASE + "/", "Origin": BASE}))
    if d.get("error"):
        raise RuntimeError(f"search error: {d.get('payload')}")
    return d["payload"]


def houses_to_skip(payload: dict, max_house_lots: int) -> list[tuple[str, str, int]]:
    out = []
    for facet in payload.get("facets") or []:
        if facet.get("id") != "auctionHouse":
            continue
        for o in facet.get("options") or []:
            name, count = o.get("label") or o.get("name") or "", int(o.get("count") or 0)
            if count > max_house_lots or is_major_house(name):
                out.append((str(o["id"]), name, count))
    return out


def to_lot(it: dict) -> Lot:
    item_id = it["itemId"]
    image = ""
    if it.get("photos"):
        image = (f"https://p1.liveauctioneers.com/{it['sellerId']}/{it['catalogId']}/"
                 f"{item_id}_1_m.jpg?version={it.get('imageVersion', 0)}")
    return Lot(
        source=NAME, source_id=str(item_id), title=(it.get("title") or "").strip(),
        url=f"{BASE}/item/{item_id}_{it.get('slug', '')}",
        house=it.get("sellerName", ""), city=it.get("sellerCity", ""),
        state=it.get("sellerStateCode", ""), image=image,
        lot_number=str(it.get("lotNumber", "")).lstrip("0"),
        sale_title=it.get("catalogTitle", ""),
        sale_type="timed" if it.get("isTimedAuction") or it.get("isTimedPlusAuction") else "live",
        starts_at=int(it.get("saleStartTs") or 0),
        ends_at=int(it.get("lotEndTimeEstimatedTs") or 0),
        currency=it.get("currency") or "USD",
        estimate_low=it.get("lowBidEstimate") or 0, estimate_high=it.get("highBidEstimate") or 0,
        current_bid=it.get("leadingBid") or 0, bid_count=it.get("bidCount") or 0,
    )


def collect(now: int, days: int, max_pages: int = 60, max_house_lots: int = 400,
            delay: float = 1.0, log=print, **_) -> list[Lot]:
    horizon = now + days * 86400
    first = search(search_params(1, [], page_size=1))
    skip = houses_to_skip(first, max_house_lots)
    if skip:
        log("  liveauctioneers: skipping bulk dealers / majors: "
            + ", ".join(f"{n} ({c})" for _, n, c in skip))
    exclude = [i for i, _, _ in skip]
    out: list[Lot] = []
    page, pages = 1, 1
    while page <= min(pages, max_pages):
        try:
            p = search(search_params(page, exclude))
        except Exception as e:  # keep what we have; one bad page shouldn't sink the run
            log(f"  liveauctioneers page {page}: {e}", file=sys.stderr)
            break
        lots = [to_lot(it) for it in p.get("items") or []]
        out.extend(lots)
        pages = int(p.get("totalPages") or 0)
        # Sorted by sale start, so once a whole page starts past the horizon we're done.
        if not lots or min(l.starts_at for l in lots) > horizon:
            break
        page += 1
        time.sleep(delay)
    log(f"  liveauctioneers: {len(out)} lots from {page if pages else 0} of {pages} pages")
    return out
