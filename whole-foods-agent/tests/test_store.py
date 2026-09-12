from datetime import date

from whole_foods_agent.model import LineItem, Order
from whole_foods_agent.store import OrderStore


def _order(order_id="113-0000000-0000001", items=1, stated=None):
    return Order(
        order_id=order_id,
        ordered_on=date(2026, 5, 1),
        items=[
            LineItem.from_raw(f"Item {n}", quantity=1, unit="each", unit_price=1.0, line_total=1.0)
            for n in range(items)
        ],
        stated_item_count=stated,
    )


def test_round_trip(tmp_path):
    path = tmp_path / "orders.json"
    store = OrderStore()
    store.merge([_order()])
    store.save(path)

    reloaded = OrderStore.load(path)
    assert len(reloaded) == 1
    order = reloaded.orders()[0]
    assert order.order_id == "113-0000000-0000001"
    assert order.ordered_on == date(2026, 5, 1)
    assert order.items[0].name == "Item 0"


def test_the_same_order_twice_is_not_counted_twice():
    store = OrderStore()
    assert store.merge([_order()]) == 1
    assert store.merge([_order()]) == 0
    assert len(store) == 1


def test_a_fuller_record_is_not_replaced_by_a_thinner_one():
    # A receipt email lists 20 lines; an export of the same order lists 30.
    store = OrderStore()
    store.merge([_order(items=30)])
    store.merge([_order(items=20)])
    assert len(store.orders()[0].items) == 30


def test_a_fuller_record_replaces_a_thinner_one():
    store = OrderStore()
    store.merge([_order(items=20)])
    store.merge([_order(items=30)])
    assert len(store.orders()[0].items) == 30


def test_orders_come_back_oldest_first():
    store = OrderStore()
    store.merge([_order(order_id="b"), _order(order_id="a")])
    assert [o.order_id for o in store.orders()] == ["a", "b"]


def test_a_corrupt_file_does_not_crash(tmp_path):
    path = tmp_path / "orders.json"
    path.write_text("{not json", encoding="utf-8")
    assert len(OrderStore.load(path)) == 0
