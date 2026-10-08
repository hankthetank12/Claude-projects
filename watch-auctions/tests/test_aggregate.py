from watch_auctions import aggregate, sample
from watch_auctions.models import Lot

NOW = 1_800_000_000


def lot(**kw):
    base = dict(source="invaluable", source_id="1", title="Rolex Datejust 16234", url="u",
                house="Small Town Auctions", lot_number="12", starts_at=NOW + 3600, ends_at=NOW + 7200)
    return Lot(**{**base, **kw})


def test_cross_listed_lot_is_merged_with_both_links():
    a = lot()
    b = lot(source="liveauctioneers", source_id="9", house="Small Town Auctions, LLC", url="u2")
    out = aggregate.build([a, b], NOW, 30)
    assert len(out) == 1
    assert out[0].also_on == [{"source": "liveauctioneers", "url": "u2"}]


def test_filters_majors_past_and_far_future():
    lots = [lot(source_id="maj", house="Bonhams", lot_number="1"),
            lot(source_id="past", lot_number="2", starts_at=NOW - 90000, ends_at=NOW - 86400),
            lot(source_id="far", lot_number="3", starts_at=NOW + 40 * 86400, ends_at=NOW + 40 * 86400),
            lot(source_id="ok", lot_number="4")]
    assert [l.source_id for l in aggregate.build(lots, NOW, 30)] == ["ok"]
    assert len(aggregate.build(lots, NOW, 30, include_majors=True)) == 2


def test_live_sale_in_progress_is_kept():
    # Live-sale end times are estimates; a sale running a bit long shouldn't vanish.
    l = lot(sale_type="live", starts_at=NOW - 3600, ends_at=NOW - 1800)
    assert aggregate.build([l], NOW, 30)


def test_ranked_by_quality_then_close_time_and_brand_filled():
    lots = [lot(source_id="soon", lot_number="1", title="Omega Seamaster Automatic", ends_at=NOW + 5000),
            lot(source_id="best", lot_number="2", title="Rolex Datejust 16234 18K", ends_at=NOW + 9000),
            lot(source_id="late", lot_number="3", title="Omega Seamaster Automatic", house="Other", ends_at=NOW + 9000)]
    out = aggregate.build(lots, NOW, 30)
    # "soon" shares a house with "best", so house fatigue drops it below "late".
    assert [l.source_id for l in out] == ["best", "late", "soon"]
    assert out[1].brand == "Omega" and out[0].score > out[1].score


def test_sample_data_builds():
    out = aggregate.build(sample.lots(NOW), NOW, 30)
    assert len(out) == 7
    assert not any("Bands" in l.title or l.house == "Bonhams" for l in out)
