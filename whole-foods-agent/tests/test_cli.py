import json
from datetime import date

import pytest

from whole_foods_agent.cli import main
from whole_foods_agent.model import LineItem, Order
from whole_foods_agent.store import OrderStore

from fixtures import RECEIPT_HTML


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    data = tmp_path / "data"
    out = tmp_path / "out"
    monkeypatch.setenv("WFA_DATA_DIR", str(data))
    monkeypatch.setenv("WFA_OUT_DIR", str(out))
    # Never inherit real mail settings from the developer's environment.
    for name in ("WFA_MAIL_TO", "WFA_MAIL_FROM", "GMAIL_APP_PASSWORD", "WFA_BUDGET", "WFA_MAX_ITEMS"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path, data, out


def _seed(data, days_ago_spacing=7, trips=5):
    from datetime import timedelta

    today = date.today()
    orders = [
        Order(
            order_id=f"113-0000000-000000{i}",
            ordered_on=today - timedelta(days=days_ago_spacing * (trips - i)),
            items=[
                LineItem.from_raw("Organic Whole Milk, 59 FZ", quantity=1, unit="each", unit_price=6.99, line_total=6.99)
            ],
        )
        for i in range(trips)
    ]
    store = OrderStore()
    store.merge(orders)
    store.save(data / "orders.json")


def test_demo_runs_and_writes_a_sheet(workspace, capsys):
    _, _, out = workspace
    assert main(["demo", "--days", "120"]) == 0
    assert (out / "order.html").is_file()
    assert "Whole Foods order" in capsys.readouterr().out


def test_import_reads_a_receipt_file(workspace, capsys):
    tmp_path, data, _ = workspace
    receipt = tmp_path / "receipt.html"
    receipt.write_text(RECEIPT_HTML, encoding="utf-8")

    assert main(["import", str(receipt)]) == 0
    assert "History now holds 1 orders" in capsys.readouterr().out

    saved = json.loads((data / "orders.json").read_text())
    assert "113-0000000-0000001" in saved["orders"]


def test_import_accepts_a_folder(workspace, capsys):
    tmp_path, data, _ = workspace
    folder = tmp_path / "receipts"
    folder.mkdir()
    (folder / "a.html").write_text(RECEIPT_HTML, encoding="utf-8")
    assert main(["import", str(folder)]) == 0
    assert len(OrderStore.load(data / "orders.json")) == 1


def test_import_skips_files_that_are_not_receipts(workspace, capsys):
    tmp_path, _, _ = workspace
    junk = tmp_path / "junk.html"
    junk.write_text("<html><body>hello</body></html>", encoding="utf-8")
    assert main(["import", str(junk)]) == 0
    assert "Read 0 orders from 1 file" in capsys.readouterr().out


def test_commands_explain_themselves_when_there_is_no_history(workspace):
    with pytest.raises(SystemExit) as excinfo:
        main(["order"])
    assert "No orders in the local history" in str(excinfo.value)


def test_order_prints_the_list(workspace, capsys):
    _, data, _ = workspace
    _seed(data)
    assert main(["order"]) == 0
    assert "Organic Whole Milk" in capsys.readouterr().out


def test_order_html_writes_a_file(workspace):
    _, data, out = workspace
    _seed(data)
    assert main(["order", "--html"]) == 0
    assert (out / "order.html").is_file()


def test_items_lists_the_catalogue(workspace, capsys):
    _, data, _ = workspace
    _seed(data)
    assert main(["items"]) == 0
    output = capsys.readouterr().out
    assert "Organic Whole Milk" in output
    assert "distinct items" in output


def test_cart_defaults_to_links_and_adds_nothing(workspace, capsys):
    _, data, _ = workspace
    _seed(data)
    assert main(["cart"]) == 0
    output = capsys.readouterr().out
    assert "amazon.com/s?k=" in output
    assert "0 added to a cart automatically" in output


def test_cart_via_browser_says_what_it_needs(workspace, capsys):
    # Without Playwright or a profile it must explain itself, not traceback.
    _, data, _ = workspace
    _seed(data)
    with pytest.raises(SystemExit) as excinfo:
        main(["cart", "--via", "browser"])
    message = str(excinfo.value)
    assert "playwright" in message.lower() or "profile" in message.lower()


def test_cart_via_browser_is_dry_run_unless_confirmed(workspace, capsys):
    _, data, _ = workspace
    _seed(data)
    with pytest.raises(SystemExit):
        main(["cart", "--via", "browser"])
    assert "Dry run: nothing will be added" in capsys.readouterr().out


def test_import_reads_an_amazon_export(workspace, capsys):
    tmp_path, data, _ = workspace
    export = tmp_path / "Retail.OrderHistory.1.csv"
    export.write_text(
        '"Website","Order ID","Order Date","Unit Price","Quantity","ASIN","Product Name"\n'
        '"Whole Foods Market","113-0000000-0000021","2026-08-23","6.99","1","B0001","Organic Whole Milk, 59 FZ"\n'
        '"Amazon.com","111-1111111-1111111","2026-08-23","19.99","1","B0002","Phone Case"\n',
        encoding="utf-8",
    )
    assert main(["import", str(export)]) == 0
    out = capsys.readouterr().out
    assert "History now holds 1 orders" in out

    saved = OrderStore.load(data / "orders.json").orders()
    assert [i.name for i in saved[0].items] == ["Organic Whole Milk"]
    # The ASIN must survive into the store; it is what makes a cart match exact.
    assert saved[0].items[0].product_id == "B0001"


def test_an_export_gives_exact_product_links(workspace, capsys):
    from datetime import timedelta

    tmp_path, data, _ = workspace
    today = date.today()
    # Weekly purchases ending a week ago, so the item is due now.
    rows = "".join(
        '"Whole Foods Market","113-0000000-000003{i}","{day}",'
        '"6.99","1","B0001","Organic Whole Milk, 59 FZ"\n'.format(
            i=i, day=(today - timedelta(days=7 * (4 - i))).isoformat()
        )
        for i in range(4)
    )
    export = tmp_path / "Retail.OrderHistory.1.csv"
    export.write_text(
        '"Website","Order ID","Order Date","Unit Price","Quantity","ASIN","Product Name"\n' + rows,
        encoding="utf-8",
    )
    assert main(["import", str(export)]) == 0
    capsys.readouterr()
    assert main(["cart"]) == 0
    out = capsys.readouterr().out
    assert "/dp/B0001" in out
    assert "exact product link" in out
