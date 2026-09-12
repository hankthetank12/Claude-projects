"""Flatten raw Oura documents into one row per day.

Oura spreads a single night across several endpoints: ``daily_sleep`` holds the
score, ``sleep`` holds the physiology (HRV, heart rate, stages), and readiness,
activity, stress and SpO2 each add their own. This module joins them on ``day``
so everything downstream reads one flat record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

HOUR = 3600.0
MINUTE = 60.0


def _to_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def clock_hours(value: Any) -> float | None:
    """A timestamp as hours past midnight, local to the reading.

    Bedtimes are compared against each other, so late-night times are unwrapped
    past 24 (00:30 becomes 24.5) to keep "later" numerically larger.
    """
    moment = _parse_dt(value)
    if moment is None:
        return None
    hours = moment.hour + moment.minute / 60.0 + moment.second / 3600.0
    if hours < 12.0:  # after midnight: continue the previous evening
        hours += 24.0
    return hours


def format_clock(hours: float | None) -> str:
    if hours is None:
        return "--"
    hours = hours % 24.0
    total_minutes = int(round(hours * 60.0))
    return f"{(total_minutes // 60) % 24:02d}:{total_minutes % 60:02d}"


def _nz(value: Any) -> float | None:
    """Coerce to float, treating None and non-numerics as missing."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class DayRow:
    """Every tracked stat for one calendar day."""

    day: date

    # scores
    sleep_score: float | None = None
    readiness_score: float | None = None
    activity_score: float | None = None

    # sleep duration and structure (hours unless noted)
    total_sleep_h: float | None = None
    time_in_bed_h: float | None = None
    deep_h: float | None = None
    rem_h: float | None = None
    light_h: float | None = None
    awake_h: float | None = None
    efficiency: float | None = None
    latency_min: float | None = None
    restless_periods: float | None = None
    bedtime_start_h: float | None = None
    bedtime_end_h: float | None = None
    nap_h: float = 0.0

    # physiology
    avg_hrv: float | None = None
    avg_hr: float | None = None
    lowest_hr: float | None = None
    avg_breath: float | None = None
    temperature_deviation: float | None = None

    # activity
    steps: float | None = None
    active_calories: float | None = None
    total_calories: float | None = None
    target_calories: float | None = None
    high_activity_min: float | None = None
    medium_activity_min: float | None = None
    low_activity_min: float | None = None
    sedentary_h: float | None = None
    inactivity_alerts: float | None = None
    non_wear_h: float | None = None
    walking_equivalent_km: float | None = None

    # stress, breathing, resilience
    stress_high_min: float | None = None
    recovery_high_min: float | None = None
    stress_summary: str | None = None
    spo2_avg: float | None = None
    breathing_disturbance_index: float | None = None
    resilience_level: str | None = None

    # long-horizon
    vascular_age: float | None = None
    vo2_max: float | None = None

    # contributor sub-scores, kept whole so suggestions can name the culprit
    readiness_contributors: dict[str, float] = field(default_factory=dict)
    sleep_contributors: dict[str, float] = field(default_factory=dict)
    activity_contributors: dict[str, float] = field(default_factory=dict)

    workouts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def workout_min(self) -> float:
        total = 0.0
        for workout in self.workouts:
            start = _parse_dt(workout.get("start_datetime"))
            end = _parse_dt(workout.get("end_datetime"))
            if start and end and end > start:
                total += (end - start).total_seconds() / MINUTE
        return total

    def get(self, name: str) -> Any:
        return getattr(self, name, None)


# Stats that trend analysis can run over, in the order the dashboard shows them.
NUMERIC_FIELDS: tuple[str, ...] = (
    "sleep_score",
    "readiness_score",
    "activity_score",
    "total_sleep_h",
    "time_in_bed_h",
    "deep_h",
    "rem_h",
    "light_h",
    "awake_h",
    "efficiency",
    "latency_min",
    "restless_periods",
    "bedtime_start_h",
    "bedtime_end_h",
    "nap_h",
    "avg_hrv",
    "avg_hr",
    "lowest_hr",
    "avg_breath",
    "temperature_deviation",
    "steps",
    "active_calories",
    "total_calories",
    "high_activity_min",
    "medium_activity_min",
    "low_activity_min",
    "sedentary_h",
    "inactivity_alerts",
    "walking_equivalent_km",
    "stress_high_min",
    "recovery_high_min",
    "spo2_avg",
    "breathing_disturbance_index",
    "vascular_age",
    "vo2_max",
)


def _contributors(doc: dict[str, Any]) -> dict[str, float]:
    raw = doc.get("contributors") or {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in ((k, _nz(v)) for k, v in raw.items()) if v is not None}


def build_rows(history: Any) -> list[DayRow]:
    """Join every endpoint in ``history`` into a sorted list of daily rows."""
    rows: dict[date, DayRow] = {}

    def row_for(value: Any) -> DayRow | None:
        day = _to_date(value)
        if day is None:
            return None
        return rows.setdefault(day, DayRow(day=day))

    for doc in history.documents("daily_sleep"):
        row = row_for(doc.get("day"))
        if row:
            row.sleep_score = _nz(doc.get("score"))
            row.sleep_contributors = _contributors(doc)

    for doc in history.documents("daily_readiness"):
        row = row_for(doc.get("day"))
        if row:
            row.readiness_score = _nz(doc.get("score"))
            row.temperature_deviation = _nz(doc.get("temperature_deviation"))
            row.readiness_contributors = _contributors(doc)

    for doc in history.documents("daily_activity"):
        row = row_for(doc.get("day"))
        if not row:
            continue
        row.activity_score = _nz(doc.get("score"))
        row.activity_contributors = _contributors(doc)
        row.steps = _nz(doc.get("steps"))
        row.active_calories = _nz(doc.get("active_calories"))
        row.total_calories = _nz(doc.get("total_calories"))
        row.target_calories = _nz(doc.get("target_calories"))
        for src, dest in (
            ("high_activity_time", "high_activity_min"),
            ("medium_activity_time", "medium_activity_min"),
            ("low_activity_time", "low_activity_min"),
        ):
            seconds = _nz(doc.get(src))
            if seconds is not None:
                setattr(row, dest, seconds / MINUTE)
        for src, dest in (("sedentary_time", "sedentary_h"), ("non_wear_time", "non_wear_h")):
            seconds = _nz(doc.get(src))
            if seconds is not None:
                setattr(row, dest, seconds / HOUR)
        row.inactivity_alerts = _nz(doc.get("inactivity_alerts"))
        meters = _nz(doc.get("equivalent_walking_distance"))
        if meters is not None:
            row.walking_equivalent_km = meters / 1000.0

    # The `sleep` endpoint holds one document per sleep period: the long sleep
    # carries the night's physiology, naps are accumulated separately.
    nights: dict[date, dict[str, Any]] = {}
    for doc in history.documents("sleep"):
        day = _to_date(doc.get("day"))
        if day is None:
            continue
        duration = _nz(doc.get("total_sleep_duration")) or 0.0
        is_nap = str(doc.get("type", "")).endswith("nap")
        if is_nap:
            row = row_for(day)
            if row:
                row.nap_h += duration / HOUR
            continue
        best = nights.get(day)
        if best is None or duration > (_nz(best.get("total_sleep_duration")) or 0.0):
            nights[day] = doc

    for day, doc in nights.items():
        row = row_for(day)
        if not row:
            continue
        for src, dest in (
            ("total_sleep_duration", "total_sleep_h"),
            ("time_in_bed", "time_in_bed_h"),
            ("deep_sleep_duration", "deep_h"),
            ("rem_sleep_duration", "rem_h"),
            ("light_sleep_duration", "light_h"),
            ("awake_time", "awake_h"),
        ):
            seconds = _nz(doc.get(src))
            if seconds is not None:
                setattr(row, dest, seconds / HOUR)
        row.efficiency = _nz(doc.get("efficiency"))
        latency = _nz(doc.get("latency"))
        row.latency_min = latency / MINUTE if latency is not None else None
        row.restless_periods = _nz(doc.get("restless_periods"))
        row.avg_hrv = _nz(doc.get("average_hrv"))
        row.avg_hr = _nz(doc.get("average_heart_rate"))
        row.lowest_hr = _nz(doc.get("lowest_heart_rate"))
        row.avg_breath = _nz(doc.get("average_breath"))
        row.bedtime_start_h = clock_hours(doc.get("bedtime_start"))
        row.bedtime_end_h = clock_hours(doc.get("bedtime_end"))
        if row.temperature_deviation is None:
            readiness = doc.get("readiness") or {}
            if isinstance(readiness, dict):
                row.temperature_deviation = _nz(readiness.get("temperature_deviation"))

    for doc in history.documents("daily_stress"):
        row = row_for(doc.get("day"))
        if not row:
            continue
        stress = _nz(doc.get("stress_high"))
        recovery = _nz(doc.get("recovery_high"))
        # Oura reports these in seconds; small values are already minutes.
        row.stress_high_min = stress / MINUTE if stress and stress > 240 else stress
        row.recovery_high_min = recovery / MINUTE if recovery and recovery > 240 else recovery
        row.stress_summary = doc.get("day_summary")

    for doc in history.documents("daily_spo2"):
        row = row_for(doc.get("day"))
        if not row:
            continue
        pct = doc.get("spo2_percentage")
        if isinstance(pct, dict):
            row.spo2_avg = _nz(pct.get("average"))
        row.breathing_disturbance_index = _nz(doc.get("breathing_disturbance_index"))

    for doc in history.documents("daily_resilience"):
        row = row_for(doc.get("day"))
        if row:
            row.resilience_level = doc.get("level")

    for doc in history.documents("daily_cardiovascular_age"):
        row = row_for(doc.get("day"))
        if row:
            row.vascular_age = _nz(doc.get("vascular_age"))

    for doc in history.documents("vO2_max"):
        row = row_for(doc.get("day"))
        if row:
            row.vo2_max = _nz(doc.get("vo2_max"))

    for doc in history.documents("workout"):
        row = row_for(doc.get("day"))
        if row:
            row.workouts.append(doc)

    return [rows[day] for day in sorted(rows)]
