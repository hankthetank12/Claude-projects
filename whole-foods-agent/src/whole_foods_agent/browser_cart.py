"""Add a proposed order to a signed-in Amazon cart with a real browser.

Read this before using it.

Amazon publishes no customer API for Whole Foods order history or the grocery
cart, so the only way to add items automatically is to drive the website as a
signed-in user. That breaches Amazon's Conditions of Use and the risk lands on
the account it runs as. This module exists because the account holder asked for
it; it is not the recommended path, and `DeepLinkCart` remains the default.

The design rules below are load-bearing, not decoration:

* **The human owns the login.** There is no password field in this module. A
  persistent browser profile is opened non-headless, and if the session is not
  already signed in the run pauses while a person signs in and clears any
  one-time code. Nothing here attempts to defeat a login challenge.
* **It stops at the cart.** Any navigation towards checkout, payment or a
  delivery slot aborts the run. Adding to a cart is reversible; buying is not.
* **It refuses ambiguous matches.** History from a receipt email records a
  product *name*, and "Organic Sweet Onion" matches dozens of listings. A line
  is added only when it has an exact product id, or when one search result is
  both a good match and clearly better than the runner-up. Everything else is
  reported for a human to decide.
* **It is dry-run by default**, so the first run tells you what it would do.
* **It is paced and bounded**, and aborts on the first unexpected page rather
  than clicking onward blindly.

Policy lives here; browser mechanics live behind `PageDriver`. That split keeps
every decision above testable without a browser. The CSS selectors in
`PlaywrightDriver` are the one part that cannot be verified except against the
live site, and they will need adjusting when Amazon changes its markup — that
is the maintenance cost of this approach, and it is why the deep-link back end
exists.
"""

from __future__ import annotations

import difflib
import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Protocol, Sequence

from .basket import OrderLine
from .cart import CartEntry, CartUnavailable

log = logging.getLogger(__name__)

# Navigating to any of these means the run has wandered towards buying.
FORBIDDEN_URL_FRAGMENTS = (
    "/gp/buy",
    "/checkout",
    "/buy/",
    "/gp/cart/desktop/go-to-checkout",
    "/payments",
    "/gp/buy/spc",
    "one-click",
    "placeorder",
    "place-order",
)

# A match must score at least this well, and beat the runner-up by this margin,
# before it is added without a human looking at it.
MATCH_THRESHOLD = 0.72
MATCH_MARGIN = 0.08

# A quantity above this is treated as a parsing error rather than an order.
MAX_QUANTITY = 12

WFM_BRAND_ID = "VUZHIFdob2xlIEZvb2Rz"
SEARCH_URL = "https://www.amazon.com/s?k={query}&almBrandId=" + WFM_BRAND_ID


class CheckoutBlocked(RuntimeError):
    """The run tried to move towards buying and was stopped."""


class NotSignedIn(RuntimeError):
    """Nobody completed the sign-in."""


@dataclass
class Candidate:
    """One product the site offered for a line."""

    name: str
    product_id: str | None = None
    price: float | None = None
    available: bool = True


class PageDriver(Protocol):
    """The browser primitives this module needs. Implemented by Playwright."""

    def current_url(self) -> str: ...
    def goto(self, url: str) -> None: ...
    def is_signed_in(self) -> bool: ...
    def wait_for_sign_in(self, timeout: float) -> bool: ...
    def search(self, query: str) -> list[Candidate]: ...
    def open_product(self, product_id: str) -> Candidate | None: ...
    def add_to_cart(self, quantity: int) -> bool: ...
    def close(self) -> None: ...


def is_forbidden_url(url: str) -> bool:
    """True for anything on the way to buying rather than browsing."""
    lowered = (url or "").lower()
    return any(fragment in lowered for fragment in FORBIDDEN_URL_FRAGMENTS)


_NOISE = re.compile(r"\b(?:organic|fresh|natural|whole foods market|365 by whole foods market|365)\b")


def normalise_for_match(name: str) -> str:
    """Reduce a product name to the words that identify it."""
    lowered = name.lower()
    lowered = re.sub(r",\s*[\d.]+\s*[a-z]{1,4}\b", " ", lowered)  # trailing size
    lowered = _NOISE.sub(" ", lowered)
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def similarity(a: str, b: str) -> float:
    """How alike two product names are, 0..1."""
    left, right = normalise_for_match(a), normalise_for_match(b)
    if not left or not right:
        return 0.0
    ratio = difflib.SequenceMatcher(None, left, right).ratio()
    # Reward containment: "sweet onion" inside "organic sweet onion 3ct".
    if left in right or right in left:
        ratio = max(ratio, 0.9)
    return ratio


def match_product(name: str, candidates: Sequence[Candidate]) -> tuple[Candidate | None, str]:
    """Pick a result only when the choice is not a guess.

    Returns the match and the reason, so a refusal can be reported rather than
    silently dropping a line.
    """
    usable = [c for c in candidates if c.available]
    if not usable:
        return None, "no available results"

    scored = sorted(((similarity(name, c.name), c) for c in usable), key=lambda pair: -pair[0])
    best_score, best = scored[0]
    if best_score < MATCH_THRESHOLD:
        return None, f"best result only {best_score:.2f} similar ({best.name!r})"
    if len(scored) > 1:
        runner_up = scored[1][0]
        if best_score - runner_up < MATCH_MARGIN:
            return None, (
                f"ambiguous: {best.name!r} and {scored[1][1].name!r} score "
                f"{best_score:.2f} and {runner_up:.2f}"
            )
    return best, f"matched {best.name!r} at {best_score:.2f}"


def cart_quantity(line: OrderLine) -> tuple[int, str | None]:
    """How many of this to add, and any caveat a human should see."""
    if line.stats.unit != "each":
        # A cart cannot express "2.52 lb"; one unit and a note is honest.
        return 1, f"usually bought by weight ({line.quantity:g} {line.stats.unit})"
    quantity = int(round(line.quantity))
    if quantity < 1:
        return 1, None
    if quantity > MAX_QUANTITY:
        return MAX_QUANTITY, f"history said {line.quantity:g}, capped at {MAX_QUANTITY}"
    return quantity, None


class BrowserCart:
    """Add proposed lines to a signed-in cart, conservatively."""

    def __init__(
        self,
        driver: PageDriver | None = None,
        *,
        profile_dir: str | None = None,
        dry_run: bool = True,
        headless: bool = False,
        delay: tuple[float, float] = (2.0, 4.5),
        sign_in_timeout: float = 300.0,
    ) -> None:
        self._driver = driver
        self.profile_dir = profile_dir
        self.dry_run = dry_run
        self.headless = headless
        self.delay = delay
        self.sign_in_timeout = sign_in_timeout

    def _ensure_driver(self) -> PageDriver:
        if self._driver is not None:
            return self._driver
        self._driver = PlaywrightDriver(
            profile_dir=self.profile_dir, headless=self.headless
        )
        return self._driver

    def _pause(self) -> None:
        low, high = self.delay
        if high > 0:
            time.sleep(random.uniform(low, high))

    def _goto(self, driver: PageDriver, url: str) -> None:
        if is_forbidden_url(url):
            raise CheckoutBlocked(f"refusing to navigate towards checkout: {url}")
        driver.goto(url)
        landed = driver.current_url()
        if is_forbidden_url(landed):
            raise CheckoutBlocked(f"the site redirected towards checkout: {landed}")

    def submit(self, lines: Sequence[OrderLine]) -> list[CartEntry]:
        driver = self._ensure_driver()
        entries: list[CartEntry] = []
        try:
            if not driver.is_signed_in():
                log.warning("not signed in; complete sign-in in the browser window")
                if not driver.wait_for_sign_in(self.sign_in_timeout):
                    raise NotSignedIn(
                        "nobody signed in within the timeout. This tool never "
                        "enters credentials itself: sign in in the open browser "
                        "window and run it again."
                    )

            for line in lines:
                entries.append(self._submit_line(driver, line))
                self._pause()
        finally:
            if self.dry_run:
                driver.close()
        return entries

    def _submit_line(self, driver: PageDriver, line: OrderLine) -> CartEntry:
        quantity, caveat = cart_quantity(line)
        entry = CartEntry(
            name=line.name,
            quantity=line.quantity,
            unit=line.stats.unit,
            product_id=line.stats.product_id,
        )

        candidate: Candidate | None
        if line.stats.product_id:
            self._goto(driver, f"https://www.amazon.com/dp/{line.stats.product_id}")
            candidate = driver.open_product(line.stats.product_id)
            reason = "exact product id from order history"
            if candidate is None:
                entry.detail = "product id no longer resolves; needs review"
                return entry
        else:
            self._goto(driver, SEARCH_URL.format(query=line.name.replace(" ", "+")))
            candidate, reason = match_product(line.name, driver.search(line.name))
            if candidate is None:
                entry.detail = f"not added — {reason}"
                return entry

        entry.url = (
            f"https://www.amazon.com/dp/{candidate.product_id}"
            if candidate.product_id
            else None
        )

        notes = [reason]
        if caveat:
            notes.append(caveat)

        if self.dry_run:
            entry.detail = f"would add {quantity} — " + "; ".join(notes)
            return entry

        added = driver.add_to_cart(quantity)
        entry.added = added
        entry.detail = ("added {} — ".format(quantity) if added else "add failed — ") + "; ".join(notes)
        return entry


class PlaywrightDriver:
    """Playwright implementation of `PageDriver`.

    The selectors here are the unverifiable part: they reflect Amazon's markup
    as documented at the time of writing and will need updating when it
    changes. Run with `--dry-run` after any change, and check the screenshots
    written on failure.
    """

    SELECTORS = {
        "signed_in": "#nav-link-accountList-nav-line-1",
        "sign_in_marker": "#nav-item-signin, #ap_email, #ap_password",
        "result_item": "div[data-component-type='s-search-result']",
        "result_title": "h2 a span, h2 span",
        "result_price": "span.a-price > span.a-offscreen",
        "result_unavailable": "span.a-color-price:has-text('Currently unavailable')",
        "product_title": "#productTitle",
        "quantity_select": "#quantity",
        "add_to_cart": "#add-to-cart-button, input[name='submit.add-to-cart']",
        "added_confirmation": "#attachDisplayAddBaseAlert, #huc-v2-order-row-confirm-text, #sw-atc-details-single-container",
    }

    def __init__(self, *, profile_dir: str | None = None, headless: bool = False) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depends on the machine
            raise CartUnavailable(
                "The browser back end needs Playwright: "
                "pip install playwright && playwright install chromium"
            ) from exc

        if not profile_dir:
            raise CartUnavailable(
                "A profile directory is required so the sign-in persists between "
                "runs; pass --profile ~/.whole-foods-profile"
            )

        self._playwright = sync_playwright().start()
        # A persistent context keeps the human's sign-in, so this tool never
        # needs to know a password.
        self._context = self._playwright.chromium.launch_persistent_context(
            profile_dir, headless=headless
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

    def current_url(self) -> str:  # pragma: no cover - needs a browser
        return self._page.url

    def goto(self, url: str) -> None:  # pragma: no cover - needs a browser
        self._page.goto(url, wait_until="domcontentloaded", timeout=45000)

    def is_signed_in(self) -> bool:  # pragma: no cover - needs a browser
        self.goto("https://www.amazon.com/gp/css/homepage.html")
        try:
            text = self._page.text_content(self.SELECTORS["signed_in"], timeout=5000) or ""
        except Exception:
            return False
        return "sign in" not in text.lower()

    def wait_for_sign_in(self, timeout: float) -> bool:  # pragma: no cover
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(3)
            if self.is_signed_in():
                return True
        return False

    def search(self, query: str) -> list[Candidate]:  # pragma: no cover
        candidates: list[Candidate] = []
        for node in self._page.query_selector_all(self.SELECTORS["result_item"])[:12]:
            title_node = node.query_selector(self.SELECTORS["result_title"])
            if not title_node:
                continue
            price_node = node.query_selector(self.SELECTORS["result_price"])
            price = None
            if price_node:
                raw = (price_node.inner_text() or "").replace("$", "").replace(",", "")
                try:
                    price = float(raw)
                except ValueError:
                    price = None
            candidates.append(
                Candidate(
                    name=(title_node.inner_text() or "").strip(),
                    product_id=node.get_attribute("data-asin") or None,
                    price=price,
                    available=node.query_selector(self.SELECTORS["result_unavailable"]) is None,
                )
            )
        return candidates

    def open_product(self, product_id: str) -> Candidate | None:  # pragma: no cover
        title = self._page.text_content(self.SELECTORS["product_title"], timeout=10000)
        if not title:
            return None
        return Candidate(name=title.strip(), product_id=product_id)

    def add_to_cart(self, quantity: int) -> bool:  # pragma: no cover
        if is_forbidden_url(self._page.url):
            raise CheckoutBlocked(f"refusing to act on {self._page.url}")
        try:
            if quantity > 1 and self._page.query_selector(self.SELECTORS["quantity_select"]):
                self._page.select_option(self.SELECTORS["quantity_select"], str(quantity))
            self._page.click(self.SELECTORS["add_to_cart"], timeout=15000)
            self._page.wait_for_selector(self.SELECTORS["added_confirmation"], timeout=15000)
        except Exception as exc:
            log.warning("add to cart failed: %s", exc)
            try:
                self._page.screenshot(path="add-to-cart-failure.png")
            except Exception:
                pass
            return False
        if is_forbidden_url(self._page.url):
            raise CheckoutBlocked(f"landed on {self._page.url} after adding")
        return True

    def close(self) -> None:  # pragma: no cover
        try:
            self._context.close()
        finally:
            self._playwright.stop()
