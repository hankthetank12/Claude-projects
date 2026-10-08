"""Filter, enrich and merge lots from every source into one catalog."""
from __future__ import annotations

import re

from watch_auctions.classify import detect_brand, is_major_house, is_watch
from watch_auctions.models import Lot


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _house_key(name: str) -> str:
    # "Fontaine's Auction Gallery" and "Fontaines Auction Gallery, LLC" are the same house.
    words = re.sub(r"[^a-z0-9 ]", "", name.lower().replace("'", "")).split()
    stop = {"auction", "auctions", "auctioneers", "gallery", "galleries", "llc", "inc", "co", "the", "and", "company"}
    return "".join(w for w in words if w not in stop)[:20] or _norm(name)


def dedupe_key(lot: Lot) -> str:
    # Houses often simulcast one sale on both platforms; the lot number + title survive intact.
    return f"{_house_key(lot.house)}|{_norm(lot.lot_number)}|{_norm(lot.title)[:50]}"


def build(lots: list[Lot], now: int, days: int, include_majors: bool = False) -> list[Lot]:
    horizon = now + days * 86400
    merged: dict[str, Lot] = {}
    for lot in lots:
        if not lot.title or not is_watch(lot.title):
            continue
        if not include_majors and is_major_house(lot.house):
            continue
        # Live-sale lot end times are estimates; give them a few hours of slack.
        end = lot.ends_at or lot.starts_at
        if end and end < now - (6 * 3600 if lot.sale_type == "live" else 0):
            continue
        if lot.starts_at and lot.starts_at > horizon:
            continue
        lot.brand = lot.brand or detect_brand(lot.title)
        key = dedupe_key(lot)
        if key in merged:
            first = merged[key]
            if all(a["source"] != lot.source for a in first.also_on) and first.source != lot.source:
                first.also_on.append({"source": lot.source, "url": lot.url})
            continue
        merged[key] = lot
    return sorted(merged.values(), key=lambda l: (l.ends_at or l.starts_at or 2**40, l.house, l.lot_number))
