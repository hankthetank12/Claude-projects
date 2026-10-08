"""AuctionMethod: white-label software small houses run as their *own* bidding site.

There is no central marketplace, so each house site has to be registered in
houses.json (`watch-auctions add-house <url>` detects the engine and adds it).
Every AuctionMethod site exposes the same JSON endpoints its catalog pages use.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request

from watch_auctions.classify import is_watch
from watch_auctions.http import USER_AGENT
from watch_auctions.models import Lot

NAME = "auctionmethod"


def _post(base: str, path: str, form: dict) -> dict:
    body = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(base.rstrip("/") + path, data=body, headers={
        "User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def open_auctions(base: str) -> list[dict]:
    d = _post(base, "/api/auctions", {"past_sales": "false"})
    rows = d.get("data") if isinstance(d, dict) else d
    if isinstance(rows, dict):
        rows = rows.get("auctions") or []
    return [a for a in rows or [] if str(a.get("completed", "0")) != "1" and a.get("status") != "completed"]


def items(base: str, auction_id: str, max_pages: int = 50) -> list[dict]:
    out, page, pages = [], 1, 1
    while page <= min(pages, max_pages):
        d = _post(base, "/api/getitems", {"auction_id": auction_id, "page": page})
        out += d.get("items") or []
        pages = int(d.get("total_pages") or 1)
        page += 1
    return out


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return 0


def to_lot(it: dict, auction: dict, house: dict, base: str) -> Lot:
    url = it.get("url") or f"{base.rstrip('/')}/auction/{auction.get('auction_id_slug', auction.get('id'))}/item/{it.get('item_id_slug') or it.get('item_id')}"
    image = it.get("thumb_url") or it.get("image") or ""
    if not image and isinstance(it.get("images"), list) and it["images"]:
        first = it["images"][0]
        image = first.get("thumb_url") or first.get("image_url") or "" if isinstance(first, dict) else str(first)
    return Lot(
        source=NAME, source_id=f"{urllib.parse.urlparse(base).netloc}:{it.get('item_id') or it.get('id')}",
        title=(it.get("title") or "").strip(), url=url, house=house["name"],
        city=house.get("city", ""), state=house.get("state", ""), image=image,
        lot_number=str(it.get("lot_number") or ""), sale_title=auction.get("title", ""),
        sale_type="timed", ends_at=int(_num(it.get("end_time_unix") or auction.get("end_time_unix"))),
        current_bid=_num(it.get("current_bid")), bid_count=int(_num(it.get("bid_count") or 0)),
    )


def collect(now: int, days: int, houses: list[dict] | None = None, log=print, **_) -> list[Lot]:
    sites = [h for h in houses or [] if h.get("engine") == NAME]
    out: list[Lot] = []
    for h in sites:
        try:
            for a in open_auctions(h["url"]):
                for it in items(h["url"], str(a["id"])):
                    if is_watch(it.get("title", ""), str(it.get("category", ""))):
                        out.append(to_lot(it, a, h, h["url"]))
                time.sleep(0.5)
        except Exception as e:
            log(f"  auctionmethod {h['name']}: {e}", file=sys.stderr)
    log(f"  auctionmethod: {len(out)} lots from {len(sites)} registered house sites")
    return out
