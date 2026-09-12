from datetime import date

import pytest

from fixtures import RECEIPT_HTML, RECEIPT_TEXT, TRUNCATED_HTML
from whole_foods_agent.receipts import (
    ReceiptError,
    parse_receipt_html,
    parse_receipt_text,
    visible_lines,
)


@pytest.fixture
def order():
    return parse_receipt_html(RECEIPT_HTML)


def test_reads_the_header(order):
    assert order.order_id == "113-0000000-0000001"
    assert order.ordered_on == date(2026, 8, 23)
    assert order.store == "Whole Foods Market - Example Street"


def test_total_is_not_confused_with_total_savings(order):
    assert order.subtotal == 44.06
    assert order.total == 42.75
    assert order.savings == -1.49
    assert order.tax == 0.18


def test_parses_every_line(order):
    assert len(order.items) == 8
    assert order.stated_item_count == 11


def test_each_priced_item(order):
    carrots = next(i for i in order.items if "Carrot" in i.name)
    assert carrots.quantity == 1
    assert carrots.unit == "each"
    assert carrots.unit_price == 3.69
    assert carrots.line_total == 3.69
    assert carrots.size == "32 OZ"


def test_weighed_item_keeps_its_weight_and_per_pound_price(order):
    cheese = next(i for i in order.items if "Parmigiano" in i.name)
    assert cheese.quantity == 0.45
    assert cheese.unit == "lb"
    assert cheese.unit_price == 26.99
    assert cheese.line_total == 12.15


def test_multiple_units(order):
    beans = next(i for i in order.items if "Cannellini" in i.name)
    assert beans.quantity == 3
    assert beans.line_total == 5.07


def test_promotion_is_captured_and_line_total_is_the_discounted_one(order):
    berries = next(i for i in order.items if "Raspberries" in i.name)
    assert berries.unit_price == 4.99
    assert berries.line_total == 3.50
    assert berries.promotion == 1.49


def test_line_totals_reconcile_with_the_receipt_arithmetic(order):
    # Line totals are post-discount, so they sum to subtotal less savings.
    total = round(sum(i.line_total for i in order.items), 2)
    assert total == round(order.subtotal + order.savings, 2)


def test_fees_and_deposits_are_not_groceries(order):
    names = {i.name for i in order.grocery_items}
    assert not any("Bag Fee" in n for n in names)
    assert not any("Container Deposit" in n for n in names)
    assert len(order.grocery_items) == 6


def test_department_prefix_is_stripped_from_the_name(order):
    onion = next(i for i in order.items if "Onion" in i.name)
    assert onion.name == "Organic Sweet Onion"
    assert onion.department == "Produce"


def test_outlook_conditional_markup_does_not_become_an_item(order):
    # The fixture embeds an mso block whose href contains a ">" character.
    for item in order.items:
        assert "href=" not in item.raw_name
        assert "https" not in item.raw_name
        assert len(item.raw_name) < 120


def test_style_blocks_are_not_read_as_text():
    lines = visible_lines(RECEIPT_HTML)
    assert not any("color:#fff" in line for line in lines)


def test_full_receipt_is_not_flagged_as_truncated(order):
    # Eleven units across eight lines: two lines had quantities above one.
    assert order.units_listed == 11
    assert order.truncated is False


def test_partial_receipt_is_flagged():
    order = parse_receipt_html(TRUNCATED_HTML)
    assert order.stated_item_count == 30
    assert order.units_listed == 4
    assert order.truncated is True


def test_plain_text_fallback_gets_names_without_prices():
    order = parse_receipt_text(RECEIPT_TEXT)
    assert order.order_id == "113-0000000-0000003"
    assert {i.name for i in order.grocery_items} == {"Organic Garlic", "Organic Rosemary"}
    assert all(i.unit_price is None for i in order.items)


def test_a_message_that_is_not_a_receipt_is_rejected():
    with pytest.raises(ReceiptError):
        parse_receipt_html("<html><body><p>Your package shipped</p></body></html>")
