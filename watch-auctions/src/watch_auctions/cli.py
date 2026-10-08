from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from watch_auctions import aggregate, houses, render, sample
from watch_auctions.models import Lot
from watch_auctions.sources import DIRECT, MARKETPLACES, SOURCES


def _log(*a, **k):
    print(*a, **k)


def _write(out: Path, lots: list[Lot], rejected: list | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    prev_path = out / "lots.json"
    seen: set[str] = set()
    if prev_path.exists():
        try:
            seen = {f"{d['source']}:{d['source_id']}" for d in json.loads(prev_path.read_text())}
        except (ValueError, KeyError):
            pass
    ids = {f"{l.source}:{l.source_id}" for l in lots}
    new_ids = ids - seen if seen else set()
    prev_path.write_text(json.dumps([l.to_dict() for l in lots], indent=1))
    if rejected is not None:
        # What the quality filter threw out and why, for auditing it.
        (out / "rejected.json").write_text(json.dumps(
            [{"why": why, "title": l.title, "house": l.house, "source": l.source, "url": l.url}
             for l, why in rejected], indent=1))
    (out / "index.html").write_text(render.render(lots, new_ids))
    houses = len({l.house for l in lots})
    dropped = f", {len(rejected)} junk lots dropped" if rejected else ""
    print(f"{len(lots)} watch lots from {houses} houses ({len(new_ids)} new{dropped}) -> {out / 'index.html'}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="watch-auctions", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="pull live catalogs and build the page")
    f.add_argument("--days", type=int, default=30, help="how far ahead to look (default 30)")
    f.add_argument("--source", action="append", choices=sorted(SOURCES), help="limit to these platforms")
    f.add_argument("--with-marketplaces", action="store_true",
                   help="also pull LiveAuctioneers and Invaluable (off by default: everyone watches those)")
    f.add_argument("--min-price", type=float, default=25,
                   help="ShopGoodwill price floor for the full-category sweep (keyword sweeps ignore it)")
    f.add_argument("--max-pages", type=int, default=60, help="LiveAuctioneers page cap (120 lots/page)")
    f.add_argument("--max-house-lots", type=int, default=400,
                   help="skip LiveAuctioneers sellers with more active watch lots than this (bulk dealers)")
    f.add_argument("--keep-garbage", action="store_true",
                   help="don't drop low-quality lots (fashion brands, bulk lots, parts); still scored")
    f.add_argument("--include-majors", action="store_true", help="keep Bonhams, Christie's, etc.")
    f.add_argument("--out", type=Path, default=Path("out"))
    h = sub.add_parser("add-house", help="register a house's own bidding site (detects its engine)")
    h.add_argument("url")
    h.add_argument("--name", default="")
    h.add_argument("--city", default="")
    h.add_argument("--state", default="")
    sub.add_parser("houses", help="list registered house sites")
    d = sub.add_parser("demo", help="build the page from bundled sample lots, no network")
    d.add_argument("--out", type=Path, default=Path("out"))
    a = p.parse_args(argv)

    now = int(time.time())
    if a.cmd == "add-house":
        entry, status = houses.add(a.url, a.name, a.city, a.state)
        print(f"{entry['name']} ({entry['url']}): {status}")
        return 0 if status == "added" or "covered" in status else 1
    if a.cmd == "houses":
        for h in houses.load():
            print(f"{h['name']:<30} {h['engine']:<14} {h['url']}")
        return 0
    if a.cmd == "demo":
        rejected: list = []
        lots = aggregate.build(sample.lots(now), now, 30, rejected=rejected)
        _write(a.out, lots, rejected)
        return 0

    raw: list[Lot] = []
    names = a.source or (list(DIRECT) + (list(MARKETPLACES) if a.with_marketplaces else []))
    registry = houses.load()
    for name in names:
        print(f"fetching {name}…")
        try:
            opts = {"houses": registry, "min_price": a.min_price, "log": _log}
            if name == "liveauctioneers":
                opts.update(max_pages=a.max_pages, max_house_lots=a.max_house_lots)
            raw += SOURCES[name].collect(now, a.days, **opts)
        except Exception as e:
            print(f"  {name} failed: {e}", file=sys.stderr)
    if not raw:
        print("no lots fetched from any source", file=sys.stderr)
        return 1
    rejected: list = []
    lots = aggregate.build(raw, now, a.days, include_majors=a.include_majors,
                           keep_garbage=a.keep_garbage, rejected=rejected)
    _write(a.out, lots, rejected)
    return 0
