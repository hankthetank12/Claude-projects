"""BidWrangler: white-label bidding sites for small regional auctioneers.

Each client runs its catalog at its own host (bid.<house>.com or
<house>.bidwrangler.com) with the same public JSON API. There is no shared
marketplace, so houses come from houses.json (engine "bidwrangler").
"""
from __future__ import annotations

import json
import sys
import time

from watch_auctions.classify import is_watch
from watch_auctions.http import fetch
from watch_auctions.models import Lot

NAME = "bidwrangler"
OPEN = {"accepting_bids", "pending"}


def _get(host: str, path: str) -> dict:
    return json.loads(fetch(f"https://{host}{path}", headers={"Accept": "application/json"}))


def open_auctions(host: str) -> list[dict]:
    return [a for a in _get(host, "/api/auctions").get("auctions") or [] if a.get("status") in OPEN]


def auction_items(host: str, auction_id, max_pages: int = 20) -> list[dict]:
    out, page = [], 1
    while page <= max_pages:
        d = _get(host, f"/api/auctions/{auction_id}/items?per_page=500&page={page}")
        items = d.get("items") or []
        out += items
        if len(items) < 500 or len(out) >= int(d.get("total") or 0):
            break
        page += 1
    return out


def to_lot(it: dict, auction: dict, host: str) -> Lot:
    state = it.get("api_bidding_state") or {}
    loc = auction.get("location") or {}
    images = it.get("images") or []
    return Lot(
        source=NAME, source_id=f"{host}:{it['id']}", title=(it.get("name") or "").strip(),
        url=f"https://{host}/ui/auctions/{auction['id']}/{it['id']}",
        house=(auction.get("company") or {}).get("name") or auction.get("contact_company") or host,
        city=loc.get("city") or "", state=loc.get("state") or "",
        image=(images[0].get("sm") or images[0].get("xs") or "") if images and isinstance(images[0], dict) else "",
        lot_number=(it.get("simple_id") or "").lstrip("#"), sale_title=auction.get("name") or "",
        sale_type="timed" if auction.get("online_only") else "live",
        starts_at=int(it.get("estimated_begin_time_unix") or auction.get("starts_at_unix") or 0),
        ends_at=int(it.get("scheduled_end_time_unix") or auction.get("scheduled_end_time_unix") or 0),
        current_bid=float(((state.get("high") or {}).get("amount")) or 0),
        bid_count=int(state.get("accepted_bid_count") or 0),
    )


def collect(now: int, days: int, houses: list[dict] | None = None, log=print, **_) -> list[Lot]:
    horizon = now + days * 86400
    sites = [h for h in houses or [] if h.get("engine") == NAME]
    out: list[Lot] = []
    for h in sites:
        host = h["url"].split("//")[-1].split("/")[0]
        try:
            for a in open_auctions(host):
                if int(a.get("starts_at_unix") or 0) > horizon:
                    continue
                out += [to_lot(it, a, host) for it in auction_items(host, a["id"])
                        if is_watch(it.get("name") or "")]
                time.sleep(0.2)
        except Exception as e:
            log(f"  bidwrangler {h['name']}: {e}", file=sys.stderr)
    log(f"  bidwrangler: {len(out)} lots from {len(sites)} registered house sites")
    return out
