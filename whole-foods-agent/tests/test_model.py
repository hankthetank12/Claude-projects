from datetime import date

from whole_foods_agent.model import (
    LineItem,
    Order,
    canonical_key,
    guess_department,
    is_non_grocery,
    merge_duplicate_lines,
    split_size,
)


def test_receipt_spelling_variants_collapse_to_one_item():
    # The same onion, with and without the receipt's department prefix.
    assert canonical_key("PRODUCE Organic Sweet Onion") == canonical_key("Organic Sweet Onion")


def test_package_size_does_not_split_an_item():
    assert canonical_key("Organic Red Raspberries, 6 Oz") == canonical_key("Organic Red Raspberries, 6 OZ")
    assert canonical_key("Rummo Pasta, 16 OZ") == canonical_key("Rummo Pasta")


def test_accents_and_punctuation_do_not_split_an_item():
    assert canonical_key("Cypress Grove Fresh Chèvre") == canonical_key("Cypress Grove Fresh Chevre")


def test_different_products_stay_distinct():
    a = canonical_key("San Pellegrino Sparkling Mineral Water, 33.8 FZ")
    b = canonical_key("San Pellegrino Carbonated Natural Mineral Water, 25.3 FZ")
    assert a != b


def test_split_size():
    assert split_size("Organic Garlic, 3 CT") == ("Organic Garlic", "3 CT")
    assert split_size("Organic Green Asparagus") == ("Organic Green Asparagus", None)


def test_fees_and_deposits_are_recognised():
    assert is_non_grocery("CUSTOMER SERVICES Bag Fee")
    assert is_non_grocery("Container Deposit Single Container Deposit")
    assert not is_non_grocery("Organic Garlic, 3 CT")


def test_departments():
    # "Organic" alone must not drag everything into produce.
    assert guess_department("365 Organic Cannellini Beans") == "Pantry"
    # Broth is pantry stock, not meat, despite the word chicken.
    assert guess_department("Kettle & Fire Organic Chicken Broth") == "Pantry"
    assert guess_department("Bell & Evans Organic Ground Chicken") == "Meat & seafood"
    assert guess_department("Organic Green Asparagus") == "Produce"
    assert guess_department("Numa Banana Cream Taffy") == "Snacks"
    # An unrecognised organic something is produce by default.
    assert guess_department("Organic Romanesco") == "Produce"


def test_units_listed_counts_units_not_lines():
    order = Order(
        order_id="1",
        ordered_on=date(2026, 1, 1),
        items=[
            LineItem.from_raw("Beans", quantity=3, unit="each"),
            LineItem.from_raw("Cheese", quantity=0.45, unit="lb"),
        ],
        stated_item_count=4,
    )
    # Three tins plus one piece of cheese, however much it weighed.
    assert order.units_listed == 4
    assert order.truncated is False


def test_repeated_lines_in_one_order_are_merged():
    merged = merge_duplicate_lines(
        [
            LineItem.from_raw("Organic Garlic, 3 CT", quantity=1, line_total=2.69),
            LineItem.from_raw("Organic Garlic", quantity=2, line_total=5.38),
        ]
    )
    assert len(merged) == 1
    assert merged[0].quantity == 3
    assert merged[0].line_total == 8.07
