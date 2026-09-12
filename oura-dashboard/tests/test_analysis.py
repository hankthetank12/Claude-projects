"""Baselines, trends, sleep debt and correlations."""

import math
from datetime import date, timedelta

from oura_dashboard.analysis import (
    analyse, build_trend, compute_sleep_debt, compute_streak, mean, median, pearson, stdev,
)
from oura_dashboard.metrics import DayRow


def rows_from(values, metric="avg_hrv", start=date(2026, 5, 1)):
    rows = []
    for index, value in enumerate(values):
        row = DayRow(day=start + timedelta(days=index))
        setattr(row, metric, value)
        rows.append(row)
    return rows


def test_mean_stdev_median_skip_missing_values():
    assert mean([1, None, 3]) == 2
    assert median([5, None, 1, 3]) == 3
    assert stdev([2, 2, 2]) == 0
    assert stdev([1]) is None
    assert mean([None]) is None


def test_trend_compares_recent_against_the_earlier_baseline():
    # 28 baseline days at 50, then 7 recent days at 60.
    rows = rows_from([50.0] * 28 + [60.0] * 7)
    trend = build_trend(rows, "avg_hrv")
    assert trend.today == 60.0
    assert trend.recent_avg == 60.0
    assert trend.baseline_avg == 50.0
    assert trend.delta == 10.0
    assert trend.delta_pct == 20.0
    assert trend.direction() == "up"


def test_z_score_measures_distance_in_baseline_sds():
    rows = rows_from([10.0, 20.0] * 14 + [0.0] * 6 + [-10.0])
    trend = build_trend(rows, "avg_hrv")
    assert trend.baseline_avg == 15.0
    assert trend.z is not None and trend.z < -4


def test_z_is_none_when_the_baseline_never_varies():
    """A flat baseline has no spread, so a z-score would be meaningless."""
    rows = rows_from([50.0] * 28 + [60.0] * 7)
    assert build_trend(rows, "avg_hrv").z is None


def test_trend_is_unreliable_with_too_little_history():
    rows = rows_from([50.0] * 4)
    assert build_trend(rows, "avg_hrv").reliable is False


def test_short_history_falls_back_to_all_prior_days():
    """In the first weeks there is no separate baseline period to compare to."""
    rows = rows_from([40.0, 40.0, 40.0, 40.0, 40.0, 70.0])
    trend = build_trend(rows, "avg_hrv")
    assert trend.baseline_avg == 40.0
    assert trend.today == 70.0


def test_missing_metric_gives_an_empty_trend():
    trend = build_trend(rows_from([None] * 30), "avg_hrv")
    assert trend.today is None
    assert trend.delta is None
    assert trend.z is None
    assert trend.reliable is False


def test_sleep_debt_is_positive_when_short_and_negative_when_over():
    short = rows_from([7.0] * 7, metric="total_sleep_h")
    assert compute_sleep_debt(short, 8.0) == 7.0

    plenty = rows_from([8.5] * 7, metric="total_sleep_h")
    assert compute_sleep_debt(plenty, 8.0) == -3.5


def test_sleep_debt_counts_naps_towards_the_total():
    rows = rows_from([7.0] * 7, metric="total_sleep_h")
    for row in rows:
        row.nap_h = 0.5
    assert compute_sleep_debt(rows, 8.0) == 3.5


def test_sleep_debt_ignores_nights_with_no_data():
    rows = rows_from([None, 7.0, None], metric="total_sleep_h")
    assert compute_sleep_debt(rows, 8.0) == 1.0


def test_streak_counts_back_from_today_and_stops_at_a_break():
    rows = rows_from([90.0, 40.0, 80.0, 80.0, 80.0], metric="readiness_score")
    assert compute_streak(rows, "readiness_score", 70, above=True) == 3


def test_streak_stops_at_a_gap_in_the_data():
    rows = rows_from([80.0, None, 80.0], metric="readiness_score")
    assert compute_streak(rows, "readiness_score", 70, above=True) == 1


def test_pearson_finds_a_perfect_relationship():
    result = pearson([(x, 2 * x) for x in range(10)])
    assert result is not None
    assert math.isclose(result[0], 1.0, abs_tol=1e-9)
    assert result[1] == 10


def test_pearson_needs_enough_pairs():
    assert pearson([(1, 1), (2, 2)]) is None


def test_pearson_returns_none_when_a_side_never_varies():
    assert pearson([(1, 5)] * 10) is None


def test_analyse_produces_the_whole_picture():
    days = 60
    rows = []
    for index in range(days):
        row = DayRow(day=date(2026, 5, 1) + timedelta(days=index))
        row.sleep_score = 70.0
        row.readiness_score = 75.0
        row.total_sleep_h = 7.5
        row.avg_hrv = 55.0
        row.steps = 9000.0
        row.bedtime_start_h = 23.0 + (index % 3) * 0.25
        rows.append(row)

    result = analyse(rows, sleep_need_h=8.0)
    assert result.days_tracked == days
    assert result.today is rows[-1]
    assert result.sleep_debt_h == 3.5                    # 0.5 h short over 7 nights
    assert result.bedtime_consistency_min is not None
    assert result.streaks["sleep_ge_7h"] == days
    assert set(result.weekday_sleep) == set(range(7))


def test_analyse_handles_an_empty_history():
    result = analyse([], sleep_need_h=8.0)
    assert result.days_tracked == 0
    assert result.today is None
    assert result.sleep_debt_h is None
    assert result.trend("avg_hrv").today is None
