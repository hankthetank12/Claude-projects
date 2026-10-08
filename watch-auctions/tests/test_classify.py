import pytest

from watch_auctions.classify import detect_brand, is_major_house, is_watch


@pytest.mark.parametrize("title", [
    "Rolex Submariner 16610 Stainless Steel Automatic",
    "Vintage Hamilton 14K Gold Filled Wrist Watch",
    "Elgin 14K Hunter Case Pocket Watch c. 1910",
    "Omega Speedmaster Professional 145.022",
    "Patek Philippe Calatrava 3919",
    "Seiko 6139-6002 Pogue Chronograph",
])
def test_watches(title):
    assert is_watch(title)


@pytest.mark.parametrize("title", [
    "Lot of 12 Watch Bands Only",
    "Rolex Watch Box Only",
    "A Precise History of Rolex Watches (book)",
    "Seth Thomas Mantel Clock",
    "Antique Gold Watch Fob",
    "Pair of Silver Candlesticks",
])
def test_not_watches(title):
    assert not is_watch(title)


@pytest.mark.parametrize("title,brand", [
    ("ROLEX. A STAINLESS STEEL AUTOMATIC WRISTWATCH", "Rolex"),
    ("Jaeger-LeCoultre Reverso Classique", "Jaeger-LeCoultre"),
    ("Vintage LeCoultre Memovox", "Jaeger-LeCoultre"),
    ("Heuer Autavia chronograph", "TAG Heuer"),
    ("A. Lange & Söhne Lange 1", "A. Lange & Sohne"),
    ("1917 Illinois Bunn Special 21J pocket watch", "Illinois Watch"),
    ("Rolex Datejust with Omega box", "Rolex"),  # first-mentioned brand wins
    ("Unsigned 14K gold wristwatch", ""),
])
def test_brand(title, brand):
    assert detect_brand(title) == brand


def test_major_houses():
    assert is_major_house("Bonhams")
    assert is_major_house("Christie's")
    assert is_major_house("DOYLE Auctioneers & Appraisers")
    assert not is_major_house("Lark Mountain Auction Company")
