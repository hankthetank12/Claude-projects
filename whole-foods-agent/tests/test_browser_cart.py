"""The browser back end's policy, exercised without a browser.

Everything that decides *whether* to add something is tested here. The CSS
selectors in PlaywrightDriver are not: they can only be checked against the
live site.
"""

from datetime import date, timedelta

import pytest

from whole_foods_agent import basket, catalog as catalog_mod
from whole_foods_agent.browser_cart import (
    BrowserCart,
    Candidate,
    CheckoutBlocked,
    NotSignedIn,
    cart_quantity,
    is_forbidden_url,
    match_product,
    normalise_for_match,
    similarity,
)
from whole_foods_agent.model import LineItem, Order

START = date(2026, 1, 1)


class FakeDriver:
    """A scriptable stand-in for the browser."""

    def __init__(self, *, results=None, signed_in=True, product=None, redirect_to=None):
        self.results = results or []
        self.signed_in = signed_in
        self.product = product
        self.redirect_to = redirect_to
        self.url = "https://www.amazon.com/"
        self.added: list[int] = []
        self.visited: list[str] = []
        self.closed = False
        self.sign_in_waits = 0

    def current_url(self):
        return self.url

    def goto(self, url):
        self.visited.append(url)
        self.url = self.redirect_to or url

    def is_signed_in(self):
        return self.signed_in

    def wait_for_sign_in(self, timeout):
        self.sign_in_waits += 1
        return self.signed_in

    def search(self, query):
        return list(self.results)

    def open_product(self, product_id):
        return self.product

    def add_to_cart(self, quantity):
        self.added.append(quantity)
        return True

    def close(self):
        self.closed = True


def _lines(name="Organic Whole Milk, 59 FZ", quantity=1, unit="each", product_id=None):
    orders = [
        Order(
            order_id=f"o{i}",
            ordered_on=START + timedelta(days=7 * i),
            items=[
                LineItem.from_raw(
                    name,
                    quantity=quantity,
                    unit=unit,
                    unit_price=6.99,
                    line_total=6.99,
                    product_id=product_id,
                )
            ],
        )
        for i in range(4)
    ]
    catalog = catalog_mod.build(orders)
    last = max(s.last_bought for s in catalog.items.values())
    return basket.build(catalog, on_date=last + timedelta(days=7)).lines


# --- guards ---------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "https://www.amazon.com/gp/buy/spc/handlers/display.html",
        "https://www.amazon.com/checkout/entry",
        "https://www.amazon.com/gp/cart/desktop/go-to-checkout",
        "https://www.amazon.com/PLACEORDER",
    ],
)
def test_checkout_urls_are_recognised(url):
    assert is_forbidden_url(url)


@pytest.mark.parametrize(
    "url",
    ["https://www.amazon.com/dp/B0001", "https://www.amazon.com/s?k=milk", ""],
)
def test_browsing_urls_are_allowed(url):
    assert not is_forbidden_url(url)


def test_a_redirect_towards_checkout_aborts_the_run():
    driver = FakeDriver(redirect_to="https://www.amazon.com/gp/buy/spc")
    cart = BrowserCart(driver, dry_run=False, delay=(0, 0))
    with pytest.raises(CheckoutBlocked):
        cart.submit(_lines())
    assert driver.added == []


# --- matching -------------------------------------------------------------

def test_size_and_filler_words_do_not_decide_a_match():
    assert normalise_for_match("365 by Whole Foods Market Organic Cannellini Beans, 15.5 OZ") == (
        "cannellini beans"
    )


def test_similarity_rewards_containment():
    assert similarity("Organic Sweet Onion", "Organic Sweet Onion, 3 CT") > 0.85


def test_a_clear_winner_is_matched():
    candidates = [
        Candidate(name="Organic Whole Milk, 59 FZ", product_id="B1"),
        Candidate(name="Cat Litter, 20 LB", product_id="B2"),
    ]
    match, reason = match_product("Organic Whole Milk, 59 FZ", candidates)
    assert match.product_id == "B1"
    assert "matched" in reason


def test_two_near_identical_results_are_refused_not_guessed():
    candidates = [
        Candidate(name="Organic Sweet Onion", product_id="B1"),
        Candidate(name="Organic Sweet Onions", product_id="B2"),
    ]
    match, reason = match_product("Organic Sweet Onion", candidates)
    assert match is None
    assert "ambiguous" in reason


def test_a_poor_best_result_is_refused():
    candidates = [Candidate(name="Garden Hose, 50 FT", product_id="B9")]
    match, reason = match_product("Organic Whole Milk", candidates)
    assert match is None
    assert "similar" in reason


def test_unavailable_results_are_ignored():
    candidates = [Candidate(name="Organic Whole Milk, 59 FZ", product_id="B1", available=False)]
    match, reason = match_product("Organic Whole Milk, 59 FZ", candidates)
    assert match is None
    assert reason == "no available results"


# --- quantity -------------------------------------------------------------

def test_a_weighed_item_becomes_one_unit_with_a_caveat():
    line = _lines(quantity=2.52, unit="lb")[0]
    quantity, caveat = cart_quantity(line)
    assert quantity == 1
    assert "by weight" in caveat


def test_an_absurd_quantity_is_capped():
    line = _lines(quantity=40)[0]
    quantity, caveat = cart_quantity(line)
    assert quantity == 12
    assert "capped" in caveat


def test_a_normal_quantity_passes_through():
    assert cart_quantity(_lines(quantity=3)[0]) == (3, None)


# --- the flow -------------------------------------------------------------

def test_dry_run_adds_nothing_and_says_what_it_would_do():
    driver = FakeDriver(results=[Candidate(name="Organic Whole Milk, 59 FZ", product_id="B1")])
    entries = BrowserCart(driver, dry_run=True, delay=(0, 0)).submit(_lines())
    assert driver.added == []
    assert entries[0].added is False
    assert "would add 1" in entries[0].detail


def test_a_known_product_id_skips_search_entirely():
    driver = FakeDriver(product=Candidate(name="Organic Whole Milk", product_id="B0001"))
    entries = BrowserCart(driver, dry_run=False, delay=(0, 0)).submit(
        _lines(product_id="B0001")
    )
    assert driver.added == [1]
    assert entries[0].added is True
    assert "exact product id" in entries[0].detail
    assert any("/dp/B0001" in url for url in driver.visited)
    assert not any("/s?k=" in url for url in driver.visited)


def test_without_a_product_id_it_searches_and_adds_a_confident_match():
    driver = FakeDriver(results=[
        Candidate(name="Organic Whole Milk, 59 FZ", product_id="B1"),
        Candidate(name="Dog Food, 30 LB", product_id="B2"),
    ])
    entries = BrowserCart(driver, dry_run=False, delay=(0, 0)).submit(_lines())
    assert driver.added == [1]
    assert entries[0].added is True


def test_an_ambiguous_line_is_reported_and_left_out_of_the_cart():
    driver = FakeDriver(results=[
        Candidate(name="Organic Whole Milk, 59 FZ", product_id="B1"),
        Candidate(name="Organic Whole Milk, 64 FZ", product_id="B2"),
    ])
    entries = BrowserCart(driver, dry_run=False, delay=(0, 0)).submit(_lines())
    assert driver.added == []
    assert entries[0].added is False
    assert entries[0].detail.startswith("not added")


def test_a_dead_product_id_is_reported_rather_than_searched_around():
    driver = FakeDriver(product=None)
    entries = BrowserCart(driver, dry_run=False, delay=(0, 0)).submit(_lines(product_id="B0001"))
    assert driver.added == []
    assert "no longer resolves" in entries[0].detail


def test_it_refuses_to_run_when_nobody_signs_in():
    driver = FakeDriver(signed_in=False)
    with pytest.raises(NotSignedIn) as excinfo:
        BrowserCart(driver, dry_run=True, delay=(0, 0), sign_in_timeout=0).submit(_lines())
    # The message must not suggest handing it a password.
    assert "never enters credentials" in str(excinfo.value)


def test_it_never_asks_for_a_password():
    import inspect

    from whole_foods_agent import browser_cart

    source = inspect.getsource(browser_cart)
    for forbidden in ("ap_password\", \"", "fill(\"#ap_password", "AMAZON_PASSWORD", "type_password"):
        assert forbidden not in source
