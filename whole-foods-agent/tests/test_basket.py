from datetime import date, timedelta

from whole_foods_agent import basket, catalog as catalog_mod
from whole_foods_agent.model import LineItem, Order

START = date(2026, 1, 1)


def _history(specs, trips=6, every=7):
    """Build `trips` weekly orders; specs is name -> (cadence, price, qty)."""
    orders = []
    for index in range(trips):
        day = START + timedelta(days=every * index)
        items = []
        for name, (cadence, price, qty) in specs.items():
            if (every * index) % cadence == 0:
                items.append(
                    LineItem.from_raw(name, quantity=qty, unit="each", unit_price=price, line_total=price * qty)
                )
        if items:
            orders.append(Order(order_id=f"o{index}", ordered_on=day, items=items))
    return catalog_mod.build(orders)


def test_an_item_due_now_is_proposed():
    catalog = _history({"Organic Whole Milk": (7, 6.99, 1)})
    last = catalog.items["organic whole milk"].last_bought
    proposal = basket.build(catalog, on_date=last + timedelta(days=7))
    assert [line.name for line in proposal.lines] == ["Organic Whole Milk"]


def test_an_item_bought_yesterday_is_not_proposed():
    catalog = _history({"Organic Whole Milk": (7, 6.99, 1)})
    last = catalog.items["organic whole milk"].last_bought
    proposal = basket.build(catalog, on_date=last + timedelta(days=1))
    assert proposal.lines == []


def test_the_threshold_lets_a_nearly_due_item_through():
    catalog = _history({"Milk": (7, 6.99, 1)})
    last = catalog.items["milk"].last_bought
    on = last + timedelta(days=6)  # 6/7 = 0.857
    assert basket.build(catalog, on_date=on, due_threshold=0.8).lines
    assert not basket.build(catalog, on_date=on, due_threshold=0.9).lines


def test_a_one_off_purchase_is_a_suggestion_never_a_line():
    orders = [
        Order(
            order_id="o1",
            ordered_on=START,
            items=[LineItem.from_raw("Birthday Card", quantity=1, unit="each", unit_price=3.99, line_total=3.99)],
        )
    ]
    catalog = catalog_mod.build(orders)
    proposal = basket.build(catalog, on_date=START + timedelta(days=30))
    assert proposal.lines == []
    assert [s.name for s in proposal.suggestions] == ["Birthday Card"]


def test_something_long_overdue_is_flagged_as_lapsed_not_proposed():
    catalog = _history({"Milk": (7, 6.99, 1)})
    last = catalog.items["milk"].last_bought
    proposal = basket.build(catalog, on_date=last + timedelta(days=90))
    assert proposal.lines == []
    assert [s.name for s in proposal.lapsed] == ["Milk"]


def test_budget_trims_the_least_overdue_items_first():
    catalog = _history({"Milk": (7, 6.00, 1), "Eggs": (7, 7.00, 1), "Bread": (7, 5.00, 1)})
    last = max(s.last_bought for s in catalog.items.values())
    full = basket.build(catalog, on_date=last + timedelta(days=7))
    assert len(full.lines) == 3
    assert full.estimated_total == 18.00

    capped = basket.build(catalog, on_date=last + timedelta(days=7), budget=13.0)
    assert capped.estimated_total <= 13.0
    assert capped.trimmed
    assert len(capped.lines) + len(capped.trimmed) == 3
    assert any("to stay under" in note for note in capped.notes)


def test_max_items_caps_the_list():
    catalog = _history({"Milk": (7, 6.0, 1), "Eggs": (7, 7.0, 1), "Bread": (7, 5.0, 1)})
    last = max(s.last_bought for s in catalog.items.values())
    proposal = basket.build(catalog, on_date=last + timedelta(days=7), max_items=2)
    assert len(proposal.lines) == 2
    assert len(proposal.trimmed) == 1


def test_the_most_overdue_item_comes_first():
    catalog = _history({"Milk": (7, 6.0, 1), "Oats": (14, 4.0, 1)})
    last = max(s.last_bought for s in catalog.items.values())
    proposal = basket.build(catalog, on_date=last + timedelta(days=14))
    # Milk is two cycles late, oats one and a half.
    assert [line.name for line in proposal.lines] == ["Milk", "Oats"]
    assert proposal.lines[0].due_ratio > proposal.lines[1].due_ratio


def test_an_item_past_the_stale_cutoff_is_not_merely_very_overdue():
    # Three times its usual gap means it probably left the rotation, and
    # proposing it forever is how a list loses trust.
    catalog = _history({"Milk": (7, 6.0, 1)})
    last = catalog.items["milk"].last_bought
    assert basket.build(catalog, on_date=last + timedelta(days=20)).lines
    assert not basket.build(catalog, on_date=last + timedelta(days=21)).lines


def test_quantity_carries_over_from_history():
    catalog = _history({"Beans": (7, 1.69, 3)})
    last = catalog.items["beans"].last_bought
    proposal = basket.build(catalog, on_date=last + timedelta(days=7))
    assert proposal.lines[0].quantity == 3
    assert proposal.lines[0].estimated_cost == 5.07


def test_a_truncated_source_is_called_out_in_the_notes():
    orders = [
        Order(
            order_id="o1",
            ordered_on=START,
            items=[LineItem.from_raw("Milk", quantity=1, unit="each", unit_price=6.0, line_total=6.0)],
            stated_item_count=30,
        )
    ]
    proposal = basket.build(catalog_mod.build(orders), on_date=START + timedelta(days=7))
    assert any("partly itemised" in note for note in proposal.notes)


def test_lines_are_grouped_into_departments_in_shopping_order():
    catalog = _history({"Organic Whole Milk": (7, 6.0, 1), "Organic Baby Spinach": (7, 4.0, 1)})
    last = max(s.last_bought for s in catalog.items.values())
    proposal = basket.build(catalog, on_date=last + timedelta(days=7))
    assert list(proposal.by_department()) == ["Produce", "Dairy & eggs"]
