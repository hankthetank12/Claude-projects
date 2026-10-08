"""CTBids: online estate sales run by local Caring Transitions franchise owners.

Each franchise is a small, local operator clearing out one household at a
time; their watches rarely reach a dedicated auction. We use the same public
search API the ctbids.com front end calls.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone

from watch_auctions.http import fetch
from watch_auctions.models import Lot

NAME = "ctbids"
API = "https://sale.ctbids.com/services/api/v1/search/item/new/list"
FIELDS = ["id", "title", "itemclosetime", "itemseourl", "saleid", "saletitle", "city", "state",
          "zipcode", "displayimageurl", "category", "itemstatus"]
STATE_ABBR = {"Alabama": "AL", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
              "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Idaho": "ID",
              "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY",
              "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
              "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE",
              "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
              "New York": "NY", "North Carolina": "NC", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
              "Pennsylvania": "PA", "South Carolina": "SC", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
              "Virginia": "VA", "Washington": "WA", "Wisconsin": "WI"}


def body(extra_filter: dict, size: int = 500) -> dict:
    return {"sort": [{"field": "itemclosetime", "direction": "asc"}], "page": {"size": size},
            "field": FIELDS,
            "filter": [{"field": "salestatus", "value": "Started", "op": "=", "join": "AND"},
                       {"field": "itemstatus", "value": "Ready", "op": "=", "join": "AND"},
                       {**extra_filter, "join": "AND"}]}


def _ts(s: str | None) -> int:
    # Close times come back as "YYYY-MM-DD HH:MM:SS" in UTC.
    try:
        return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
    except (TypeError, ValueError):
        return 0


def to_lot(it: dict) -> Lot:
    seo = it.get("itemseourl") or re.sub(r"[^A-Za-z0-9]+", "-", it.get("title", "")).strip("-")
    return Lot(
        source=NAME, source_id=str(it["id"]), title=(it.get("title") or "").strip(),
        url=f"https://ctbids.com/estate-sale/{it.get('saleid')}/item/{it['id']}/{seo}",
        house=f"CTBids estate sale · {it.get('city', '')}".strip(" ·"),
        city=it.get("city") or "", state=STATE_ABBR.get(it.get("state") or "", it.get("state") or ""),
        image=it.get("displayimageurl") or "", sale_title=it.get("saletitle") or "",
        sale_type="timed", ends_at=_ts(it.get("itemclosetime")),
    )


def collect(now: int, days: int, log=print, **_) -> list[Lot]:
    seen: dict[str, dict] = {}
    for flt in ({"field": "category", "value": "Watches", "op": "="},
                {"field": "title", "value": "watch", "op": "LIKE"}):
        try:
            d = json.loads(fetch(API, data=body(flt), headers={"Origin": "https://ctbids.com"}))
        except Exception as e:
            log(f"  ctbids: {e}", file=sys.stderr)
            continue
        for it in d.get("data") or []:
            seen.setdefault(str(it["id"]), it)
    lots = [to_lot(it) for it in seen.values()]
    log(f"  ctbids: {len(lots)} lots")
    return lots
