"""Bidspirit: white-label catalog and bidding platform used by ~150 small houses.

Its US portal publishes every upcoming sale and every lot in each catalog as
plain JSON on its CDN, so we walk all upcoming US sales and keep the watches.
Most of these houses (estate auctioneers in Ohio, Michigan, the Carolinas…)
aren't on the big marketplaces at all.
"""
from __future__ import annotations

import json
import re
import sys
import time

from watch_auctions.classify import is_watch
from watch_auctions.http import fetch
from watch_auctions.models import Lot

NAME = "bidspirit"
CDN = "https://bidspirit-portal.global.ssl.fastly.net/services"
IMG = "https://bidspirit-images.global.ssl.fastly.net"
SITE = "https://us.bidspirit.com/ui"


def upcoming_auctions() -> list[dict]:
    d = json.loads(fetch(f"{CDN}/portal/getHomePageData?cdnSubDomain=us&content=ART&lang=en&region=US"))
    lists = d.get("auctionsLists") or {}
    return [a for key in ("UPCOMING", "FUTURE") for a in lists.get(key) or []
            if a.get("region") == "US" and a.get("hasCatalog") is not False]


def auction_page(int_key: str) -> dict:
    return json.loads(fetch(f"{CDN}/portal/getAuctionPageData?cdnSubDomain=us&intKey={int_key}"
                            "&lang=en&withHouseData=true"))


def catalog(int_key: str) -> list[dict]:
    return json.loads(fetch(f"{CDN}/catalogs/getItems?allowEro=true&allowHidden=false"
                            f"&catalogKey={int_key}&cdnSubDomain=us&lang=en"))


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:80]


def _image(it: dict) -> str:
    imgs = it.get("imagesList") or []
    if not imgs:
        return ""
    first = imgs[0]
    stem = first.rsplit(".", 1)[0]
    return f"{IMG}/{it['houseCode']}/cloned-images/{it.get('imagesBase')}/{stem}/a_ignore_q_80_w_400_h_400_c_fit_{first}"


def _price(s: str) -> tuple[float, float]:
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", s or "")]
    return (nums[0], nums[1]) if len(nums) >= 2 else ((nums[0], 0) if nums else (0, 0))


def to_lot(it: dict, auction: dict, house: dict) -> Lot:
    key, lot_id = auction["intKey"], it.get("idInApp") or it["id"]
    lo, hi = _price(it.get("estimatedPrice", ""))
    start = int(auction.get("startTimeMillis") or 0) // 1000
    expire = int(it.get("expireTime") or 0) // 1000
    return Lot(
        source=NAME, source_id=f"{key}:{lot_id}", title=(it.get("name") or "").strip(),
        url=f"{SITE}/lotPage/{it['houseCode']}/source/catalog/auction/{key}/lot/{lot_id}/{_slug(it.get('name', ''))}",
        house=house.get("name") or it["houseCode"], city=house.get("city") or "",
        state=house.get("stateCode") or "", image=_image(it), lot_number=str(it.get("itemIndex", "")),
        sale_title=auction.get("name") or "",
        sale_type="timed" if auction.get("timedAuction") else "live",
        starts_at=start, ends_at=expire or start, estimate_low=lo, estimate_high=hi,
    )


def collect(now: int, days: int, delay: float = 0.3, log=print, **_) -> list[Lot]:
    horizon = now + days * 86400
    try:
        auctions = upcoming_auctions()
    except Exception as e:
        log(f"  bidspirit: {e}", file=sys.stderr)
        return []
    out: list[Lot] = []
    houses: set[str] = set()
    for a in auctions:
        try:
            page = auction_page(a["intKey"])
            auction, house = page.get("auction") or a, page.get("house") or {}
            start = int(auction.get("startTimeMillis") or 0) // 1000
            if start and start > horizon:
                continue
            items = catalog(a["intKey"])
        except Exception as e:
            log(f"  bidspirit {a.get('houseCode')}/{a.get('intKey')}: {e}", file=sys.stderr)
            continue
        watches = [to_lot(it, auction, house) for it in items
                   if not it.get("removedFromAuction") and is_watch(it.get("name", ""), it.get("category") or "")]
        if watches:
            houses.add(house.get("name") or a["houseCode"])
        out += watches
        time.sleep(delay)
    log(f"  bidspirit: {len(out)} lots from {len(houses)} houses ({len(auctions)} sales scanned)")
    return out
