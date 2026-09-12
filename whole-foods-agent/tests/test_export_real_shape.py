"""Regression tests for the shape of a real Amazon order export.

Real column names, entirely invented products and identifiers — no one's
shopping history belongs in a test suite. Every case here stands for a bug
that a live export actually caused.
"""

from datetime import date

from whole_foods_agent.amazon_export import find_exports, parse_export

# Column names exactly as the current export writes them, including the
# order-level "Shipment Item Subtotal" repeated on every row.
REAL_SHAPE = '''"ASIN","Department","Order Date","Order ID","Order Status","Original Quantity","Product Name","Shipment Item Subtotal","Shipment Status","Total Amount","Unit Price","Website"
"BTEST000001","Not Available","2026-09-11T12:52:29.461Z","113-0000000-0000001","Closed","1","Sparkling Vitamin Water, 20 FZ","25.65","Shipped","2.49","2.49","wholefoods.com"
"BTEST000002","Not Available","2026-09-11T12:52:29.461Z","113-0000000-0000001","Closed","2","Broccoli Microgreens, 2 OZ","25.65","Shipped","9.98","4.99","wholefoods.com"
"BTEST000003","Not Available","2026-09-11T12:52:29.461Z","113-0000000-0000001","Closed","1","CUSTOMER SERVICES Bag Fee","25.65","Shipped","0","0","wholefoods.com"
"BTEST000004","Not Available","2026-09-11T12:52:29.461Z","113-0000000-0000002","Cancelled","1","Cancelled Thing","9.99","Cancelled","9.99","9.99","wholefoods.com"
"BTEST000005","Electronics","2026-09-10T10:00:00.000Z","111-0000000-0000003","Closed","1","Wireless Keyboard","24.99","Shipped","24.99","24.99","Amazon.com"
"BTEST000006","Grocery","2026-09-09T10:00:00.000Z","113-0000000-0000004","Closed","1","Store Sparkling Water, 12 FZ","1.99","Shipped","1.99","1.99","Amazon Go"
'''


def _write(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_the_storefront_is_spelled_wholefoods_dot_com(tmp_path):
    # The export says "wholefoods.com", with no space. Matching only on
    # "whole foods" silently drops every grocery row in the file.
    orders = parse_export(_write(tmp_path, "Order History.csv", REAL_SHAPE))
    assert any(o.order_id == "113-0000000-0000001" for o in orders)


def test_amazon_go_counts_as_grocery(tmp_path):
    orders = parse_export(_write(tmp_path, "Order History.csv", REAL_SHAPE))
    assert any(o.order_id == "113-0000000-0000004" for o in orders)


def test_ordinary_retail_is_still_excluded(tmp_path):
    orders = parse_export(_write(tmp_path, "Order History.csv", REAL_SHAPE))
    assert not any(i.name == "Wireless Keyboard" for o in orders for i in o.items)


def test_original_quantity_is_read(tmp_path):
    # The column is "Original Quantity". Missing it makes every line qty 1.
    orders = parse_export(_write(tmp_path, "Order History.csv", REAL_SHAPE))
    greens = next(i for o in orders for i in o.items if "Microgreens" in i.name)
    assert greens.quantity == 2


def test_an_order_level_subtotal_is_not_used_as_a_line_total(tmp_path):
    # Every row repeats the order subtotal 25.65. Read as a line total that
    # multiplies the order's spend by its line count.
    orders = parse_export(_write(tmp_path, "Order History.csv", REAL_SHAPE))
    order = next(o for o in orders if o.order_id == "113-0000000-0000001")
    water = next(i for i in order.items if "Vitamin Water" in i.name)
    greens = next(i for i in order.items if "Microgreens" in i.name)
    assert water.line_total == 2.49
    assert greens.line_total == 9.98
    assert order.subtotal == 12.47


def test_a_repeated_total_is_recomputed_from_unit_prices(tmp_path):
    # The same trap, where the chosen total column is the order-level one.
    body = (
        '"Order ID","Order Date","Product Name","Original Quantity","Unit Price","Total Amount","Website"\n'
        '"113-0000000-0000010","2026-09-01","Milk","1","6.99","30.00","wholefoods.com"\n'
        '"113-0000000-0000010","2026-09-01","Beans","3","1.69","30.00","wholefoods.com"\n'
    )
    orders = parse_export(_write(tmp_path, "x.csv", body))
    milk = next(i for i in orders[0].items if i.name == "Milk")
    beans = next(i for i in orders[0].items if i.name == "Beans")
    assert milk.line_total == 6.99
    assert beans.line_total == 5.07


def test_cancelled_rows_are_not_purchases(tmp_path):
    orders = parse_export(_write(tmp_path, "Order History.csv", REAL_SHAPE))
    assert not any(i.name == "Cancelled Thing" for o in orders for i in o.items)


def test_millisecond_timestamps_parse(tmp_path):
    orders = parse_export(_write(tmp_path, "Order History.csv", REAL_SHAPE))
    order = next(o for o in orders if o.order_id == "113-0000000-0000001")
    assert order.ordered_on == date(2026, 9, 11)


def test_fees_still_do_not_count_as_groceries(tmp_path):
    orders = parse_export(_write(tmp_path, "Order History.csv", REAL_SHAPE))
    order = next(o for o in orders if o.order_id == "113-0000000-0000001")
    assert len(order.items) == 3
    assert len(order.grocery_items) == 2


def test_every_line_carries_its_product_id(tmp_path):
    # An id per line is what lets a cart match exactly instead of guessing.
    orders = parse_export(_write(tmp_path, "Order History.csv", REAL_SHAPE))
    order = next(o for o in orders if o.order_id == "113-0000000-0000001")
    assert all(item.product_id for item in order.items)


def test_find_exports_matches_the_real_filename(tmp_path):
    folder = tmp_path / "Your Amazon Orders"
    folder.mkdir()
    wanted = folder / "Order History.csv"
    wanted.write_text(REAL_SHAPE, encoding="utf-8")
    assert list(find_exports(tmp_path)) == [wanted]
