"""Normalization: unit conversions, the multi-endpoint join, and naps."""

from datetime import date

from oura_dashboard.metrics import build_rows, clock_hours, format_clock
from oura_dashboard.store import History


def history_with(**endpoints):
    history = History()
    history.merge(endpoints)
    return history


def test_seconds_become_hours_and_minutes():
    history = history_with(sleep=[{
        "id": "s1", "day": "2026-09-10", "type": "long_sleep",
        "total_sleep_duration": 27000,   # 7.5 h
        "time_in_bed": 28800,            # 8 h
        "deep_sleep_duration": 5400,     # 1.5 h
        "rem_sleep_duration": 7200,      # 2 h
        "light_sleep_duration": 14400,   # 4 h
        "awake_time": 1800,              # 0.5 h
        "latency": 900,                  # 15 min
        "efficiency": 94,
    }])
    row = build_rows(history)[0]
    assert row.total_sleep_h == 7.5
    assert row.time_in_bed_h == 8.0
    assert row.deep_h == 1.5
    assert row.rem_h == 2.0
    assert row.awake_h == 0.5
    assert row.latency_min == 15.0
    assert row.efficiency == 94


def test_activity_seconds_become_minutes_and_hours():
    history = history_with(daily_activity=[{
        "id": "a1", "day": "2026-09-10", "score": 80,
        "high_activity_time": 1800,      # 30 min
        "medium_activity_time": 3600,    # 60 min
        "sedentary_time": 36000,         # 10 h
        "equivalent_walking_distance": 7200,  # 7.2 km
        "steps": 11000,
    }])
    row = build_rows(history)[0]
    assert row.high_activity_min == 30.0
    assert row.medium_activity_min == 60.0
    assert row.sedentary_h == 10.0
    assert row.walking_equivalent_km == 7.2
    assert row.steps == 11000


def test_endpoints_join_on_the_same_day():
    history = history_with(
        daily_sleep=[{"id": "ds", "day": "2026-09-10", "score": 72}],
        daily_readiness=[{"id": "dr", "day": "2026-09-10", "score": 65,
                          "temperature_deviation": 0.3}],
        daily_activity=[{"id": "da", "day": "2026-09-10", "score": 88, "steps": 9000}],
        daily_spo2=[{"id": "sp", "day": "2026-09-10",
                     "spo2_percentage": {"average": 96.5},
                     "breathing_disturbance_index": 4}],
        daily_resilience=[{"id": "re", "day": "2026-09-10", "level": "solid"}],
    )
    rows = build_rows(history)
    assert len(rows) == 1
    row = rows[0]
    assert (row.sleep_score, row.readiness_score, row.activity_score) == (72, 65, 88)
    assert row.spo2_avg == 96.5
    assert row.breathing_disturbance_index == 4
    assert row.resilience_level == "solid"
    assert row.temperature_deviation == 0.3


def test_naps_are_separated_from_the_night():
    history = history_with(sleep=[
        {"id": "n", "day": "2026-09-10", "type": "long_sleep",
         "total_sleep_duration": 25200, "average_hrv": 60},
        {"id": "p", "day": "2026-09-10", "type": "late_nap",
         "total_sleep_duration": 1800},
    ])
    row = build_rows(history)[0]
    assert row.total_sleep_h == 7.0     # the nap is not folded into the night
    assert row.nap_h == 0.5
    assert row.avg_hrv == 60


def test_the_longest_period_wins_when_two_nights_share_a_day():
    history = history_with(sleep=[
        {"id": "short", "day": "2026-09-10", "type": "long_sleep",
         "total_sleep_duration": 3600, "average_hrv": 10},
        {"id": "main", "day": "2026-09-10", "type": "long_sleep",
         "total_sleep_duration": 25200, "average_hrv": 55},
    ])
    row = build_rows(history)[0]
    assert row.avg_hrv == 55


def test_missing_values_stay_none_rather_than_zero():
    history = history_with(daily_sleep=[{"id": "x", "day": "2026-09-10", "score": 70}])
    row = build_rows(history)[0]
    assert row.sleep_score == 70
    assert row.total_sleep_h is None
    assert row.avg_hrv is None
    assert row.steps is None


def test_rows_are_sorted_and_cover_every_day_seen():
    history = history_with(daily_sleep=[
        {"id": "b", "day": "2026-09-11", "score": 1},
        {"id": "a", "day": "2026-09-09", "score": 2},
    ])
    assert [r.day for r in build_rows(history)] == [date(2026, 9, 9), date(2026, 9, 11)]


def test_readiness_falls_back_to_the_nested_sleep_document():
    history = history_with(sleep=[{
        "id": "s", "day": "2026-09-10", "type": "long_sleep",
        "total_sleep_duration": 25200,
        "readiness": {"temperature_deviation": -0.2},
    }])
    assert build_rows(history)[0].temperature_deviation == -0.2


def test_bedtimes_after_midnight_unwrap_past_24():
    """00:30 must compare as *later* than 23:30, not earlier."""
    late = clock_hours("2026-09-10T00:30:00+00:00")
    early = clock_hours("2026-09-10T23:30:00+00:00")
    assert late == 24.5
    assert late > early


def test_format_clock_wraps_back_into_a_24_hour_dial():
    assert format_clock(24.5) == "00:30"
    assert format_clock(23.25) == "23:15"
    assert format_clock(None) == "--"


def test_workout_minutes_come_from_the_timestamps():
    history = history_with(workout=[{
        "id": "w", "day": "2026-09-10",
        "start_datetime": "2026-09-10T17:00:00+00:00",
        "end_datetime": "2026-09-10T18:30:00+00:00",
    }])
    assert build_rows(history)[0].workout_min == 90.0


def test_non_numeric_values_are_treated_as_missing():
    history = history_with(daily_activity=[
        {"id": "a", "day": "2026-09-10", "steps": None, "score": "bogus"}
    ])
    row = build_rows(history)[0]
    assert row.steps is None
    assert row.activity_score is None


def test_stress_seconds_are_converted_but_minutes_are_left_alone():
    """The stress endpoint reports seconds; small values are already minutes."""
    seconds = history_with(daily_stress=[
        {"id": "s", "day": "2026-09-10", "stress_high": 3600, "recovery_high": 7200}
    ])
    row = build_rows(seconds)[0]
    assert row.stress_high_min == 60.0
    assert row.recovery_high_min == 120.0

    minutes = history_with(daily_stress=[
        {"id": "s", "day": "2026-09-10", "stress_high": 90, "recovery_high": 120}
    ])
    row = build_rows(minutes)[0]
    assert row.stress_high_min == 90
