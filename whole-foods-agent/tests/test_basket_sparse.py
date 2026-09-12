"""Selection rules for sporadic shopping, not a tidy weekly shop.

Every case here comes from a real seven-year export: roughly monthly orders,
hundreds of items bought once or twice, and long-abandoned products whose two
purchases years apart produce a confident-looking "cadence" of 500 days.
"""

from datetime import date, timedelta

from whole_foods_agent import basket, catalog as catalog_mod
from whole_foods_agent.model import LineItem, Order

TODAY = date(2026, 9, 12)


def _bought_on(name, days_ago_list, price=4.99, quantity=1):
    """History for one item, bought this many days before TODAY."""
    return [
        Order(
            order_id=f"{name}-{days}",
            ordered_on=TODAY - timedelta(days=days),
            items=[
                LineItem.from_raw(
                    name,
                    quantity=quantity,
                    unit="each",
                    unit_price=price,
                    line_total=price * quantity,
                )
            ],
        )
        for days in days_ago_list
    ]


def _propose(orders, **kwargs):
    return basket.build(catalog_mod.build(orders), on_date=TODAY, **kwargs)


def test_two_purchases_years_apart_are_not_a_rhythm():
    # Bought twice, 511 days apart, last seen three and a half years ago.
    # The ratio test alone calls this only 2.5x overdue and proposes it.
    proposal = _propose(_bought_on("Black and White Cookie", [1281, 1792]))
    assert proposal.lines == []


def test_three_purchases_are_required_by_default():
    twice = _propose(_bought_on("Sushi Combo", [40, 70]))
    assert twice.lines == []
    thrice = _propose(_bought_on("Sushi Combo", [40, 70, 100]))
    assert [line.name for line in thrice.lines] == ["Sushi Combo"]


def test_an_item_bought_every_eight_months_is_not_replenishment():
    # Regular, but on a gap too long to predict a next purchase from.
    proposal = _propose(_bought_on("Seasonal Cereal", [100, 340, 580]))
    assert proposal.lines == []
    assert any("less often than" in reason for reason in proposal.excluded)


def test_an_item_not_bought_in_months_is_lapsed_however_overdue():
    # A real trap: fortnightly for a year, then stopped two years ago. The
    # ratio is enormous but the honest answer is that it left the rotation.
    days = [730 + 14 * n for n in range(6)]
    proposal = _propose(_bought_on("Cashewmilk", days))
    assert proposal.lines == []
    assert [s.name for s in proposal.lapsed] == ["Cashewmilk"]


def test_a_genuine_staple_still_gets_through():
    # Monthly for half a year, due now: exactly what should be proposed.
    proposal = _propose(_bought_on("Broccoli Crowns", [50, 79, 108, 137, 166, 195]))
    assert [line.name for line in proposal.lines] == ["Broccoli Crowns"]
    assert proposal.lines[0].due_ratio > 1.0


def test_something_bought_yesterday_is_not_due():
    proposal = _propose(_bought_on("Bananas", [1, 30, 60, 90]))
    assert proposal.lines == []


def test_the_bars_are_adjustable():
    orders = _bought_on("Sushi Combo", [40, 70])
    assert _propose(orders).lines == []
    assert _propose(orders, min_purchases=2).lines


def test_an_empty_list_explains_itself():
    # Hundreds of one-off items and nothing due is a normal outcome for this
    # kind of history; it must not read as a broken tool.
    orders = []
    for n in range(12):
        orders.extend(_bought_on(f"One-off {n}", [200 + n * 30]))
    proposal = _propose(orders)
    assert proposal.lines == []
    assert any("Nothing is due" in note for note in proposal.notes)


def test_a_proposed_list_says_how_much_it_left_out():
    orders = _bought_on("Broccoli Crowns", [50, 79, 108, 137, 166, 195])
    for n in range(5):
        orders.extend(_bought_on(f"One-off {n}", [300 + n * 30]))
    proposal = _propose(orders)
    assert proposal.lines
    assert any("other items were not proposed" in note for note in proposal.notes)


def test_rejections_are_counted_by_reason():
    orders = _bought_on("Rare Thing", [100, 340, 580]) + _bought_on("Once", [400])
    proposal = _propose(orders)
    assert sum(proposal.excluded.values()) >= 2
