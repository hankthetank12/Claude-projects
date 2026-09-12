# Whole Foods order agent

Builds your next Whole Foods order out of what you actually buy, and how often
you actually buy it.

It reads past orders, works out each item's rhythm — milk every 7 days, oats
every 28 — and proposes the things that should be running out now. Every line
shows the reasoning behind it, so a wrong suggestion is obvious instead of
mysterious.

```
PRODUCE
  [ ] 1 x Organic Red Raspberries  ~$4.99
        bought 17x, about every 7 days; last 9 days ago
  [ ] 1 x Organic Garlic  ~$2.69
        bought 6x, about every 23 days; last 22 days ago

PANTRY
  [ ] 2 x Kettle & Fire Organic Chicken Broth  ~$10.58
        bought 6x, about every 23 days; last 22 days ago

Estimated total: $43.08 for 6 items
```

The output is a plain list for pasting anywhere, and a self-contained HTML
order sheet you can open on a phone: tick items off, watch the running total,
and tap **Find in app** on any line to open it in the Amazon app.

---

## Try it before connecting anything

No account needed — this builds an order from synthetic history:

```bash
cd whole-foods-agent
python -m whole_foods_agent demo      # writes out/order.html
open out/order.html                   # or: xdg-open / start
```

Run from `src/` if `python -m whole_foods_agent` cannot find the module:

```bash
cd whole-foods-agent/src && python -m whole_foods_agent demo
```

## Loading real history

### Saved receipt emails (no credentials)

Save the "Your Whole Foods Market Receipt" emails as `.eml` or `.html` and:

```bash
python -m whole_foods_agent import ~/Downloads/receipts/
```

### Straight from a mailbox

Set `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` in `.env` for the mailbox that
gets the receipts — **whoever does the shopping**, which need not be whoever
runs the tool — then:

```bash
python -m whole_foods_agent sync --since 01-Jan-2026
```

Gmail blocks ordinary passwords for IMAP, so this needs an
[App Password](https://myaccount.google.com/apppasswords) created by that
account holder.

## Using it

```bash
python -m whole_foods_agent items                  # what gets bought, how often
python -m whole_foods_agent order                  # the next order, as text
python -m whole_foods_agent order --html           # the order sheet
python -m whole_foods_agent order --budget 80      # cap the estimate
python -m whole_foods_agent order --date 2026-10-01  # as of a future date
python -m whole_foods_agent cart                   # resolve to per-item links
python -m whole_foods_agent send                   # email the sheet
```

## How it decides

For every item that has been bought at least twice:

- **cadence** — the median gap between purchases.
- **due ratio** — days since last purchase ÷ cadence. At `1.0` it is exactly
  due. Anything at or above `WFA_DUE_THRESHOLD` (default `0.8`) is proposed,
  most overdue first.
- **quantity** — the median quantity bought, so three tins of beans stays three.
- **estimate** — the most recent price paid × that quantity.

Two guards keep the list honest:

- An item bought **once** has no measurable rhythm, so it never lands on the
  list automatically. It appears under "bought before, no rhythm yet".
- An item **three times past** its usual gap has probably left the rotation.
  It moves to "long overdue, maybe dropped" rather than being proposed forever.

Fees and container deposits are stripped out; they are on every receipt and are
not shopping.

## What it does not do

**It does not place the order, and it does not fill a cart by itself.**

Amazon publishes no customer-facing API for Whole Foods order history or the
grocery cart. The only way to add items automatically would be to drive a
signed-in browser session with real account credentials, which breaches
Amazon's Conditions of Use, puts the account at risk, and breaks whenever the
page changes. There is a further problem specific to groceries: order history
records a product *name*, never an identifier, and "Organic Sweet Onion"
matches dozens of listings — a wrong match becomes a real purchase.

So the hand-off is deliberately one tap per item. `cart.py` defines the seam
(`CartAdapter`); `DeepLinkCart` is the working implementation, and `BrowserCart`
documents the contract any automated back end would have to meet — session
reuse rather than stored passwords, humans handling every login challenge,
refusing ambiguous product matches, and stopping at the cart rather than
checkout.

## Known limits of the data

- **Receipt emails list at most 20 lines.** A bigger trip is genuinely
  truncated; the receipt's own "Items Purchased" count is kept so the shortfall
  is visible, and the order sheet says so rather than quietly under-counting.
- **Delivery orders are not itemised in email at all.** The Amazon
  confirmations for those carry a total and a delivery window, nothing more. If
  most shopping is delivered, email alone will miss most of the basket — an
  account order export is the fuller source.
- **Cadence needs history.** Below about six orders most items have been bought
  once, and the list will be short. The tool says so in its notes instead of
  inventing confidence it does not have.
- **Prices are the last price paid**, not today's shelf price.

## Layout

| Module | Does |
|---|---|
| `receipts.py` | Parse receipt emails (HTML, with plain text as fallback) |
| `gmail.py` | Fetch those emails over IMAP from any mailbox |
| `model.py` | The normalized `Order`/`LineItem` shape every source produces |
| `store.py` | The local JSON history, upserted by order id |
| `catalog.py` | Per-item cadence, quantities, prices, co-occurrence |
| `basket.py` | Choosing what goes on the list, and why |
| `render.py` | The text list and the HTML order sheet |
| `cart.py` | The seam between a proposed order and a real cart |

Adding a source means writing a parser that emits `Order` objects; nothing
downstream changes.

## Tests

```bash
cd whole-foods-agent && python -m pytest -q
```

The receipt fixtures are synthetic but structurally identical to the real
emails, including the Outlook conditional-comment block that will spill raw
markup into the item list if tag stripping is naive.
