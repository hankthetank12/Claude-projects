"""Synthetic lots so the page can be built and tested without the network."""
from __future__ import annotations

from watch_auctions.models import Lot

_ROWS = [
    ("Rolex Submariner 16610 Stainless Steel Automatic", "Kodner Galleries", "Dania Beach", "FL", 1, 4000, 6000),
    ("Omega Speedmaster Professional 145.022 Moonwatch", "Rachel Davis Fine Arts", "Cleveland", "OH", 2, 2500, 3500),
    ("Vintage Hamilton 14K Solid Gold Manual Wind Wrist Watch", "Lark Mountain Auction Company", "Waynesville", "NC", 1, 100, 200),
    ("Tudor Black Bay 58 Ref. 79030N", "Gold Coast Auctions", "Fort Lauderdale", "FL", 3, 2200, 2800),
    ("Elgin 14K Hunter Case Pocket Watch c. 1910", "Davis Brothers Auction", "Pinson", "AL", 4, 300, 500),
    ("Seiko 6139-6002 Pogue Chronograph", "Hotspot Auctions", "Kalamazoo", "MI", 2, 250, 400),
    ("Cartier Tank Francaise Ladies 18K", "Akiba Galleries", "Hollywood", "FL", 5, 3000, 5000),
    ("Lot of 12 Watch Bands Only", "Thriftiques of Iowa", "Ankeny", "IA", 1, 10, 20),
    ("Fossil Men's Chronograph Watch FS4656", "Thriftiques of Iowa", "Ankeny", "IA", 2, 20, 40),
    ("Patek Philippe Calatrava 3919 18K Yellow Gold", "Bonhams", "New York", "NY", 6, 12000, 18000),
]


def lots(now: int) -> list[Lot]:
    out = []
    for i, (title, house, city, st, d, lo, hi) in enumerate(_ROWS):
        out.append(Lot(source=("bidspirit", "shopgoodwill", "ctbids", "auctionninja")[i % 4], source_id=f"demo{i}",
                       title=title, url="https://example.com/lot/demo", house=house, city=city,
                       state=st, lot_number=str(100 + i), sale_type="timed" if i % 3 else "live",
                       starts_at=now + d * 86400 - 3600, ends_at=now + d * 86400,
                       estimate_low=lo, estimate_high=hi, current_bid=lo // 2 if i % 2 else 0,
                       bid_count=3 if i % 2 else 0))
    # The same Kodner lot cross-listed on the other platform.
    dup = Lot(**{**out[0].to_dict(), "source": "auctionninja", "source_id": "demo-dup",
                 "house": "Kodner Galleries Inc."})
    return out + [dup]
