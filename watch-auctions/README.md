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
| **EBTH** | Everything But The House estate sales | the site's JSON API (key read from its page) |
| **PropertyRoom** | police and government agencies selling recovered property | server-rendered listing pages |
| **BidWrangler sites** | 22 regional auctioneers' own bidding sites (Alderfer, Cabin Fever, Joe R. Pyle…) | each site's JSON API |
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

- **AuctionMethod and BidWrangler sites** are added to `houses.json` and
  scraped on every run.
- **Bidspirit, Invaluable and LiveAuctioneers sites** are already covered by
  their platform source, and the command tells you so. Many "own" house sites
  are really white-label front ends of these platforms.
- **HiBid, Wavebid, Auction Mobility and Bidsquare sites** are detected but
  not supported yet.

BidWrangler publishes a [client list](https://www.bidwrangler.com/clients).
Its bidding sites resolved to 43 houses. Many are land, farm and equipment
auctioneers that never sell watches, so only the 22 that sell general
merchandise and estates are registered.

### Ranked by quality, junk dropped

Every lot gets a 0–100 collector score, and the page shows the reasons
behind it ("Rolex · solid 18K · reference no. · $18,000 estimate"):

| Signal | Points |
|---|---|
| Maker | Patek, AP, Vacheron, Lange: 45 · Rolex, Breguet: 40 · JLC, Blancpain: 35 · Omega, Cartier: 30 · Tudor, IWC, Panerai, Grand Seiko: 28 · … · Elgin, Gruen: 8 |
| Solid gold or platinum (not filled, plated or gold-tone) | +18 |
| Mechanical movement | +8 (quartz −4) |
| Complication (chronograph, GMT, moonphase, repeater…) | +6 |
| Box and papers | +6 |
| Vintage | +5 |
| Reference number (not a year) | +4 |
| Estimate or current bid | up to +25, log-scaled ($100 ≈ 4, $1k ≈ 12, $10k ≈ 20) |
| Active bidding | up to +6 |
| Diamonds added after the factory | −8 |

Lots are rejected outright, never shown, and listed in `out/rejected.json`
with the reason, when they are:

- **Fashion, mall or gadget brands:** Fossil, Michael Kors, Invicta,
  Armitron, Geneva, Stauer, Casio, Apple Watch and others.
- **Not a real, working watch:** parts or repair, not working, as-is,
  replicas and homages, kids' and novelty watches, cases or dials only,
  trading cards.
- **Bulk lots** ("lot of 15 watches", "12pc"), unless the brand alone
  justifies it (two Rolexes are still worth seeing).
- **Below 25 points:** nothing collectible about it.

On a typical run, about 80% of watch-titled lots are rejected.

The page sorts best-first by default, or by closing time. A minimum-score
slider lets you raise the bar further. One dealer can't monopolize the top:
each further lot from the same house sorts 2 points lower, up to 20. This
only affects order; the score shown stays the same. Add `--keep-garbage`
to score everything without dropping anything.

### What else gets filtered out

- **Things that aren't watches:** bands, empty boxes, books, clocks, fobs,
  parts, and jewelry that only mentions a watch brand ("Omega chain").
- **Most ShopGoodwill listings never get fetched.** The full-category sweep
  only pulls listings already bid to $25 or more (`--min-price`). It also
  runs keyword sweeps (Rolex, Omega, 14K, automatic, pocket watch…) with no
  price floor, since good pieces often sit at a low bid until the last day.
- **Duplicates.** A lot listed in two places becomes one card with a "+1"
  marker.

## Run it

Needs Python 3.10+. There are no dependencies.

```bash
cd watch-auctions
PYTHONPATH=src python3 -m watch_auctions fetch      # ~10 min, writes out/index.html + out/lots.json
open out/index.html
```

Options:

```
--days N              look N days ahead (default 30)
--source NAME         only these sources (repeatable)
--with-marketplaces   also pull LiveAuctioneers and Invaluable
--min-price N         ShopGoodwill price floor for the category sweep (default 25)
--include-majors      keep Bonhams, Christie's, etc. (marketplaces only)
--keep-garbage        score everything but drop nothing
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
