"""Registry of individual house websites, and engine detection for adding new ones."""
from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path

from watch_auctions.http import fetch

REGISTRY = Path(__file__).with_name("houses.json")

# Fingerprints in a house site's HTML -> which engine (and so which adapter) runs it.
ENGINES = [
    ("auctionmethod", re.compile(r"auctionmethod\.com|d3sachi1veog95\.cloudfront\.net", re.I)),
    ("bidspirit", re.compile(r"bidspirit", re.I)),
    ("hibid", re.compile(r"hibid\.com", re.I)),
    ("invaluable", re.compile(r"image\.invaluable\.com|invaluable\.com/catalog", re.I)),
    ("bidsquare", re.compile(r"images\.bidsquare\.com|bidsquare\.com/auctions", re.I)),
    ("liveauctioneers", re.compile(r"liveauctioneers\.com/(catalog|auctioneer)", re.I)),
    ("auctionmobility", re.compile(r"auctionmobility", re.I)),
    ("wavebid", re.compile(r"wavebid", re.I)),
]
# Engines whose lots are already covered by a whole-platform adapter.
COVERED = {"bidspirit", "invaluable", "liveauctioneers"}
SUPPORTED = {"auctionmethod"}


def load() -> list[dict]:
    try:
        return json.loads(REGISTRY.read_text())
    except (OSError, ValueError):
        return []


def detect(url: str) -> list[str]:
    page = fetch(url)
    return [name for name, rx in ENGINES if rx.search(page)]


def add(url: str, name: str = "", city: str = "", state: str = "") -> tuple[dict, str]:
    if not url.startswith("http"):
        url = "https://" + url
    found = detect(url)
    engine = next((e for e in found if e in SUPPORTED), found[0] if found else "unknown")
    entry = {"name": name or urllib.parse.urlparse(url).netloc, "url": url.rstrip("/"),
             "engine": engine, "city": city, "state": state}
    if engine in SUPPORTED:
        houses = [h for h in load() if h["url"] != entry["url"]] + [entry]
        REGISTRY.write_text(json.dumps(houses, indent=2) + "\n")
        return entry, "added"
    if engine in COVERED:
        return entry, f"runs on {engine}, already covered by the {engine} source"
    return entry, f"engine '{engine}' isn't supported yet (detected: {', '.join(found) or 'nothing'})"
