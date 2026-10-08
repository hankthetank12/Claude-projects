from watch_auctions.sources import invaluable, liveauctioneers

# Each source exposes collect(now, days, **opts) -> list[Lot].
SOURCES = {
    "liveauctioneers": liveauctioneers,
    "invaluable": invaluable,
}
