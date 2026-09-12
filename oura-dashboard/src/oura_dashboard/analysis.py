"""Baselines, trends and correlations over the daily rows.

Every suggestion needs to answer "compared to what?", so the unit of analysis
here is a :class:`Trend`: today's value, the recent window, the longer personal
baseline, and how far today sits from it in standard deviations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Sequence

from .metrics import NUMERIC_FIELDS, DayRow

RECENT_WINDOW = 7
BASELINE_WINDOW = 28


def mean(values: Iterable[float]) -> float | None:
    items = [v for v in values if v is not None]
    return sum(items) / len(items) if items else None


def stdev(values: Iterable[float]) -> float | None:
    items = [v for v in values if v is not None]
    if len(items) < 2:
        return None
    avg = sum(items) / len(items)
    variance = sum((v - avg) ** 2 for v in items) / (len(items) - 1)
    return math.sqrt(variance)


def median(values: Iterable[float]) -> float | None:
    items = sorted(v for v in values if v is not None)
    if not items:
        return None
    mid = len(items) // 2
    if len(items) % 2:
        return items[mid]
    return (items[mid - 1] + items[mid]) / 2.0


def series(rows: Sequence[DayRow], metric: str) -> list[float]:
    """Present values of a metric, oldest first."""
    return [v for v in (row.get(metric) for row in rows) if v is not None]


@dataclass
class Trend:
    """How one metric is doing today relative to the user's own history."""

    metric: str
    today: float | None
    recent_avg: float | None      # mean of the last RECENT_WINDOW days
    baseline_avg: float | None    # mean of the BASELINE_WINDOW before those
    baseline_sd: float | None
    n_baseline: int

    @property
    def delta(self) -> float | None:
        """Recent average minus baseline average."""
        if self.recent_avg is None or self.baseline_avg is None:
            return None
        return self.recent_avg - self.baseline_avg

    @property
    def delta_pct(self) -> float | None:
        if self.delta is None or not self.baseline_avg:
            return None
        return 100.0 * self.delta / abs(self.baseline_avg)

    @property
    def z(self) -> float | None:
        """Today's distance from baseline, in baseline standard deviations."""
        if self.today is None or self.baseline_avg is None:
            return None
        if not self.baseline_sd or self.baseline_sd < 1e-9:
            return None
        return (self.today - self.baseline_avg) / self.baseline_sd

    @property
    def reliable(self) -> bool:
        """Enough baseline days to say anything responsible about the metric."""
        return self.n_baseline >= 10

    def direction(self, tolerance: float = 0.02) -> str:
        pct = self.delta_pct
        if pct is None:
            return "flat"
        if pct > tolerance * 100:
            return "up"
        if pct < -tolerance * 100:
            return "down"
        return "flat"


def build_trend(
    rows: Sequence[DayRow],
    metric: str,
    *,
    recent: int = RECENT_WINDOW,
    baseline: int = BASELINE_WINDOW,
) -> Trend:
    values = [row.get(metric) for row in rows]
    present_today = values[-1] if values else None

    recent_slice = [v for v in values[-recent:] if v is not None]
    baseline_slice = [v for v in values[-(recent + baseline) : -recent] if v is not None]
    # Early on there is no separate baseline period; fall back to all prior days
    # so trends still work in the first weeks of tracking.
    if len(baseline_slice) < 5:
        baseline_slice = [v for v in values[:-1] if v is not None]

    return Trend(
        metric=metric,
        today=present_today,
        recent_avg=mean(recent_slice),
        baseline_avg=mean(baseline_slice),
        baseline_sd=stdev(baseline_slice),
        n_baseline=len(baseline_slice),
    )


@dataclass
class Analysis:
    """Everything the dashboard and the brief need to say something useful."""

    rows: list[DayRow]
    trends: dict[str, Trend]
    today: DayRow | None
    sleep_debt_h: float | None
    bedtime_consistency_min: float | None
    weekday_sleep: dict[int, float]
    correlations: dict[str, tuple[float, int]]
    streaks: dict[str, int]
    sleep_need_h: float

    def trend(self, metric: str) -> Trend:
        return self.trends.get(
            metric, Trend(metric, None, None, None, None, 0)
        )

    @property
    def days_tracked(self) -> int:
        return len(self.rows)


def pearson(pairs: Sequence[tuple[float, float]]) -> tuple[float, int] | None:
    """Correlation coefficient and sample size, or None if underpowered."""
    clean = [(x, y) for x, y in pairs if x is not None and y is not None]
    if len(clean) < 8:
        return None
    xs = [p[0] for p in clean]
    ys = [p[1] for p in clean]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in clean)
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx < 1e-9 or dy < 1e-9:
        return None
    return num / (dx * dy), len(clean)


def _lagged_pairs(
    rows: Sequence[DayRow], cause: str, effect: str
) -> list[tuple[float, float]]:
    """Pair each day's ``cause`` with the *next* day's ``effect``."""
    by_day = {row.day: row for row in rows}
    pairs: list[tuple[float, float]] = []
    for row in rows:
        nxt = by_day.get(row.day + timedelta(days=1))
        if nxt is None:
            continue
        x, y = row.get(cause), nxt.get(effect)
        if x is not None and y is not None:
            pairs.append((x, y))
    return pairs


def _same_day_pairs(
    rows: Sequence[DayRow], a: str, b: str
) -> list[tuple[float, float]]:
    return [
        (row.get(a), row.get(b))
        for row in rows
        if row.get(a) is not None and row.get(b) is not None
    ]


def compute_sleep_debt(
    rows: Sequence[DayRow], need_h: float, window: int = RECENT_WINDOW
) -> float | None:
    """Hours of sleep owed over the recent window (positive means short)."""
    recent = [r for r in rows[-window:] if r.total_sleep_h is not None]
    if not recent:
        return None
    slept = sum((r.total_sleep_h or 0.0) + (r.nap_h or 0.0) for r in recent)
    return need_h * len(recent) - slept


def compute_streak(rows: Sequence[DayRow], metric: str, threshold: float, above: bool) -> int:
    """Consecutive days, counting back from today, meeting a threshold."""
    streak = 0
    for row in reversed(rows):
        value = row.get(metric)
        if value is None:
            break
        if (value >= threshold) if above else (value <= threshold):
            streak += 1
        else:
            break
    return streak


def analyse(rows: Sequence[DayRow], sleep_need_h: float = 8.0) -> Analysis:
    rows = list(rows)
    trends = {metric: build_trend(rows, metric) for metric in NUMERIC_FIELDS}

    bedtimes = series(rows[-BASELINE_WINDOW:], "bedtime_start_h")
    consistency = stdev(bedtimes)

    weekday_sleep: dict[int, float] = {}
    for weekday in range(7):
        scores = [
            r.sleep_score
            for r in rows[-(BASELINE_WINDOW * 2) :]
            if r.day.weekday() == weekday and r.sleep_score is not None
        ]
        if scores:
            weekday_sleep[weekday] = sum(scores) / len(scores)

    candidates = {
        "steps_to_next_readiness": _lagged_pairs(rows, "steps", "readiness_score"),
        "bedtime_to_sleep_score": _same_day_pairs(rows, "bedtime_start_h", "sleep_score"),
        "sleep_to_next_activity": _lagged_pairs(rows, "total_sleep_h", "activity_score"),
        "high_activity_to_next_hrv": _lagged_pairs(rows, "high_activity_min", "avg_hrv"),
        "stress_to_next_hrv": _lagged_pairs(rows, "stress_high_min", "avg_hrv"),
        "sleep_duration_to_score": _same_day_pairs(rows, "total_sleep_h", "sleep_score"),
    }
    correlations: dict[str, tuple[float, int]] = {}
    for name, pairs in candidates.items():
        result = pearson(pairs)
        if result is not None:
            correlations[name] = result

    streaks = {
        "readiness_ge_70": compute_streak(rows, "readiness_score", 70, above=True),
        "sleep_ge_7h": compute_streak(rows, "total_sleep_h", 7.0, above=True),
        "steps_ge_8000": compute_streak(rows, "steps", 8000, above=True),
    }

    return Analysis(
        rows=rows,
        trends=trends,
        today=rows[-1] if rows else None,
        sleep_debt_h=compute_sleep_debt(rows, sleep_need_h),
        bedtime_consistency_min=consistency * 60.0 if consistency is not None else None,
        weekday_sleep=weekday_sleep,
        correlations=correlations,
        streaks=streaks,
        sleep_need_h=sleep_need_h,
    )
