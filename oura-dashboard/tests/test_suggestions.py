"""Suggestion rules: each must fire on its own trigger and stay quiet otherwise."""

from datetime import date, timedelta

from oura_dashboard.analysis import analyse
from oura_dashboard.metrics import DayRow
from oura_dashboard.suggestions import generate


def build(days=60, **overrides):
    """A healthy, unremarkable history; overrides tweak the final day or all days."""
    rows = []
    for index in range(days):
        row = DayRow(day=date(2026, 5, 1) + timedelta(days=index))
        row.sleep_score = 80.0
        row.readiness_score = 80.0
        row.activity_score = 80.0
        row.total_sleep_h = 8.0
        row.time_in_bed_h = 8.5
        row.deep_h = 1.5
        row.rem_h = 1.8
        row.light_h = 4.7
        row.awake_h = 0.5
        row.efficiency = 93.0
        row.latency_min = 14.0
        row.restless_periods = 12.0
        row.avg_hrv = 55.0 + (index % 5) - 2       # a little spread for the baseline
        row.avg_hr = 60.0
        row.lowest_hr = 52.0 + (index % 3) - 1
        row.avg_breath = 14.0
        row.temperature_deviation = 0.05
        row.steps = 9500.0 + (index % 7) * 100
        row.high_activity_min = 15.0
        row.medium_activity_min = 45.0
        row.sedentary_h = 8.0
        row.inactivity_alerts = 2.0
        row.non_wear_h = 0.2
        row.stress_high_min = 30.0
        row.recovery_high_min = 150.0
        row.spo2_avg = 96.5
        row.breathing_disturbance_index = 4.0
        row.resilience_level = "solid"
        rows.append(row)

    for key, value in overrides.items():
        if key.startswith("all_"):
            for row in rows:
                setattr(row, key[4:], value)
        else:
            setattr(rows[-1], key, value)
    return rows


def ids(rows, need=8.0):
    return {s.id for s in generate(analyse(rows, need))}


def one(rows, rule_id, need=8.0):
    found = [s for s in generate(analyse(rows, need)) if s.id == rule_id]
    assert found, f"expected {rule_id} to fire"
    return found[0]


# -- the quiet case ----------------------------------------------------
def test_a_healthy_history_raises_no_alarms():
    fired = ids(build())
    assert "low_readiness" not in fired
    assert "sleep_debt" not in fired
    assert "hrv_drop" not in fired
    assert "elevated_resting_hr" not in fired
    assert "temperature_deviation" not in fired


def test_there_is_always_at_least_one_suggestion():
    """An empty brief would be a bug — the mail must say something."""
    assert generate(analyse([], 8.0))


def test_suggestions_are_ordered_by_urgency():
    rows = build(readiness_score=45.0, total_sleep_h=4.0, all_total_sleep_h=5.0)
    found = generate(analyse(rows, 8.0))
    ranks = [s.rank for s in found]
    assert ranks == sorted(ranks)
    assert found[0].severity == "critical"


# -- recovery ----------------------------------------------------------
def test_low_readiness_fires_on_a_low_absolute_score():
    suggestion = one(build(readiness_score=55.0), "low_readiness")
    assert suggestion.severity == "critical"


def test_low_readiness_stays_quiet_when_the_score_beats_your_own_baseline():
    """67 is 'low' in the abstract but good for someone averaging 60."""
    rows = build(all_readiness_score=60.0)
    rows[-1].readiness_score = 67.0
    assert "low_readiness" not in ids(rows)


def test_low_readiness_fires_on_a_sharp_relative_drop_above_70():
    rows = build(all_readiness_score=90.0)
    for index, row in enumerate(rows):
        row.readiness_score = 90.0 + (index % 3)   # tight baseline
    rows[-1].readiness_score = 78.0
    assert "low_readiness" in ids(rows)


def test_hrv_drop_fires_well_below_baseline():
    suggestion = one(build(avg_hrv=25.0), "hrv_drop")
    assert "25" in suggestion.detail


def test_hrv_drop_quiet_on_a_normal_night():
    assert "hrv_drop" not in ids(build(avg_hrv=56.0))


def test_elevated_resting_hr_needs_three_bpm():
    assert "elevated_resting_hr" not in ids(build(lowest_hr=53.0))
    assert "elevated_resting_hr" in ids(build(lowest_hr=60.0))


def test_temperature_deviation_escalates_when_high():
    assert "temperature_deviation" not in ids(build(temperature_deviation=0.2))
    assert one(build(temperature_deviation=0.5), "temperature_deviation").severity == "warn"
    assert one(build(temperature_deviation=0.9), "temperature_deviation").severity == "critical"


def test_resilience_drop_is_noticed():
    rows = build()
    for row in rows[-7:]:
        row.resilience_level = "limited"
    assert "resilience_drop" in ids(rows)


# -- sleep -------------------------------------------------------------
def test_sleep_debt_fires_and_quantifies():
    rows = build(all_total_sleep_h=6.0)
    suggestion = one(rows, "sleep_debt")
    assert "14h 00m" in suggestion.title        # 2 h short over 7 nights
    assert suggestion.severity == "critical"


def test_no_sleep_debt_when_you_hit_your_need():
    assert "sleep_debt" not in ids(build(all_total_sleep_h=8.0))


def test_sleep_need_is_configurable():
    rows = build(all_total_sleep_h=7.0)
    assert "sleep_debt" in ids(rows, need=8.0)
    assert "sleep_debt" not in ids(rows, need=7.0)


def test_bedtime_inconsistency_fires_on_a_wide_spread():
    rows = build()
    for index, row in enumerate(rows):
        row.bedtime_start_h = 23.0 + (3.0 if index % 2 else 0.0)
    assert "bedtime_inconsistency" in ids(rows)


def test_bedtime_inconsistency_quiet_when_regular():
    rows = build()
    for index, row in enumerate(rows):
        row.bedtime_start_h = 23.0 + (index % 2) * 0.1
    assert "bedtime_inconsistency" not in ids(rows)


def test_late_bedtime_drift_is_reported_with_both_clock_times():
    rows = build()
    for index, row in enumerate(rows):
        row.bedtime_start_h = 22.5 if index < len(rows) - 7 else 23.5
    suggestion = one(rows, "bedtime_drift_late")
    assert "23:30" in suggestion.detail
    assert "22:30" in suggestion.detail


def test_poor_efficiency_and_long_latency_fire_independently():
    assert "poor_efficiency" in ids(build(efficiency=74.0))
    assert "poor_efficiency" not in ids(build(efficiency=92.0))
    assert "long_latency" in ids(build(latency_min=45.0))
    assert "long_latency" not in ids(build(latency_min=12.0))


def test_low_deep_or_rem_fires_against_your_own_typical_night():
    assert "low_deep_or_rem" in ids(build(deep_h=0.4, rem_h=0.5))
    assert "low_deep_or_rem" not in ids(build())


def test_frequent_naps_needs_three_in_a_week():
    rows = build()
    for row in rows[-3:]:
        row.nap_h = 0.75
    assert "frequent_naps" in ids(rows)

    rows = build()
    rows[-1].nap_h = 0.75
    assert "frequent_naps" not in ids(rows)


# -- activity ----------------------------------------------------------
def test_overtraining_needs_rising_load_and_falling_readiness():
    rows = build()
    for row in rows[-7:]:
        row.high_activity_min = 60.0
        row.readiness_score = 68.0
    assert "overtraining" in ids(rows)


def test_rising_load_alone_is_not_overtraining():
    rows = build()
    for row in rows[-7:]:
        row.high_activity_min = 60.0
    assert "overtraining" not in ids(rows)


def test_sedentary_fires_on_a_low_step_week():
    rows = build()
    for row in rows[-7:]:
        row.steps = 3000.0
    assert "sedentary" in ids(rows)


def test_ready_to_train_celebrates_a_strong_morning():
    suggestion = one(build(readiness_score=90.0), "ready_to_train")
    assert suggestion.severity == "win"


def test_ready_to_train_withheld_when_hrv_is_suppressed():
    rows = build(readiness_score=90.0, avg_hrv=30.0)
    assert "ready_to_train" not in ids(rows)


# -- stress, breathing, long horizon -----------------------------------
def test_high_stress_fires_on_a_loaded_week():
    rows = build()
    for row in rows[-7:]:
        row.stress_high_min = 150.0
    assert one(rows, "high_stress").severity == "warn"


def test_breathing_disturbance_fires_on_low_spo2():
    assert "breathing_disturbance" in ids(build(spo2_avg=92.0))
    assert "breathing_disturbance" not in ids(build(spo2_avg=97.0))


def test_data_gap_is_flagged_when_nights_are_missing():
    rows = build()
    for row in rows[-3:]:
        row.total_sleep_h = None
    assert "data_gap" in ids(rows)


# -- positives ---------------------------------------------------------
def test_streak_win_appears_for_a_long_good_run():
    assert "streak_win" in ids(build())


def test_improving_metric_notices_real_gains():
    rows = build()
    for row in rows[-7:]:
        row.avg_hrv = 75.0
    suggestion = one(rows, "improving_metric")
    assert "HRV" in suggestion.detail or "hrv" in suggestion.detail.lower()


def test_every_suggestion_carries_evidence_and_an_action():
    rows = build(readiness_score=50.0, efficiency=70.0, latency_min=50.0)
    for suggestion in generate(analyse(rows, 8.0)):
        assert suggestion.title
        assert suggestion.detail, f"{suggestion.id} has no evidence"
        assert suggestion.action, f"{suggestion.id} has no action"
        assert suggestion.severity in {"critical", "warn", "info", "win"}


def test_a_broken_rule_cannot_sink_the_whole_brief(monkeypatch):
    from oura_dashboard import suggestions as module

    def exploding(analysis):
        raise ValueError("boom")

    monkeypatch.setattr(module, "RULES", [exploding, module.streak_win])
    found = module.generate(analyse(build(), 8.0))
    assert found  # the good rule still made it through


def test_acronyms_survive_sentence_casing():
    """str.capitalize() would turn 'SpO₂' into 'spo₂'."""
    suggestion = one(build(spo2_avg=92.0), "breathing_disturbance")
    assert "SpO₂" in suggestion.detail
    assert suggestion.detail[0].isupper()


def test_rem_stays_upper_case_in_stage_findings():
    suggestion = one(build(rem_h=0.4), "low_deep_or_rem")
    assert "REM" in suggestion.detail
