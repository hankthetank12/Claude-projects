import pytest

from watch_auctions import aggregate, quality
from watch_auctions.classify import detect_brand
from watch_auctions.models import Lot


def verdict(title, **kw):
    lot = Lot(source="x", source_id="1", title=title, url="u", house=kw.pop("house", "h"), **kw)
    lot.brand = detect_brand(title)
    return quality.score(lot)


@pytest.mark.parametrize("title", [
    "Fossil Men's Chronograph Watch",
    "Michael Kors MK5076 Rose Gold Tone",
    "Apple Watch Series 7 45mm",
    "Lot of 15 Metallic Watches",
    "Omega Longines Benrus Wittnauer Elgin Vintage Watch Lot 12pc Gold Fill",
    "2020 Panini Chronicles Omega Football: JK Dobbins",
    "Rolex Datejust for parts or repair",
    "Replica Rolex Submariner",
    "Mickey Mouse Kids Watch",
    "Vintage Gruen Swiss Gold Tone Black Dial Ladies Watch",  # plated, nothing collectible
])
def test_garbage_is_rejected(title):
    assert verdict(title).rejected


@pytest.mark.parametrize("title", [
    "Rolex Submariner 16610 Stainless Steel",
    "18k Gold Hunter Case Emile Jacot Key Wound Swiss Pocket Watch",
    "Vintage Omega Seamaster Automatic Solid 14k Gold Wristwatch",
    "Two Rolex Datejust Watches",  # a multi-lot, but the brand carries it
    "ELGIN 1925 B.W. Raymond Railroad Pocket Watch 21 Jewels 14K Gold",
])
def test_good_watches_are_kept(title):
    assert not verdict(title).rejected


def test_score_order_and_reasons():
    ap = verdict("Audemars Piguet 18K Gold Skeletonized Wristwatch, Circa 1970", estimate_low=10000, estimate_high=15000)
    seiko = verdict("Vintage Seiko 5 Automatic 7009-3040 Stainless Steel")
    assert ap.score > seiko.score > 0
    assert "Audemars Piguet" in ap.reasons and "solid 18K" in ap.reasons and "$15,000 estimate" in ap.reasons


def test_plated_gold_is_not_solid_gold():
    v = verdict("Cartier 18K Gold Electroplated Wristwatch")
    assert "solid 18K" not in v.reasons


def test_placeholder_estimates_are_ignored():
    real = verdict("TAG Heuer Aquaracer Stainless Steel Wristwatch", estimate_low=300, estimate_high=500)
    fake = verdict("TAG Heuer Aquaracer Stainless Steel Wristwatch", estimate_low=10, estimate_high=100000)
    assert not any("estimate" in r for r in fake.reasons)
    assert real.score >= fake.score


def test_year_is_not_a_reference_number():
    assert "reference no." not in verdict("1965 Omega Constellation 14K Gold Automatic").reasons
    assert "reference no." in verdict("Omega Constellation 168.005 Automatic").reasons


def test_one_house_cannot_take_over_the_top():
    lots = [Lot(source="x", source_id=str(i), title="t", url="u", house="Dealer", score=80) for i in range(10)]
    lots.append(Lot(source="x", source_id="z", title="t", url="u", house="Small House", score=70))
    ranked = aggregate.rank(lots)
    assert [l.house for l in ranked].index("Small House") < 8
    assert ranked[0].house == "Dealer"
