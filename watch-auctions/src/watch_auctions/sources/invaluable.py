"""Invaluable: the other big white-label host for small US houses.

Its public site search runs on Algolia with a search-only key embedded in the
page; we query the same index the site does.
"""
from __future__ import annotations

import json
import re
import sys

from watch_auctions.http import fetch
from watch_auctions.models import Lot

NAME = "invaluable"
APP_ID = "0HJBNDV358"
# Public, search-only key served to every visitor of invaluable.com/search.
API_KEY = "c72467a0649841b28a88222132bef0ea"
INDEX = "upcoming_lots_dateTimeUTCUnix_asc_prod"
CATEGORIES = ["Watches, Men's", "Watches, Women's", "Pocket Watches"]
STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL",
    "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
    "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA",
    "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def query(now: int, horizon: int, page: int, category: str) -> dict:
    return {
        "query": "", "hitsPerPage": 500, "page": page,
        # Live sales have no end time (0), so "not over yet" is end>now OR end=0.
        "numericFilters": [[f"endTimeUTCUnix>{now}", "endTimeUTCUnix=0"], f"dateTimeUTCUnix<{horizon}"],
        "facetFilters": ["closed:false", "countryName:United States of America",
                         f"categoryName:{category}"],
        "attributesToRetrieve": ["*"], "attributesToHighlight": [],
    }


def to_lot(h: dict) -> Lot:
    loc = [p.strip() for p in (h.get("location") or "").split(",")]
    return Lot(
        source=NAME, source_id=str(h.get("lotRef") or h["objectID"]),
        title=(h.get("lotTitle") or "").strip(),
        url="https://www.invaluable.com/auction-lot/"
            f"{slug(h.get('lotTitle', ''))}-{slug(str(h.get('lotNumber', '')))}-c-{slug(h.get('lotRef', ''))}",
        house=h.get("houseName", ""), city=loc[0] if loc else "",
        state=STATES.get(h.get("stateName", ""), loc[1] if len(loc) > 1 else ""),
        image=f"https://image.invaluable.com/housePhotos/{h['photoPath']}" if h.get("photoPath") else "",
        lot_number=str(h.get("lotNumber", "")),
        sale_type="timed" if (h.get("saleType") or "").lower().startswith("timed") else "live",
        starts_at=int(h.get("dateTimeUTCUnix") or 0), ends_at=int(h.get("endTimeUTCUnix") or 0),
        currency=h.get("currencyCode") or "USD",
        estimate_low=h.get("estimateLow") or 0, estimate_high=h.get("estimateHigh") or 0,
        current_bid=h.get("currentBid") or 0, bid_count=h.get("bidCount") or 0,
    )


def collect(now: int, days: int, log=print, **_) -> list[Lot]:
    url = f"https://{APP_ID.lower()}-dsn.algolia.net/1/indexes/{INDEX}/query"
    headers = {"X-Algolia-Application-Id": APP_ID, "X-Algolia-API-Key": API_KEY,
               "Referer": "https://www.invaluable.com/", "Origin": "https://www.invaluable.com"}
    out: list[Lot] = []
    # Algolia stops paging at 1000 hits per query, so ask one category at a time.
    for category in CATEGORIES:
        out += _collect_category(url, headers, now, days, category, log)
    log(f"  invaluable: {len(out)} lots")
    return out


def _collect_category(url, headers, now, days, category, log) -> list[Lot]:
    out, page, pages = [], 0, 1
    while page < pages:
        try:
            d = json.loads(fetch(url, data=query(now, now + days * 86400, page, category), headers=headers))
        except Exception as e:
            log(f"  invaluable {category} page {page}: {e}", file=sys.stderr)
            break
        for h in d.get("hits", []):
            # A live sale that started over 12h ago with no end time is a stale record.
            if h.get("banned") or (not h.get("endTimeUTCUnix") and h.get("dateTimeUTCUnix", 0) < now - 43200):
                continue
            out.append(to_lot(h))
        pages = d.get("nbPages", 0)
        page += 1
        if d.get("nbHits", 0) > 1000 and page == pages:
            log(f"  invaluable {category}: {d['nbHits']} hits, only the first 1000 are reachable",
                file=sys.stderr)
    return out
