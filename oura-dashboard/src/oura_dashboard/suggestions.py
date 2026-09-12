"""Turn the analysis into ranked, evidence-backed morning suggestions.

Each rule is a small function over the :class:`Analysis`. A rule either returns
a :class:`Suggestion` or ``None``, and every suggestion carries the numbers that
triggered it, so the morning mail explains itself instead of just asserting.

These are pattern observations from your own trailing data, not medical advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .analysis import Analysis
from .metrics import format_clock

SEVERITY_ORDER = {"critical": 0, "warn": 1, "info": 2, "win": 3}

CONTRIBUTOR_LABELS = {
    "activity_balance": "activity balance",
    "body_temperature": "body temperature",
    "hrv_balance": "HRV balance",
    "previous_day_activity": "previous day's activity",
    "previous_night": "previous night",
    "recovery_index": "recovery index",
    "resting_heart_rate": "resting heart rate",
    "sleep_balance": "sleep balance",
    "sleep_regularity": "sleep regularity",
    "deep_sleep": "deep sleep",
    "efficiency": "sleep efficiency",
    "latency": "sleep latency",
    "rem_sleep": "REM sleep",
    "restfulness": "restfulness",
    "timing": "sleep timing",
    "total_sleep": "total sleep",
    "meet_daily_targets": "meeting daily targets",
    "move_every_hour": "moving every hour",
    "recovery_time": "recovery time",
    "stay_active": "staying active",
    "training_frequency": "training frequency",
    "training_volume": "training volume",
}

RESILIENCE_RANK = {
    "limited": 0,
    "adequate": 1,
    "solid": 2,
    "strong": 3,
    "exceptional": 4,
}


@dataclass
class Suggestion:
    id: str
    severity: str       # critical | warn | info | win
    title: str          # the recommendation itself
    detail: str         # the evidence, with numbers
    action: str = ""    # concretely what to do today
    tags: list[str] = field(default_factory=list)

    @property
    def rank(self) -> int:
        return SEVERITY_ORDER.get(self.severity, 9)


Rule = Callable[[Analysis], Suggestion | None]
RULES: list[Rule] = []


def rule(func: Rule) -> Rule:
    RULES.append(func)
    return func


def _fmt(value: float | None, digits: int = 1, unit: str = "") -> str:
    if value is None:
        return "--"
    return f"{value:.{digits}f}{unit}" if digits else f"{value:.0f}{unit}"


def _sentence(text: str) -> str:
    """Upper-case the first letter only — str.capitalize() would lower SpO₂ and REM."""
    return text[:1].upper() + text[1:]


def _hm(hours: float | None) -> str:
    """Hours as `7h 20m`."""
    if hours is None:
        return "--"
    total = int(round(abs(hours) * 60))
    sign = "-" if hours < 0 else ""
    return f"{sign}{total // 60}h {total % 60:02d}m"


def _worst_contributor(contributors: dict[str, float], limit: float = 70.0):
    if not contributors:
        return None
    name, value = min(contributors.items(), key=lambda kv: kv[1])
    if value >= limit:
        return None
    return CONTRIBUTOR_LABELS.get(name, name.replace("_", " ")), value


# --------------------------------------------------------------------------
# Recovery and readiness
# --------------------------------------------------------------------------
@rule
def low_readiness(a: Analysis) -> Suggestion | None:
    today = a.today
    if today is None or today.readiness_score is None:
        return None
    score = today.readiness_score
    trend = a.trend("readiness_score")
    z = trend.z
    baseline = trend.baseline_avg

    # A low absolute score is only worth flagging if it is also low *for you*:
    # someone whose baseline sits at 60 should not be told to rest at 67.
    absolute_low = score < 70 and (baseline is None or score <= baseline + 2)
    relative_low = z is not None and z <= -1.5
    if not (absolute_low or relative_low):
        return None

    worst = _worst_contributor(today.readiness_contributors)
    because = f" The weakest contributor is {worst[0]} at {worst[1]:.0f}." if worst else ""
    severity = "critical" if score < 60 or (z is not None and z <= -2) else "warn"
    if baseline is None:
        comparison = ""
    elif relative_low:
        comparison = f" That is {baseline - score:.0f} points below your 28-day average."
    else:
        comparison = f" Your 28-day average is {baseline:.0f}."
    return Suggestion(
        id="low_readiness",
        severity=severity,
        title="Keep today easy — your body is asking for recovery",
        detail=f"Readiness is {score:.0f}.{comparison}{because}",
        action=(
            "Swap anything hard for a walk, easy spin or mobility work, and keep "
            "caffeine earlier than usual."
        ),
        tags=["recovery"],
    )


@rule
def hrv_drop(a: Analysis) -> Suggestion | None:
    trend = a.trend("avg_hrv")
    if not trend.reliable or trend.today is None or trend.baseline_avg is None:
        return None
    z = trend.z
    if z is None or z > -1.25:
        return None
    return Suggestion(
        id="hrv_drop",
        severity="warn" if z > -2 else "critical",
        title="HRV is well below your baseline",
        detail=(
            f"Last night's average HRV was {trend.today:.0f} ms against a baseline of "
            f"{trend.baseline_avg:.0f} ms ({z:+.1f} SD)."
        ),
        action=(
            "This usually follows hard training, alcohol, a late meal or stress. "
            "Go aerobic-easy today and prioritise an early night."
        ),
        tags=["recovery", "hrv"],
    )


@rule
def elevated_resting_hr(a: Analysis) -> Suggestion | None:
    trend = a.trend("lowest_hr")
    if not trend.reliable or trend.today is None or trend.baseline_avg is None:
        return None
    delta = trend.today - trend.baseline_avg
    if delta < 3.0:
        return None
    return Suggestion(
        id="elevated_resting_hr",
        severity="warn" if delta < 6 else "critical",
        title="Resting heart rate is elevated overnight",
        detail=(
            f"Lowest overnight heart rate was {trend.today:.0f} bpm, "
            f"{delta:+.0f} bpm above your {trend.baseline_avg:.0f} bpm baseline."
        ),
        action=(
            "Hydrate well, hold off on intensity, and check in with how you feel — "
            "this is an early marker of fighting something off."
        ),
        tags=["recovery", "heart"],
    )


@rule
def temperature_deviation(a: Analysis) -> Suggestion | None:
    today = a.today
    if today is None or today.temperature_deviation is None:
        return None
    deviation = today.temperature_deviation
    if deviation < 0.4:
        return None
    return Suggestion(
        id="temperature_deviation",
        severity="critical" if deviation >= 0.7 else "warn",
        title="Body temperature is running warm",
        detail=f"Skin temperature deviation is {deviation:+.1f}°C from your baseline.",
        action=(
            "Common causes are illness onset, a late alcohol or heavy meal, a hot "
            "room, or hormonal cycle phase. Treat today as a rest day if it holds."
        ),
        tags=["recovery", "illness"],
    )


@rule
def resilience_drop(a: Analysis) -> Suggestion | None:
    levels = [r.resilience_level for r in a.rows if r.resilience_level]
    if len(levels) < 8:
        return None
    current = levels[-1]
    previous = levels[-8]
    now_rank = RESILIENCE_RANK.get(str(current).lower())
    then_rank = RESILIENCE_RANK.get(str(previous).lower())
    if now_rank is None or then_rank is None or now_rank >= then_rank:
        return None
    return Suggestion(
        id="resilience_drop",
        severity="warn",
        title="Resilience has slipped over the past week",
        detail=f"Resilience moved from “{previous}” to “{current}” in the last seven days.",
        action=(
            "Resilience tracks how well recovery keeps up with load. Protect sleep "
            "and add one genuinely restful day this week."
        ),
        tags=["recovery"],
    )


# --------------------------------------------------------------------------
# Sleep
# --------------------------------------------------------------------------
@rule
def sleep_debt(a: Analysis) -> Suggestion | None:
    debt = a.sleep_debt_h
    if debt is None or debt < 2.0:
        return None
    nights = min(len([r for r in a.rows[-7:] if r.total_sleep_h is not None]), 7)
    per_night = debt / nights if nights else debt
    return Suggestion(
        id="sleep_debt",
        severity="critical" if debt >= 6 else "warn",
        title=f"You are carrying {_hm(debt)} of sleep debt",
        detail=(
            f"Over the last {nights} nights you averaged {_hm(a.sleep_need_h - per_night)} "
            f"against a {_hm(a.sleep_need_h)} target."
        ),
        action=(
            f"Going to bed {int(round(min(per_night * 60, 90)))} minutes earlier tonight "
            "clears most of this without a weekend catch-up binge."
        ),
        tags=["sleep"],
    )


@rule
def bedtime_inconsistency(a: Analysis) -> Suggestion | None:
    spread = a.bedtime_consistency_min
    if spread is None or spread < 60.0:
        return None
    return Suggestion(
        id="bedtime_inconsistency",
        severity="warn" if spread >= 90 else "info",
        title="Your bedtime is drifting night to night",
        detail=(
            f"Bedtime has varied by ±{spread:.0f} minutes over the last four weeks."
        ),
        action=(
            "A fixed wake time is the strongest lever — anchor that first and bedtime "
            "follows. Aim to keep bedtime inside a 30-minute window."
        ),
        tags=["sleep", "consistency"],
    )


@rule
def bedtime_drift_late(a: Analysis) -> Suggestion | None:
    trend = a.trend("bedtime_start_h")
    if not trend.reliable or trend.delta is None:
        return None
    drift_min = trend.delta * 60.0
    if drift_min < 30.0:
        return None
    return Suggestion(
        id="bedtime_drift_late",
        severity="info",
        title="Bedtime has crept later this week",
        detail=(
            f"You have been going to bed around {format_clock(trend.recent_avg)}, "
            f"{drift_min:.0f} minutes later than your {format_clock(trend.baseline_avg)} norm."
        ),
        action="Pull tonight's wind-down forward by half an hour to reset the drift.",
        tags=["sleep", "consistency"],
    )


@rule
def poor_efficiency(a: Analysis) -> Suggestion | None:
    today = a.today
    if today is None or today.efficiency is None:
        return None
    if today.efficiency >= 85:
        return None
    awake = _hm(today.awake_h) if today.awake_h is not None else "--"
    restless = today.restless_periods
    extra = f" with {restless:.0f} restless periods" if restless else ""
    return Suggestion(
        id="poor_efficiency",
        severity="warn" if today.efficiency < 80 else "info",
        title="You spent a lot of last night awake in bed",
        detail=(
            f"Sleep efficiency was {today.efficiency:.0f}% — {awake} awake{extra}."
        ),
        action=(
            "Keep the room cool and dark, and avoid alcohol and late screens. "
            "If you are awake more than 20 minutes, get up briefly rather than lie there."
        ),
        tags=["sleep"],
    )


@rule
def long_latency(a: Analysis) -> Suggestion | None:
    today = a.today
    if today is None or today.latency_min is None or today.latency_min < 30:
        return None
    return Suggestion(
        id="long_latency",
        severity="info",
        title="You took a while to fall asleep",
        detail=f"Sleep latency was {today.latency_min:.0f} minutes last night.",
        action=(
            "Long latency usually means going to bed too early, too much evening "
            "light, or an activated nervous system. Try a 20-minute screen-free wind-down."
        ),
        tags=["sleep"],
    )


@rule
def low_deep_or_rem(a: Analysis) -> Suggestion | None:
    today = a.today
    if today is None or not today.total_sleep_h:
        return None
    findings: list[str] = []
    deep_trend = a.trend("deep_h")
    rem_trend = a.trend("rem_h")
    if (
        today.deep_h is not None
        and deep_trend.baseline_avg
        and today.deep_h < deep_trend.baseline_avg * 0.7
    ):
        findings.append(
            f"deep sleep {_hm(today.deep_h)} vs {_hm(deep_trend.baseline_avg)} typical"
        )
    if (
        today.rem_h is not None
        and rem_trend.baseline_avg
        and today.rem_h < rem_trend.baseline_avg * 0.7
    ):
        findings.append(
            f"REM {_hm(today.rem_h)} vs {_hm(rem_trend.baseline_avg)} typical"
        )
    if not findings:
        return None
    return Suggestion(
        id="low_deep_or_rem",
        severity="info",
        title="Restorative sleep stages were short last night",
        detail=_sentence(" and ".join(findings)) + ".",
        action=(
            "Deep sleep suffers from late alcohol and late exercise; REM suffers "
            "from short nights and early alarms. Protect the back half of your night."
        ),
        tags=["sleep"],
    )


@rule
def frequent_naps(a: Analysis) -> Suggestion | None:
    napped = [r for r in a.rows[-7:] if (r.nap_h or 0) > 0.25]
    if len(napped) < 3:
        return None
    total = sum(r.nap_h or 0 for r in napped)
    return Suggestion(
        id="frequent_naps",
        severity="info",
        title="You have been napping most days",
        detail=f"{len(napped)} naps in the last 7 days, {_hm(total)} in total.",
        action=(
            "Daytime sleep pressure like this usually points at short or fragmented "
            "nights. Keep naps under 25 minutes and before mid-afternoon."
        ),
        tags=["sleep"],
    )


# --------------------------------------------------------------------------
# Activity and training load
# --------------------------------------------------------------------------
@rule
def overtraining(a: Analysis) -> Suggestion | None:
    load = a.trend("high_activity_min")
    readiness = a.trend("readiness_score")
    if load.delta is None or readiness.delta is None or not load.reliable:
        return None
    if load.delta <= 10 or readiness.delta >= -2:
        return None
    return Suggestion(
        id="overtraining",
        severity="warn",
        title="Training load is up while readiness is trending down",
        detail=(
            f"High-intensity minutes are {load.delta:+.0f}/day above baseline while "
            f"readiness is {readiness.delta:+.0f} points below it."
        ),
        action=(
            "Hold volume but cut intensity for two or three days, or take a full rest "
            "day — this is the pattern that precedes a stall."
        ),
        tags=["training"],
    )


@rule
def sedentary(a: Analysis) -> Suggestion | None:
    steps = a.trend("steps")
    if steps.recent_avg is None:
        return None
    if steps.recent_avg >= 7000:
        return None
    alerts = a.trend("inactivity_alerts")
    extra = (
        f" You are averaging {alerts.recent_avg:.0f} inactivity alerts a day."
        if alerts.recent_avg
        else ""
    )
    return Suggestion(
        id="sedentary",
        severity="info",
        title="Movement has been light this week",
        detail=f"You are averaging {steps.recent_avg:.0f} steps a day.{extra}",
        action=(
            "Two 15-minute walks — one after lunch, one after dinner — is the cheapest "
            "way to add both steps and better sleep pressure."
        ),
        tags=["activity"],
    )


@rule
def ready_to_train(a: Analysis) -> Suggestion | None:
    today = a.today
    if today is None or today.readiness_score is None:
        return None
    if today.readiness_score < 85:
        return None
    hrv = a.trend("avg_hrv")
    if hrv.z is not None and hrv.z < -0.5:
        return None
    load = a.trend("high_activity_min")
    quiet = load.recent_avg is not None and load.recent_avg < 30
    return Suggestion(
        id="ready_to_train",
        severity="win",
        title="Good day to train hard",
        detail=(
            f"Readiness is {today.readiness_score:.0f}"
            + (f" with HRV {today.avg_hrv:.0f} ms" if today.avg_hrv else "")
            + "."
        ),
        action=(
            "If you have a hard session in the plan, today is the day for it."
            + (" Your recent intensity has been low, so there is room." if quiet else "")
        ),
        tags=["training"],
    )


# --------------------------------------------------------------------------
# Stress, breathing, and long-horizon markers
# --------------------------------------------------------------------------
@rule
def high_stress(a: Analysis) -> Suggestion | None:
    stress = a.trend("stress_high_min")
    if stress.recent_avg is None or stress.recent_avg < 60:
        return None
    recovery = a.trend("recovery_high_min")
    balance = ""
    if recovery.recent_avg is not None:
        balance = (
            f" against {recovery.recent_avg:.0f} minutes of restorative time"
        )
    return Suggestion(
        id="high_stress",
        severity="warn" if stress.recent_avg >= 120 else "info",
        title="Daytime stress load is high",
        detail=(
            f"Averaging {stress.recent_avg:.0f} minutes a day in high stress{balance}."
        ),
        action=(
            "Book two deliberate downshifts today — a walk without your phone, or "
            "five minutes of slow breathing between meetings."
        ),
        tags=["stress"],
    )


@rule
def breathing_disturbance(a: Analysis) -> Suggestion | None:
    today = a.today
    if today is None:
        return None
    spo2 = today.spo2_avg
    bdi = today.breathing_disturbance_index
    problems: list[str] = []
    if spo2 is not None and spo2 < 94:
        problems.append(f"average overnight SpO₂ was {spo2:.1f}%")
    bdi_trend = a.trend("breathing_disturbance_index")
    if (
        bdi is not None
        and bdi_trend.baseline_avg is not None
        and bdi > max(bdi_trend.baseline_avg * 1.5, bdi_trend.baseline_avg + 3)
    ):
        problems.append(
            f"breathing disturbance index was {bdi:.0f} vs {bdi_trend.baseline_avg:.0f} typical"
        )
    if not problems:
        return None
    return Suggestion(
        id="breathing_disturbance",
        severity="warn",
        title="Overnight breathing looked disturbed",
        detail=_sentence(" and ".join(problems)) + ".",
        action=(
            "Side sleeping, a clear nose and skipping late alcohol all help. If this "
            "repeats regularly, it is worth raising with a doctor."
        ),
        tags=["breathing"],
    )


@rule
def vascular_age_gap(a: Analysis) -> Suggestion | None:
    today = a.today
    if today is None or today.vascular_age is None:
        return None
    trend = a.trend("vascular_age")
    if trend.delta is None or trend.delta < 1.0:
        return None
    return Suggestion(
        id="vascular_age_gap",
        severity="info",
        title="Cardiovascular age is trending up",
        detail=(
            f"Vascular age reads {today.vascular_age:.0f}, up {trend.delta:.1f} years "
            "against your recent baseline."
        ),
        action=(
            "This metric responds to aerobic base work — steady zone-2 sessions and "
            "consistent sleep move it more than hard intervals."
        ),
        tags=["longterm"],
    )


@rule
def data_gap(a: Analysis) -> Suggestion | None:
    recent = a.rows[-7:]
    missing = [r.day for r in recent if r.total_sleep_h is None]
    non_wear = [r.non_wear_h for r in recent if r.non_wear_h is not None]
    long_non_wear = [h for h in non_wear if h > 4]
    if len(missing) < 2 and not long_non_wear:
        return None
    parts: list[str] = []
    if len(missing) >= 2:
        parts.append(f"{len(missing)} of the last 7 nights have no sleep data")
    if long_non_wear:
        parts.append(f"{len(long_non_wear)} days with over 4 hours of non-wear time")
    return Suggestion(
        id="data_gap",
        severity="info",
        title="Some data is missing from this week",
        detail=_sentence(" and ".join(parts)) + ".",
        action=(
            "Trends get shaky with gaps — check the ring is charged and syncing, and "
            "charge it during the day rather than overnight."
        ),
        tags=["data"],
    )


# --------------------------------------------------------------------------
# Positive reinforcement — a brief that only nags gets ignored
# --------------------------------------------------------------------------
@rule
def streak_win(a: Analysis) -> Suggestion | None:
    wins: list[str] = []
    if a.streaks.get("sleep_ge_7h", 0) >= 3:
        wins.append(f"{a.streaks['sleep_ge_7h']} nights of 7+ hours")
    if a.streaks.get("readiness_ge_70", 0) >= 5:
        wins.append(f"{a.streaks['readiness_ge_70']} days of readiness at 70+")
    if a.streaks.get("steps_ge_8000", 0) >= 4:
        wins.append(f"{a.streaks['steps_ge_8000']} days above 8,000 steps")
    if not wins:
        return None
    return Suggestion(
        id="streak_win",
        severity="win",
        title="Streak worth protecting",
        detail=" · ".join(wins) + ".",
        action="Whatever you changed recently, keep it.",
        tags=["win"],
    )


@rule
def improving_metric(a: Analysis) -> Suggestion | None:
    watch = [
        ("avg_hrv", "HRV", "ms", 1, True),
        ("total_sleep_h", "sleep duration", "", 0, True),
        ("sleep_score", "sleep score", "", 0, True),
        ("readiness_score", "readiness", "", 0, True),
        ("steps", "daily steps", "", 0, True),
    ]
    best: tuple[float, str] | None = None
    for metric, label, unit, digits, higher_better in watch:
        trend = a.trend(metric)
        if not trend.reliable or trend.delta_pct is None:
            continue
        gain = trend.delta_pct if higher_better else -trend.delta_pct
        if gain < 8.0:
            continue
        if metric == "total_sleep_h":
            text = f"{label} up {_hm(trend.delta)} a night"
        else:
            text = f"{label} up {abs(trend.delta):.{digits}f}{unit} ({gain:+.0f}%)"
        if best is None or gain > best[0]:
            best = (gain, text)
    if best is None:
        return None
    return Suggestion(
        id="improving_metric",
        severity="win",
        title="Something is working",
        detail=_sentence(best[1]) + " against your four-week baseline.",
        action="Worth noting what changed so you can keep doing it.",
        tags=["win"],
    )


@rule
def weekday_pattern(a: Analysis) -> Suggestion | None:
    if len(a.weekday_sleep) < 6:
        return None
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    worst_day, worst_score = min(a.weekday_sleep.items(), key=lambda kv: kv[1])
    best_day, best_score = max(a.weekday_sleep.items(), key=lambda kv: kv[1])
    if best_score - worst_score < 8:
        return None
    return Suggestion(
        id="weekday_pattern",
        severity="info",
        title=f"{names[worst_day]} is consistently your worst night",
        detail=(
            f"{names[worst_day]} averages a {worst_score:.0f} sleep score versus "
            f"{best_score:.0f} on {names[best_day]}."
        ),
        action=(
            f"Whatever is different about {names[worst_day]} evenings — later food, "
            "drinks, screens, training — that is the single highest-leverage fix."
        ),
        tags=["sleep", "pattern"],
    )


@rule
def correlation_insight(a: Analysis) -> Suggestion | None:
    templates = {
        "steps_to_next_readiness": (
            "Days you move more, you wake up more ready",
            "Steps correlate {r:+.2f} with next-day readiness across {n} days.",
            "Getting your steps in today pays out tomorrow morning.",
        ),
        "bedtime_to_sleep_score": (
            "Later bedtimes cost you sleep quality",
            "Bedtime correlates {r:+.2f} with sleep score across {n} nights.",
            "Every 30 minutes earlier is measurably worth it for you.",
        ),
        "sleep_to_next_activity": (
            "Sleep drives how much you move the next day",
            "Sleep duration correlates {r:+.2f} with next-day activity across {n} days.",
            "Protecting sleep is also protecting your training consistency.",
        ),
        "high_activity_to_next_hrv": (
            "Hard days blunt your HRV the next morning",
            "Intensity correlates {r:+.2f} with next-day HRV across {n} days.",
            "Follow hard sessions with a genuinely easy day.",
        ),
        "stress_to_next_hrv": (
            "High-stress days show up in the next morning's HRV",
            "Stress minutes correlate {r:+.2f} with next-day HRV across {n} days.",
            "A wind-down routine on heavy days protects the next morning.",
        ),
    }
    best: tuple[float, str, str, str] | None = None
    for key, (title, detail, action) in templates.items():
        found = a.correlations.get(key)
        if not found:
            continue
        r, n = found
        # Only surface a relationship in the direction the template describes.
        expected_negative = key in {
            "bedtime_to_sleep_score",
            "high_activity_to_next_hrv",
            "stress_to_next_hrv",
        }
        if expected_negative and r > -0.3:
            continue
        if not expected_negative and r < 0.3:
            continue
        strength = abs(r)
        if best is None or strength > best[0]:
            best = (strength, title, detail.format(r=r, n=n), action)
    if best is None:
        return None
    return Suggestion(
        id="correlation_insight",
        severity="info",
        title=best[1],
        detail=best[2],
        action=best[3],
        tags=["pattern"],
    )


# --------------------------------------------------------------------------
def generate(analysis: Analysis, limit: int | None = None) -> list[Suggestion]:
    """Run every rule and return suggestions, most urgent first."""
    found: list[Suggestion] = []
    for rule_fn in RULES:
        try:
            result = rule_fn(analysis)
        except Exception:  # a single bad rule must not lose the whole brief
            continue
        if result is not None:
            found.append(result)

    found.sort(key=lambda s: (s.rank, s.id))

    if not found:
        found.append(
            Suggestion(
                id="all_clear",
                severity="win",
                title="Nothing needs your attention today",
                detail="Every tracked metric is sitting inside its normal range.",
                action="Carry on with the plan you already had.",
                tags=["win"],
            )
        )
    return found[:limit] if limit else found
