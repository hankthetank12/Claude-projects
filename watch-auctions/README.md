# Watch auctions

One scrolling catalog of upcoming watch lots from small US auction houses:
the estate-sale houses, regional galleries and one-person auctioneers whose
catalogs you'd otherwise check one app at a time.

```
fetching invaluable…
  invaluable: 970 lots
fetching liveauctioneers…
  liveauctioneers: skipping bulk dealers / majors: Mynt Auctions (6171), Diamond Depot (4990), …
  liveauctioneers: 2520 lots from 21 of 23 pages
2251 watch lots from 185 houses (37 new) -> out/index.html
```

The output is one self-contained HTML page that works offline and on a phone.
Lots are grouped by the day they close. You can filter by brand, state,
house, or "closing in the next 24h / 3 days / 7 days", and you can show only
lots that are new since your last run. Every card links straight to the
lot's bidding page.

## How it reaches the small houses

Most small US houses don't run their own bidding software. Their "app" or
catalog page is a white-label front end for one of a few hosting platforms,
so we read each platform once instead of scraping hundreds of house sites:

| Platform | How we read it | What we ask for |
|---|---|---|
| **LiveAuctioneers** | the JSON search endpoint its own pages call | Watches category, US houses, live + timed sales |
| **Invaluable** | the public search index its site queries | Men's, women's and pocket watch categories, US houses |

Each house's catalog on these platforms is the same one that shows on the
house's own website or app.

### What gets filtered out

- **Bulk dealers.** A few LiveAuctioneers sellers run perpetual watch sales
  with thousands of lots (Mynt, Diamond Depot, Bidhaus…). They're excluded
  server-side so they don't push the small houses off the results. The
  cutoff is `--max-house-lots` (default 400 active lots).
- **Major houses.** Bonhams, Christie's, Sotheby's, Phillips, Heritage,
  Doyle and similar. Add `--include-majors` to keep them.
- **Things that aren't watches.** Bands, empty boxes, books, clocks, fobs
  and parts (see `classify.py`).
- **Duplicates.** Many houses simulcast on both platforms. The same house,
  lot number and title becomes one card with a "+1" marker.

## Run it

Needs Python 3.10+. There are no dependencies.

```bash
cd watch-auctions
PYTHONPATH=src python3 -m watch_auctions fetch      # ~30s, writes out/index.html + out/lots.json
open out/index.html
```

Options:

```
--days N              look N days ahead (default 30)
--source NAME         only one platform (repeatable): liveauctioneers, invaluable
--max-house-lots N    bulk-dealer cutoff for LiveAuctioneers (default 400)
--include-majors      keep Bonhams, Christie's, etc.
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

The obvious next sources are **HiBid** and **Proxibid**. They host many of
the smallest Midwest and rural houses, but both refuse requests from the
cloud environment this was built in, so they aren't wired up yet. They
should be tested from a home connection.

## Tests

```bash
python -m pytest -q
```
