"""Filter, enrich and merge lots from every source into one catalog."""
from __future__ import annotations

import re

from watch_auctions.classify import detect_brand, is_major_house, is_watch
from watch_auctions import quality
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


# Sources whose query is already restricted to a watch category, so a title
# like "Bulova Accutron 218" counts even without the word "watch".
CATEGORY_FILTERED = {"liveauctioneers", "invaluable", "shopgoodwill"}


def build(lots: list[Lot], now: int, days: int, include_majors: bool = False,
          keep_garbage: bool = False, rejected: list | None = None) -> list[Lot]:
    horizon = now + days * 86400
    merged: dict[str, Lot] = {}
    for lot in lots:
        if not lot.title or not is_watch(lot.title, "watches" if lot.source in CATEGORY_FILTERED else ""):
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
        verdict = quality.score(lot)
        if verdict.rejected and not keep_garbage:
            if rejected is not None:
                rejected.append((lot, verdict.rejected))
            continue
        lot.score, lot.reasons = verdict.score, verdict.reasons
        key = dedupe_key(lot)
        if key in merged:
            first = merged[key]
            if all(a["source"] != lot.source for a in first.also_on) and first.source != lot.source:
                first.also_on.append({"source": lot.source, "url": lot.url})
            continue
        merged[key] = lot
    return rank(list(merged.values()))


# Each further lot from the same house ranks this much lower, up to the cap, so a
# dealer with forty diamond Rolexes doesn't bury every other house.
HOUSE_FATIGUE, FATIGUE_CAP = 4.0, 30.0


def rank(lots: list[Lot]) -> list[Lot]:
    """Best first; ties go to whatever closes sooner."""
    lots.sort(key=lambda l: (-l.score, l.ends_at or l.starts_at or 2**40, l.house, l.lot_number))
    seen: dict[str, int] = {}
    for l in lots:
        n = seen.get(l.house, 0)
        l.rank = l.score - min(FATIGUE_CAP, HOUSE_FATIGUE * n)
        seen[l.house] = n + 1
    return sorted(lots, key=lambda l: (-l.rank, -l.score, l.ends_at or l.starts_at or 2**40))
