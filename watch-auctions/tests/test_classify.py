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


@pytest.mark.parametrize("title,expected", [
    ("Milor Italian Sterling Silver Omega Chain Necklace", False),
    ("American Flyer S gauge 910 Gilbert Chemicals Tank Car", False),
    ("Lot Of Five (5) Watch Related Books", False),
    ("Victorian 14K Gold Pendant Watch", True),
    ("Rolex 1601 Datejust", True),
    ("Cartier Tank Francaise Ladies 18K Watch", True),
])
def test_edge_cases(title, expected):
    assert is_watch(title) is expected


@pytest.mark.parametrize("title,expected", [
    ("Italian Glass Ceiling lamp 'Omega' by Vico Magistretti", False),
    ("Assortment of Zenith Holland and Hesson Tobacco Pipes and Humidor Stands", False),
    ("Rolex 16610 Stainless Steel", True),
    ("Omega Constellation 18K Gold", True),
    ("Hublot Big Bang Meca-10 Black Magic, Box & Pap", True),
])
def test_brand_needs_watch_context(title, expected):
    assert is_watch(title) is expected
