"""ShopGoodwill: online auctions run by hundreds of individual Goodwill stores.

Every store lists its own donated watches here, so this is a large pool of
lots that never go near a specialist auction. We query the site's own JSON
search API in the Watches category: once with a small price floor to skip
$5 fashion watches, and once per collector keyword with no floor (good
pieces often sit at a low bid until the last day).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from watch_auctions.http import fetch
from watch_auctions.models import Lot

NAME = "shopgoodwill"
API = "https://buyerapi.shopgoodwill.com/api/Search/ItemListing"
WATCHES = 89
KEYWORDS = ["rolex", "omega", "longines", "hamilton", "elgin", "waltham", "seiko automatic",
            "14k", "18k", "solid gold", "automatic", "chronograph", "vintage", "pocket watch",
            "swiss", "tudor", "cartier", "patek", "heuer", "breitling"]
PACIFIC = ZoneInfo("America/Los_Angeles")  # end times come back in the site's local time


def body(page: int, text: str = "", low_price: float = 0) -> dict:
    return {"searchText": text, "catIds": str(WATCHES), "categoryId": WATCHES,
            "selectedCategoryIds": str(WATCHES), "categoryLevelNo": "2", "categoryLevel": 2,
            "page": page, "pageSize": 40, "sortColumn": "1", "sortDescending": False,
            "lowPrice": str(low_price), "highPrice": "999999", "closedAuctionDaysBack": "7",
            "searchClosedAuctions": "false", "searchDescriptions": "false"}


def _ts(s: str) -> int:
    try:
        return int(datetime.fromisoformat(s[:19]).replace(tzinfo=PACIFIC).timestamp())
    except (TypeError, ValueError):
        return 0


def seller_info(seller_id: str) -> dict:
    try:
        return json.loads(fetch(f"https://buyerapi.shopgoodwill.com/api/Seller/GetSellerInfo/{seller_id}"))
    except Exception:
        return {}


def to_lot(it: dict, seller: dict | None = None) -> Lot:
    seller = seller or {}
    return Lot(
        source=NAME, source_id=str(it["itemId"]), title=(it.get("title") or "").strip(),
        url=f"https://shopgoodwill.com/item/{it['itemId']}",
        house=seller.get("companyName") or f"Goodwill store #{it.get('sellerId')}",
        city=seller.get("city") or "", state=seller.get("state") or "",
        image=(it.get("imageURL") or "").replace("\\", "/"),
        sale_type="timed", starts_at=_ts(it.get("startTime")), ends_at=_ts(it.get("endTime")),
        current_bid=float(it.get("currentPrice") or 0), bid_count=int(it.get("numBids") or 0),
    )


def _sweep(text: str, low_price: float, max_pages: int, delay: float, log) -> list[dict]:
    out, page = [], 1
    while page <= max_pages:
        try:
            r = json.loads(fetch(API, data=body(page, text, low_price),
                                 headers={"Origin": "https://shopgoodwill.com"}))["searchResults"]
        except Exception as e:
            log(f"  shopgoodwill '{text}' page {page}: {e}", file=sys.stderr)
            break
        items = r.get("items") or []
        out += items
        if len(items) < 40 or page * 40 >= int(r.get("itemCount") or 0):
            break
        page += 1
        time.sleep(delay)
    return out


def collect(now: int, days: int, min_price: float = 25, max_pages: int = 40, delay: float = 0.5,
            log=print, **_) -> list[Lot]:
    seen: dict[str, dict] = {}
    for it in _sweep("", min_price, max_pages, delay, log):
        seen[str(it["itemId"])] = it
    for kw in KEYWORDS:
        for it in _sweep(kw, 0, 5, delay, log):
            seen.setdefault(str(it["itemId"]), it)
    # One lookup per store (about a hundred) turns seller ids into names and locations.
    sellers = {sid: seller_info(sid) for sid in {str(it.get("sellerId")) for it in seen.values()}}
    lots = [to_lot(it, sellers.get(str(it.get("sellerId")))) for it in seen.values()]
    log(f"  shopgoodwill: {len(lots)} lots")
    return lots
