# Watch auctions

One scrolling catalog of upcoming watch lots from the small sellers nobody
sweeps systematically: estate-sale companies, local Goodwill stores,
Caring Transitions franchises, and small-town auction houses running their
own bidding sites.

```
fetching bidspirit…
  bidspirit: 475 lots from 46 houses (180 sales scanned)
fetching auctionninja…
  auctionninja: 516 lots from 73 companies
fetching ctbids…
  ctbids: 248 lots
fetching shopgoodwill…
  shopgoodwill: 1279 lots
2290 watch lots from 268 houses (37 new) -> out/index.html
```

In the run above, 90% of the lots came from sellers with no watch lots on
LiveAuctioneers or Invaluable. Those two marketplaces are where everyone
already looks.

The output is one self-contained HTML page that works offline and on a phone.
Lots are grouped by the day they close. You can filter by brand, state,
seller, or "closing in the next 24h / 3 days / 7 days", and you can show only
lots that are new since your last run. Every card links straight to the
lot's bidding page.

## Where it looks

| Source | Who sells there | How we read it |
|---|---|---|
| **Bidspirit** | ~150 small houses (Ohio, Michigan, Carolinas, Florida…) | public JSON catalog of every upcoming US sale |
| **AuctionNinja** | hundreds of local estate-sale companies | server-rendered search pages |
| **CTBids** | Caring Transitions estate-sale franchises | the site's public search API |
| **ShopGoodwill** | ~110 individual Goodwill stores | the site's public search API, Watches category |
| **AuctionMethod sites** | houses running their *own* bidding site on AuctionMethod | each registered site's JSON API |
| LiveAuctioneers, Invaluable | the big shared marketplaces | **off by default**; add `--with-marketplaces` |

### House sites you add yourself

Many small houses run their own `bid.<house>.com` site on white-label
software, and those sites have no central directory. You can register any
house site, and `add-house` will detect what software it runs:

```bash
PYTHONPATH=src python3 -m watch_auctions add-house bid.gwsauctions.com --name "GWS Auctions" --state CA
PYTHONPATH=src python3 -m watch_auctions houses
```

- **AuctionMethod sites** are added to `houses.json` and scraped on every run.
- **Bidspirit, Invaluable and LiveAuctioneers sites** are already covered by
  their platform source, and the command tells you so. Many "own" house sites
  are really white-label front ends of these platforms.
- **HiBid, Wavebid, Auction Mobility and Bidsquare sites** are detected but
  not supported yet.

### What gets filtered out

- **Things that aren't watches:** bands, empty boxes, books, clocks, fobs,
  parts, and jewelry that only mentions a watch brand ("Omega chain").
- **ShopGoodwill fashion watches.** The full-category sweep only keeps
  listings already bid to $25 or more (`--min-price`). It also runs keyword
  sweeps (Rolex, Omega, 14K, automatic, pocket watch…) with no price floor,
  since good pieces often sit at a low bid until the last day.
- **Duplicates.** A lot listed in two places becomes one card with a "+1"
  marker.

## Run it

Needs Python 3.10+. There are no dependencies.

```bash
cd watch-auctions
PYTHONPATH=src python3 -m watch_auctions fetch      # ~5 min, writes out/index.html + out/lots.json
open out/index.html
```

Options:

```
--days N              look N days ahead (default 30)
--source NAME         only these sources (repeatable)
--with-marketplaces   also pull LiveAuctioneers and Invaluable
--min-price N         ShopGoodwill price floor for the category sweep (default 25)
--include-majors      keep Bonhams, Christie's, etc. (marketplaces only)
--out DIR             output directory (default out/)
```

Use `demo` to build the page from bundled sample lots, with no network:

```bash
PYTHONPATH=src python3 -m watch_auctions demo
```

Run `fetch` daily (cron, launchd, a GitHub Action). The "new since last
run" filter then becomes a daily list of watches you haven't seen yet.

## Adding a platform

A source is a module in `src/watch_auctions/sources/` with a
`collect(now, days, **opts) -> list[Lot]` function, registered in
`sources/__init__.py`. Filtering, brand detection and de-duplication happen
afterwards in `aggregate.py`, so a source only has to map the platform's
records onto `Lot`.

Not wired up yet:
- **HiBid, Proxibid, K-BID and Wavebid.** They host many of the smallest
  Midwest and rural houses, but they block requests from the cloud
  environment this was built in (K-BID after a few pages). Try them from a
  home connection.
- **Biddergy.** Reachable, but it only had a dozen watch lots, mostly
  liquidation bundles.

## Tests

```bash
python -m pytest -q
```
