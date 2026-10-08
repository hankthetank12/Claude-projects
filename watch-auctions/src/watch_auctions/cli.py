from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from watch_auctions import aggregate, render, sample
from watch_auctions.models import Lot
from watch_auctions.sources import SOURCES


def _log(*a, **k):
    print(*a, **k)


def _write(out: Path, lots: list[Lot]) -> None:
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
    (out / "index.html").write_text(render.render(lots, new_ids))
    houses = len({l.house for l in lots})
    print(f"{len(lots)} watch lots from {houses} houses ({len(new_ids)} new) -> {out / 'index.html'}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="watch-auctions", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="pull live catalogs and build the page")
    f.add_argument("--days", type=int, default=30, help="how far ahead to look (default 30)")
    f.add_argument("--source", action="append", choices=sorted(SOURCES), help="limit to these platforms")
    f.add_argument("--max-pages", type=int, default=60, help="LiveAuctioneers page cap (120 lots/page)")
    f.add_argument("--max-house-lots", type=int, default=400,
                   help="skip LiveAuctioneers sellers with more active watch lots than this (bulk dealers)")
    f.add_argument("--include-majors", action="store_true", help="keep Bonhams, Christie's, etc.")
    f.add_argument("--out", type=Path, default=Path("out"))
    d = sub.add_parser("demo", help="build the page from bundled sample lots, no network")
    d.add_argument("--out", type=Path, default=Path("out"))
    a = p.parse_args(argv)

    now = int(time.time())
    if a.cmd == "demo":
        lots = aggregate.build(sample.lots(now), now, 30)
        _write(a.out, lots)
        return 0

    raw: list[Lot] = []
    for name in a.source or sorted(SOURCES):
        print(f"fetching {name}…")
        try:
            raw += SOURCES[name].collect(now, a.days, max_pages=a.max_pages,
                                         max_house_lots=a.max_house_lots, log=_log)
        except Exception as e:
            print(f"  {name} failed: {e}", file=sys.stderr)
    if not raw:
        print("no lots fetched from any source", file=sys.stderr)
        return 1
    _write(a.out, aggregate.build(raw, now, a.days, include_majors=a.include_majors))
    return 0
