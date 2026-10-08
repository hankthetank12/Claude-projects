from watch_auctions.sources import (auctionmethod, auctionninja, bidspirit, bidwrangler, ctbids, ebth,
                                    invaluable, liveauctioneers, propertyroom, shopgoodwill)

# Each source exposes collect(now, days, **opts) -> list[Lot].
# Direct sources reach small sellers that the big watch marketplaces don't carry.
DIRECT = {
    "bidspirit": bidspirit,
    "bidwrangler": bidwrangler,
    "auctionmethod": auctionmethod,
    "auctionninja": auctionninja,
    "ctbids": ctbids,
    "ebth": ebth,
    "propertyroom": propertyroom,
    "shopgoodwill": shopgoodwill,
}
# Big shared marketplaces; opt in with --with-marketplaces.
MARKETPLACES = {
    "liveauctioneers": liveauctioneers,
    "invaluable": invaluable,
}
SOURCES = {**DIRECT, **MARKETPLACES}
