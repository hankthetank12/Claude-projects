import json

from watch_auctions import cli


def test_demo_writes_page_and_marks_new_lots(tmp_path, capsys):
    assert cli.main(["demo", "--out", str(tmp_path)]) == 0
    page = (tmp_path / "index.html").read_text()
    assert "Upcoming watch lots" in page and "Rolex Submariner" in page
    assert len(json.loads((tmp_path / "lots.json").read_text())) == 7
    assert {r["title"] for r in json.loads((tmp_path / "rejected.json").read_text())} >= {"Fossil Men's Chronograph Watch FS4656"}
    # Second run: drop one lot from the saved file so it shows up as new.
    data = json.loads((tmp_path / "lots.json").read_text())
    (tmp_path / "lots.json").write_text(json.dumps(data[1:]))
    cli.main(["demo", "--out", str(tmp_path)])
    assert "(1 new, 1 junk lots dropped)" in capsys.readouterr().out


def test_page_escapes_script_breakout(tmp_path):
    from watch_auctions import render
    from watch_auctions.models import Lot
    html = render.render([Lot(source="x", source_id="1", title="</script><b>", url="u", house="h")], set())
    assert "</script><b>" not in html
