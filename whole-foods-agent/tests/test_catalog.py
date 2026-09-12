from datetime import date, timedelta

from whole_foods_agent import catalog as catalog_mod
from whole_foods_agent.model import LineItem, Order


def _order(day: date, names, order_id="x"):
    return Order(
        order_id=f"{order_id}-{day.isoformat()}",
        ordered_on=day,
        items=[
            LineItem.from_raw(name, quantity=qty, unit="each", unit_price=price, line_total=qty * price)
            for name, qty, price in names
        ],
    )


def test_cadence_is_the_median_gap_between_purchases():
    start = date(2026, 1, 1)
    orders = [_order(start + timedelta(days=7 * i), [("Organic Whole Milk", 1, 6.99)]) for i in range(5)]
    catalog = catalog_mod.build(orders)
    milk = catalog.items[list(catalog.items)[0]]
    assert milk.times_bought == 5
    assert milk.median_interval == 7
    assert milk.has_cadence


def test_a_single_purchase_has_no_cadence():
    catalog = catalog_mod.build([_order(date(2026, 1, 1), [("Birthday Card", 1, 3.99)])])
    card = catalog.items[list(catalog.items)[0]]
    assert card.times_bought == 1
    assert card.median_interval is None
    assert not card.has_cadence


def test_due_ratio_passes_one_when_the_usual_gap_has_elapsed():
    start = date(2026, 1, 1)
    orders = [_order(start + timedelta(days=10 * i), [("Pretzels", 1, 4.39)]) for i in range(4)]
    catalog = catalog_mod.build(orders)
    pretzels = catalog.items[list(catalog.items)[0]]
    last = pretzels.last_bought
    assert pretzels.due_ratio(last + timedelta(days=10)) == 1.0
    assert pretzels.due_ratio(last + timedelta(days=5)) == 0.5


def test_latest_price_is_used_not_the_first():
    orders = [
        _order(date(2026, 1, 1), [("Milk", 1, 5.99)]),
        _order(date(2026, 1, 8), [("Milk", 1, 6.99)]),
    ]
    catalog = catalog_mod.build(orders)
    milk = catalog.items[list(catalog.items)[0]]
    assert milk.last_price == 6.99


def test_fees_never_enter_the_catalog():
    catalog = catalog_mod.build(
        [_order(date(2026, 1, 1), [("CUSTOMER SERVICES Bag Fee", 1, 0.0), ("Milk", 1, 6.99)])]
    )
    assert len(catalog.items) == 1


def test_co_occurrence_counts_shared_trips():
    orders = [
        _order(date(2026, 1, 1), [("Milk", 1, 6.0), ("Cereal", 1, 4.0)]),
        _order(date(2026, 1, 8), [("Milk", 1, 6.0), ("Cereal", 1, 4.0)]),
        _order(date(2026, 1, 15), [("Milk", 1, 6.0)]),
    ]
    catalog = catalog_mod.build(orders)
    assert "cereal" in catalog.partners("milk", minimum=2)
    assert catalog.partners("milk", minimum=3) == []


def test_typical_quantity_is_the_median():
    orders = [
        _order(date(2026, 1, 1), [("Beans", 1, 1.69)]),
        _order(date(2026, 1, 8), [("Beans", 3, 1.69)]),
        _order(date(2026, 1, 15), [("Beans", 3, 1.69)]),
    ]
    catalog = catalog_mod.build(orders)
    beans = catalog.items[list(catalog.items)[0]]
    assert beans.typical_quantity == 3
