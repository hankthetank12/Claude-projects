from watch_auctions.sources import (auctionmethod, auctionninja, bidspirit, ctbids, invaluable,
                                    liveauctioneers, shopgoodwill)

# Each source exposes collect(now, days, **opts) -> list[Lot].
# Direct sources reach small sellers that the big watch marketplaces don't carry.
DIRECT = {
    "bidspirit": bidspirit,
    "auctionmethod": auctionmethod,
    "auctionninja": auctionninja,
    "ctbids": ctbids,
    "shopgoodwill": shopgoodwill,
}
# Big shared marketplaces; opt in with --with-marketplaces.
MARKETPLACES = {
    "liveauctioneers": liveauctioneers,
    "invaluable": invaluable,
}
SOURCES = {**DIRECT, **MARKETPLACES}
