from datetime import date

import pytest

from whole_foods_agent.amazon_export import (
    ExportError,
    find_exports,
    map_columns,
    parse_export,
)

# The current "Request My Data" retail export.
MODERN = """﻿"Website","Order ID","Order Date","Currency","Unit Price","Total Owed","ASIN","Quantity","Product Name"
"Whole Foods Market","113-0000000-0000001","2026-08-23T20:32:24Z","USD","3.69","3.69","B0001","1","Organic Rainbow Carrot Bag, 32 OZ"
"Whole Foods Market","113-0000000-0000001","2026-08-23T20:32:24Z","USD","1.69","5.07","B0002","3","365 Organic Cannellini Beans, 15.5 OZ"
"Amazon.com","111-2222222-3333333","2026-08-24T10:00:00Z","USD","24.99","24.99","B0003","1","Wireless Keyboard"
"Whole Foods Market","113-0000000-0000002","2026-08-30T18:00:00Z","USD","6.99","6.99","B0004","1","Organic Whole Milk, 59 FZ"
"""

# The older order history report, which disagrees on nearly every heading.
LEGACY = """"Order Date","Order ID","Title","ASIN/ISBN","Purchase Price Per Unit","Quantity","Item Subtotal","Website"
"09/07/2026","113-0000000-0000009","Organic Garlic, 3 CT","B0009","$2.69","1","$2.69","Whole Foods Market"
"09/07/2026","113-0000000-0000009","Organic Sweet Onion","B0010","$2.99","2","$5.98","Whole Foods Market"
"""


def _write(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_columns_are_matched_by_alias_not_position():
    mapping = map_columns(["Order Date", "Order ID", "Title", "ASIN/ISBN", "Quantity"])
    assert mapping["ordered_on"] == "Order Date"
    assert mapping["name"] == "Title"
    assert mapping["product_id"] == "ASIN/ISBN"


def test_a_byte_order_mark_does_not_hide_the_first_column():
    mapping = map_columns(["﻿Website", "Order ID"])
    assert "website" in mapping


def test_modern_export_groups_rows_into_orders(tmp_path):
    orders = parse_export(_write(tmp_path, "Retail.OrderHistory.1.csv", MODERN))
    assert [o.order_id for o in orders] == ["113-0000000-0000001", "113-0000000-0000002"]
    assert len(orders[0].items) == 2


def test_non_grocery_orders_are_left_out(tmp_path):
    orders = parse_export(_write(tmp_path, "export.csv", MODERN))
    assert all("Whole Foods" in (o.store or "") for o in orders)
    assert not any(i.name == "Wireless Keyboard" for o in orders for i in o.items)


def test_every_storefront_can_be_kept_deliberately(tmp_path):
    orders = parse_export(_write(tmp_path, "export.csv", MODERN), stores=None)
    assert any(i.name == "Wireless Keyboard" for o in orders for i in o.items)


def test_asin_is_captured(tmp_path):
    orders = parse_export(_write(tmp_path, "export.csv", MODERN))
    carrots = next(i for o in orders for i in o.items if "Carrot" in i.name)
    assert carrots.product_id == "B0001"


def test_quantities_and_totals(tmp_path):
    orders = parse_export(_write(tmp_path, "export.csv", MODERN))
    beans = next(i for o in orders for i in o.items if "Cannellini" in i.name)
    assert beans.quantity == 3
    assert beans.unit_price == 1.69
    assert beans.line_total == 5.07


def test_iso_timestamps_become_dates(tmp_path):
    orders = parse_export(_write(tmp_path, "export.csv", MODERN))
    assert orders[0].ordered_on == date(2026, 8, 23)


def test_legacy_report_parses_too(tmp_path):
    orders = parse_export(_write(tmp_path, "old.csv", LEGACY))
    assert len(orders) == 1
    assert orders[0].ordered_on == date(2026, 9, 7)
    names = {i.name for i in orders[0].items}
    assert names == {"Organic Garlic", "Organic Sweet Onion"}


def test_currency_symbols_are_stripped(tmp_path):
    orders = parse_export(_write(tmp_path, "old.csv", LEGACY))
    onion = next(i for i in orders[0].items if "Onion" in i.name)
    assert onion.unit_price == 2.99
    assert onion.line_total == 5.98


def test_a_missing_unit_price_is_derived_from_the_line_total(tmp_path):
    body = (
        '"Website","Order ID","Order Date","Total Owed","Quantity","Product Name"\n'
        '"Whole Foods Market","113-0000000-0000005","2026-08-23","9.00","3","Beans"\n'
    )
    orders = parse_export(_write(tmp_path, "x.csv", body))
    assert orders[0].items[0].unit_price == 3.0


def test_export_orders_are_never_flagged_truncated(tmp_path):
    # Unlike a receipt email, an export lists every line.
    orders = parse_export(_write(tmp_path, "export.csv", MODERN))
    assert all(not o.truncated for o in orders)


def test_delivery_channel_is_recorded(tmp_path):
    orders = parse_export(_write(tmp_path, "export.csv", MODERN))
    assert orders[0].channel == "delivery"


def test_a_file_that_is_not_an_export_is_rejected(tmp_path):
    path = _write(tmp_path, "nope.csv", "a,b,c\n1,2,3\n")
    with pytest.raises(ExportError) as excinfo:
        parse_export(path)
    assert "does not look like an Amazon order export" in str(excinfo.value)


def test_rows_missing_essentials_are_skipped_not_fatal(tmp_path):
    body = (
        '"Website","Order ID","Order Date","Unit Price","Quantity","Product Name"\n'
        '"Whole Foods Market","","2026-08-23","1.00","1","No order id"\n'
        '"Whole Foods Market","113-0000000-0000007","","1.00","1","No date"\n'
        '"Whole Foods Market","113-0000000-0000008","2026-08-23","1.00","1","Good row"\n'
    )
    orders = parse_export(_write(tmp_path, "x.csv", body))
    assert len(orders) == 1
    assert orders[0].items[0].name == "Good row"


def test_find_exports_picks_order_history_files_out_of_an_unzipped_export(tmp_path):
    (tmp_path / "Retail.OrderHistory.1").mkdir(parents=True)
    wanted = tmp_path / "Retail.OrderHistory.1" / "Retail.OrderHistory.1.csv"
    wanted.write_text(MODERN, encoding="utf-8")
    (tmp_path / "Digital.Music.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    assert list(find_exports(tmp_path)) == [wanted]
