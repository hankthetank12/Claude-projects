"""Synthetic but plausible Oura documents, for demos and tests.

The API sandbox returns the same numbers every day, which is useless for
trend and baseline logic, so this builds a deterministic fake history with
weekday effects, a training block and a short illness episode.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

UTC = timezone.utc


def _iso(day: date, clock: float) -> str:
    """A `YYYY-MM-DDTHH:MM:SS+00:00` stamp, where clock may exceed 24h."""
    base = datetime.combine(day, time(0, 0), tzinfo=UTC)
    return (base + timedelta(hours=clock)).isoformat(timespec="milliseconds")


def generate(days: int = 120, end: date | None = None, seed: int = 7) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(seed)
    end = end or date.today()
    start = end - timedelta(days=days - 1)

    out: dict[str, list[dict[str, Any]]] = {
        "daily_sleep": [],
        "daily_readiness": [],
        "daily_activity": [],
        "daily_stress": [],
        "daily_spo2": [],
        "daily_resilience": [],
        "daily_cardiovascular_age": [],
        "sleep": [],
        "workout": [],
        "vO2_max": [],
        "personal_info": [
            {"id": "sample-user", "age": 34, "weight": 74.0, "height": 1.79,
             "biological_sex": "male", "email": "sample@example.com"}
        ],
    }

    for index in range(days):
        day = start + timedelta(days=index)
        weekday = day.weekday()
        is_weekend = weekday >= 5
        progress = index / max(days - 1, 1)

        # A hard training block in the final three weeks, and a bug 12 days out.
        training_block = index > days - 22
        ill = (days - 12) <= index <= (days - 9)

        # --- sleep -------------------------------------------------------
        bedtime = 23.1 + (1.1 if is_weekend else 0.0) + rng.gauss(0, 0.45)
        bedtime += 0.4 * progress  # slow drift later over the period
        wake = bedtime + 7.6 + (0.7 if is_weekend else 0.0) + rng.gauss(0, 0.4)
        time_in_bed_h = max(4.5, wake - bedtime)
        efficiency = max(68.0, min(97.0, rng.gauss(90 if not ill else 80, 3.5)))
        total_sleep_h = time_in_bed_h * efficiency / 100.0
        latency_min = max(2.0, rng.gauss(18 if not ill else 34, 7))
        awake_h = max(0.05, time_in_bed_h - total_sleep_h)
        deep_h = max(0.3, total_sleep_h * rng.gauss(0.17, 0.03) - (0.25 if ill else 0))
        rem_h = max(0.4, total_sleep_h * rng.gauss(0.22, 0.035))
        light_h = max(0.5, total_sleep_h - deep_h - rem_h)

        hrv = rng.gauss(58, 6)
        hrv += 6 * math.sin(progress * math.pi)          # fitness arc
        hrv -= 12 if ill else 0
        hrv -= 5 if training_block else 0
        hrv = max(18.0, hrv)

        lowest_hr = rng.gauss(52, 2.5) + (5 if ill else 0) + (1.5 if training_block else 0)
        avg_hr = lowest_hr + rng.gauss(7, 1.2)

        sleep_score = int(max(35, min(98,
            58 + (total_sleep_h - 7.0) * 9 + (efficiency - 88) * 0.9
            + rng.gauss(0, 4) - (10 if ill else 0))))

        out["sleep"].append({
            "id": f"sleep-{day}",
            "day": day.isoformat(),
            "type": "long_sleep",
            "bedtime_start": _iso(day - timedelta(days=1), bedtime),
            "bedtime_end": _iso(day - timedelta(days=1), wake),
            "total_sleep_duration": int(total_sleep_h * 3600),
            "time_in_bed": int(time_in_bed_h * 3600),
            "deep_sleep_duration": int(deep_h * 3600),
            "rem_sleep_duration": int(rem_h * 3600),
            "light_sleep_duration": int(light_h * 3600),
            "awake_time": int(awake_h * 3600),
            "efficiency": int(round(efficiency)),
            "latency": int(latency_min * 60),
            "restless_periods": int(max(0, rng.gauss(14 if not ill else 24, 5))),
            "average_hrv": int(round(hrv)),
            "average_heart_rate": round(avg_hr, 1),
            "lowest_heart_rate": int(round(lowest_hr)),
            "average_breath": round(rng.gauss(14.2, 0.8), 1),
            "period": 0,
        })

        # An occasional afternoon nap, more likely after a short night.
        if rng.random() < (0.28 if total_sleep_h < 6.6 else 0.07):
            nap_h = rng.uniform(0.3, 1.1)
            out["sleep"].append({
                "id": f"sleep-nap-{day}",
                "day": day.isoformat(),
                "type": "late_nap",
                "bedtime_start": _iso(day, 14.5),
                "bedtime_end": _iso(day, 14.5 + nap_h),
                "total_sleep_duration": int(nap_h * 3600),
                "time_in_bed": int(nap_h * 3700),
                "efficiency": 88,
            })

        out["daily_sleep"].append({
            "id": f"daily_sleep-{day}",
            "day": day.isoformat(),
            "score": sleep_score,
            "timestamp": _iso(day, 0),
            "contributors": {
                "deep_sleep": int(max(20, min(100, 60 + (deep_h - 1.2) * 40))),
                "efficiency": int(max(20, min(100, efficiency + 4))),
                "latency": int(max(15, min(100, 100 - latency_min * 1.6))),
                "rem_sleep": int(max(20, min(100, 60 + (rem_h - 1.5) * 35))),
                "restfulness": int(max(20, min(100, rng.gauss(72, 10)))),
                "timing": int(max(20, min(100, 100 - abs(bedtime - 23.0) * 22))),
                "total_sleep": int(max(20, min(100, 55 + (total_sleep_h - 7.0) * 22))),
            },
        })

        # --- activity ----------------------------------------------------
        steps = int(max(1200, rng.gauss(9200 if not is_weekend else 7400, 2600)
                        - (3200 if ill else 0) + (900 if training_block else 0)))
        high_min = max(0.0, rng.gauss(26 if training_block else 13, 12) - (12 if ill else 0))
        medium_min = max(0.0, rng.gauss(44, 16))
        low_min = max(30.0, rng.gauss(210, 45))
        active_cal = int(220 + steps * 0.035 + high_min * 6)
        activity_score = int(max(35, min(99, 55 + (steps - 8000) / 260 + rng.gauss(0, 5))))

        out["daily_activity"].append({
            "id": f"daily_activity-{day}",
            "day": day.isoformat(),
            "score": activity_score,
            "timestamp": _iso(day, 0),
            "steps": steps,
            "active_calories": active_cal,
            "total_calories": active_cal + 1750,
            "target_calories": 2400,
            "high_activity_time": int(high_min * 60),
            "medium_activity_time": int(medium_min * 60),
            "low_activity_time": int(low_min * 60),
            "sedentary_time": int(max(3.0, rng.gauss(9.5, 1.4)) * 3600),
            "non_wear_time": int(max(0, rng.gauss(0.4, 0.9)) * 3600),
            "inactivity_alerts": int(max(0, rng.gauss(2.2, 1.5))),
            "equivalent_walking_distance": int(steps * 0.72),
            "resting_time": int(8 * 3600),
            "average_met_minutes": round(rng.gauss(1.5, 0.2), 2),
            "contributors": {
                "meet_daily_targets": int(max(20, min(100, rng.gauss(78, 14)))),
                "move_every_hour": int(max(20, min(100, rng.gauss(82, 12)))),
                "recovery_time": int(max(20, min(100, rng.gauss(80, 13)))),
                "stay_active": int(max(20, min(100, rng.gauss(76, 14)))),
                "training_frequency": int(max(20, min(100, rng.gauss(70, 16)))),
                "training_volume": int(max(20, min(100, rng.gauss(74, 15)))),
            },
        })

        if high_min > 20 and rng.random() < 0.75:
            duration_h = rng.uniform(0.6, 1.4)
            out["workout"].append({
                "id": f"workout-{day}",
                "day": day.isoformat(),
                "activity": rng.choice(["running", "cycling", "strength_training", "swimming"]),
                "intensity": rng.choice(["moderate", "hard"]),
                "calories": round(rng.uniform(300, 780), 1),
                "distance": round(rng.uniform(4000, 14000), 1),
                "start_datetime": _iso(day, 17.5),
                "end_datetime": _iso(day, 17.5 + duration_h),
                "source": "manual",
                "label": None,
            })

        # --- readiness ---------------------------------------------------
        temp_dev = round(rng.gauss(0.0, 0.14) + (0.75 if ill else 0), 2)
        readiness_score = int(max(30, min(99,
            0.45 * sleep_score + 0.2 * activity_score + (hrv - 55) * 0.7
            - (lowest_hr - 52) * 1.6 - abs(temp_dev) * 14 + 26 + rng.gauss(0, 3))))

        out["daily_readiness"].append({
            "id": f"daily_readiness-{day}",
            "day": day.isoformat(),
            "score": readiness_score,
            "timestamp": _iso(day, 0),
            "temperature_deviation": temp_dev,
            "temperature_trend_deviation": round(temp_dev * 0.6, 2),
            "contributors": {
                "activity_balance": int(max(20, min(100, rng.gauss(78, 12)))),
                "body_temperature": int(max(15, min(100, 98 - abs(temp_dev) * 70))),
                "hrv_balance": int(max(15, min(100, 55 + (hrv - 55) * 2.2))),
                "previous_day_activity": int(max(20, min(100, rng.gauss(80, 12)))),
                "previous_night": int(max(20, min(100, sleep_score + rng.gauss(0, 6)))),
                "recovery_index": int(max(20, min(100, rng.gauss(82, 14)))),
                "resting_heart_rate": int(max(15, min(100, 95 - (lowest_hr - 50) * 6))),
                "sleep_balance": int(max(20, min(100, rng.gauss(76, 13)))),
                "sleep_regularity": int(max(20, min(100, 90 - abs(bedtime - 23.2) * 25))),
            },
        })

        # --- stress, spo2, resilience ------------------------------------
        # The API reports these in seconds, so generate minutes and convert.
        stress_min = max(0.0, rng.gauss(74 if not is_weekend else 42, 34) + (40 if ill else 0))
        recovery_min = max(0.0, rng.gauss(150, 50))
        out["daily_stress"].append({
            "id": f"daily_stress-{day}",
            "day": day.isoformat(),
            "stress_high": int(stress_min * 60),
            "recovery_high": int(recovery_min * 60),
            "day_summary": (
                "stressful" if stress_min > 130 else "normal" if stress_min > 40 else "restored"
            ),
        })

        out["daily_spo2"].append({
            "id": f"daily_spo2-{day}",
            "day": day.isoformat(),
            "spo2_percentage": {"average": round(rng.gauss(96.4, 0.6) - (1.4 if ill else 0), 1)},
            "breathing_disturbance_index": int(max(0, rng.gauss(6, 3) + (7 if ill else 0))),
        })

        if readiness_score >= 85:
            level = "strong"
        elif readiness_score >= 75:
            level = "solid"
        elif readiness_score >= 65:
            level = "adequate"
        else:
            level = "limited"
        out["daily_resilience"].append({
            "id": f"daily_resilience-{day}",
            "day": day.isoformat(),
            "level": level,
            "contributors": {
                "sleep_recovery": round(max(10, min(100, sleep_score + rng.gauss(0, 6))), 1),
                "daytime_recovery": round(max(10, min(100, rng.gauss(72, 12))), 1),
                "stress": round(max(10, min(100, 100 - stress_min * 0.35)), 1),
            },
        })

        # Weekly long-horizon markers.
        if index % 7 == 0:
            out["daily_cardiovascular_age"].append({
                "id": f"cva-{day}",
                "day": day.isoformat(),
                "vascular_age": int(round(32 + rng.gauss(0, 1.1) - progress * 1.5)),
                "pulse_wave_velocity": None,
            })
            out["vO2_max"].append({
                "id": f"vo2-{day}",
                "day": day.isoformat(),
                "timestamp": _iso(day, 0),
                "vo2_max": round(44 + progress * 2.5 + rng.gauss(0, 0.8), 1),
            })

    return out
