"""EBTH (Everything But The House): online estate sales, one household at a time.

The site's JSON search API needs the public API key it embeds in every page,
so we read that first.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime

from watch_auctions.http import fetch
from watch_auctions.models import Lot

NAME = "ebth"
BASE = "https://www.ebth.com"
QUERIES = ["watch", "wristwatch", "pocket watch", "rolex", "omega"]


def api_key() -> str:
    m = re.search(r'apiKey\s*=\s*"([a-f0-9]{32})"', fetch(BASE + "/browse"))
    if not m:
        raise RuntimeError("EBTH page no longer embeds an API key")
    return m.group(1)


def _ts(s: str | None) -> int:
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except (AttributeError, ValueError):
        return 0


def to_lot(it: dict) -> Lot:
    city, _, state = (it.get("pickup_city_state") or "").partition(", ")
    return Lot(
        source=NAME, source_id=str(it["id"]), title=(it.get("name") or "").strip(),
        url=BASE + (it.get("public_url") or f"/items/{it['id']}"),
        house="EBTH estate sale", city=city, state=state[:2], image=it.get("main_image") or "",
        sale_type="timed", starts_at=_ts(it.get("sale_starts_at")), ends_at=_ts(it.get("sale_ends_at")),
        current_bid=float(it.get("high_bid_amount") or 0), bid_count=int(it.get("bids_count") or 0),
    )


def collect(now: int, days: int, log=print, **_) -> list[Lot]:
    try:
        headers = {"Authorization": f"Token token={api_key()}", "X-Requested-With": "XMLHttpRequest"}
    except Exception as e:
        log(f"  ebth: {e}", file=sys.stderr)
        return []
    seen: dict[str, Lot] = {}
    for q in QUERIES:
        page, pages = 1, 1
        while page <= min(pages, 10):
            try:
                d = json.loads(fetch(f"{BASE}/api/v1/twosearch/items?only[]=items&only[]=pages&page={page}"
                                     f"&path=%2Fbrowse&per_page=48&q={q.replace(' ', '+')}", headers=headers))
            except Exception as e:
                log(f"  ebth '{q}': {e}", file=sys.stderr)
                break
            for it in d.get("items") or []:
                if it.get("aasm_state") == "for_sale":
                    seen.setdefault(str(it["id"]), to_lot(it))
            pages = int((d.get("pages") or {}).get("total_pages") or 1)
            page += 1
    log(f"  ebth: {len(seen)} lots")
    return list(seen.values())
