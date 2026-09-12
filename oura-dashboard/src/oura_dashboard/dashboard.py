"""Render the dashboard as one self-contained HTML file.

The page embeds the daily rows as JSON and draws its charts client-side, so a
single file gives you hover tooltips and a working range filter with no server
and no external requests.
"""

from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from .analysis import Analysis
from .metrics import DayRow, format_clock
from .suggestions import Suggestion

ASSETS = Path(__file__).parent / "assets"

SEVERITY_WORD = {
    "critical": "Act today",
    "warn": "Worth noting",
    "info": "Insight",
    "win": "Win",
}

# Stat tiles: (label, metric, unit, decimals, higher_is_better)
TILES: tuple[tuple[str, str, str, int, bool], ...] = (
    ("Readiness", "readiness_score", "", 0, True),
    ("Sleep score", "sleep_score", "", 0, True),
    ("Activity score", "activity_score", "", 0, True),
    ("Time asleep", "total_sleep_h", "h", 1, True),
    ("Avg HRV", "avg_hrv", " ms", 0, True),
    ("Resting HR", "lowest_hr", " bpm", 0, False),
    ("Steps", "steps", "", 0, True),
    ("Sleep efficiency", "efficiency", "%", 0, True),
    ("Respiratory rate", "avg_breath", "/min", 1, False),
    ("Blood oxygen", "spo2_avg", "%", 1, True),
    ("Body temp", "temperature_deviation", "°C", 2, False),
    ("High stress", "stress_high_min", " min", 0, False),
)

# Table columns: (header, metric, decimals)
TABLE_COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("Readiness", "readiness_score", 0),
    ("Sleep", "sleep_score", 0),
    ("Activity", "activity_score", 0),
    ("Asleep (h)", "total_sleep_h", 2),
    ("Deep (h)", "deep_h", 2),
    ("REM (h)", "rem_h", 2),
    ("Eff (%)", "efficiency", 0),
    ("Latency (m)", "latency_min", 0),
    ("HRV (ms)", "avg_hrv", 0),
    ("RHR (bpm)", "lowest_hr", 0),
    ("Breath (/m)", "avg_breath", 1),
    ("Temp (°C)", "temperature_deviation", 2),
    ("Steps", "steps", 0),
    ("Stress (m)", "stress_high_min", 0),
    ("SpO₂ (%)", "spo2_avg", 1),
)

CHART_CARDS: tuple[tuple[str, str, str, bool, tuple[tuple[str, str], ...]], ...] = (
    (
        "scores",
        "Sleep, readiness and activity",
        "Your three headline scores. Hover for any day.",
        True,
        (("Readiness", "--series-1"), ("Sleep", "--series-2"), ("Activity", "--series-3")),
    ),
    ("sleepDuration", "Time asleep", "Bars against your nightly sleep need.", False, ()),
    (
        "stages",
        "Sleep stages",
        "Deep, REM and light sleep, plus time awake in bed.",
        False,
        (("Deep", "--seq-700"), ("REM", "--seq-450"), ("Light", "--seq-250"), ("Awake", "--neutral-fill")),
    ),
    ("hrv", "Heart rate variability", "Higher is generally better recovered.", False, ()),
    ("rhr", "Resting heart rate", "Lowest heart rate reached overnight.", False, ()),
    ("window", "Sleep window", "When you fell asleep and woke, night by night.", False, ()),
    ("steps", "Daily steps", "Against an 8,000-step reference line.", False, ()),
    ("efficiency", "Sleep efficiency", "Share of time in bed actually asleep.", False, ()),
    (
        "stress",
        "Stress and recovery minutes",
        "Time your body spent stressed versus restored.",
        False,
        (("High stress", "--series-2"), ("Restorative", "--series-3")),
    ),
    ("temperature", "Body temperature deviation", "Distance from your own baseline.", False, ()),
    ("spo2", "Blood oxygen", "Average overnight SpO₂.", False, ()),
    ("weekday", "Sleep score by weekday", "Your worst night of the week is highlighted.", False, ()),
)


def _fmt_value(value: float | None, decimals: int) -> str:
    if value is None:
        return "--"
    if decimals == 0:
        return f"{value:,.0f}"
    return f"{value:,.{decimals}f}"


def _delta_text(analysis: Analysis, metric: str, decimals: int, higher_better: bool) -> tuple[str, str]:
    """A short '+3 vs 28-day avg' string and the class that colours it."""
    trend = analysis.trend(metric)
    if trend.today is None or trend.baseline_avg is None:
        return "no baseline yet", ""
    delta = trend.today - trend.baseline_avg
    # Anything that would round to zero at this precision reads as "level".
    if abs(delta) < (10**-decimals) / 2:
        return "level with your average", ""
    sign = "+" if delta > 0 else "−"
    magnitude = _fmt_value(abs(delta), decimals)
    good = (delta > 0) == higher_better
    return f"{sign}{magnitude} vs 28-day avg", "up" if good else "down"


def _payload(analysis: Analysis, sleep_need_h: float) -> dict[str, Any]:
    metrics = [
        "sleep_score", "readiness_score", "activity_score", "total_sleep_h",
        "deep_h", "rem_h", "light_h", "awake_h", "efficiency", "latency_min",
        "avg_hrv", "avg_hr", "lowest_hr", "avg_breath", "temperature_deviation",
        "steps", "active_calories", "high_activity_min", "sedentary_h",
        "stress_high_min", "recovery_high_min", "spo2_avg",
        "breathing_disturbance_index", "bedtime_start_h", "bedtime_end_h",
    ]
    days: list[dict[str, Any]] = []
    for row in analysis.rows:
        record: dict[str, Any] = {"day": row.day.isoformat(), "weekday": row.day.weekday()}
        for metric in metrics:
            value = row.get(metric)
            record[metric] = round(value, 4) if isinstance(value, float) else value
        days.append(record)
    return {
        "days": days,
        "meta": {
            "sleep_need_h": sleep_need_h,
            "generated": date.today().isoformat(),
        },
    }


def _suggestion_card(suggestion: Suggestion) -> str:
    return f"""      <article class="card {suggestion.severity}">
        <h3><span class="sev {suggestion.severity}">{SEVERITY_WORD.get(suggestion.severity, suggestion.severity)}</span>{html.escape(suggestion.title)}</h3>
        <p>{html.escape(suggestion.detail)}</p>
        <p class="do">{html.escape(suggestion.action)}</p>
      </article>"""


def _tiles_html(analysis: Analysis) -> str:
    parts: list[str] = []
    for label, metric, unit, decimals, higher_better in TILES:
        trend = analysis.trend(metric)
        if trend.today is None and trend.recent_avg is None:
            continue
        delta_text, delta_class = _delta_text(analysis, metric, decimals, higher_better)
        value = _fmt_value(trend.today, decimals)
        if metric == "temperature_deviation" and trend.today is not None and trend.today > 0:
            value = f"+{value}"
        parts.append(
            f"""      <div class="tile">
        <div class="name">{html.escape(label)}</div>
        <div class="value">{value}<span class="unit">{html.escape(unit)}</span></div>
        <div class="delta {delta_class}">{html.escape(delta_text)}</div>
        <div class="spark" data-spark="{metric}"></div>
      </div>"""
        )
    return "\n".join(parts)


def _chart_html(rows: Sequence[DayRow]) -> str:
    parts: list[str] = []
    for key, title, note, wide, legend in CHART_CARDS:
        legend_html = ""
        if legend:
            items = "".join(
                f'<li><span class="swatch" style="background:var({var})"></span>{html.escape(name)}</li>'
                for name, var in legend
            )
            legend_html = f'\n        <ul class="legend">{items}</ul>'
        parts.append(
            f"""      <section class="chart{' wide' if wide else ''}">
        <h3>{html.escape(title)}</h3>
        <p class="note">{html.escape(note)}</p>{legend_html}
        <div class="plot" data-chart="{key}"></div>
      </section>"""
        )
    return "\n".join(parts)


def _table_html(rows: Sequence[DayRow], limit: int = 60) -> str:
    headers = "".join(f"<th>{html.escape(name)}</th>" for name, _, _ in TABLE_COLUMNS)
    body: list[str] = []
    for row in reversed(rows[-limit:]):
        cells = "".join(
            f"<td>{_fmt_value(row.get(metric), decimals)}</td>"
            for _, metric, decimals in TABLE_COLUMNS
        )
        bedtime = format_clock(row.bedtime_start_h)
        body.append(f"<tr><td>{row.day.isoformat()}</td><td>{bedtime}</td>{cells}</tr>")
    return f"""    <details class="table-view">
      <summary>Table view — every number for the last {min(limit, len(rows))} days</summary>
      <div class="scroller">
        <table>
          <thead><tr><th>Day</th><th>Asleep at</th>{headers}</tr></thead>
          <tbody>
            {"".join(body)}
          </tbody>
        </table>
      </div>
    </details>"""


def _range_buttons(total: int) -> str:
    options = [(n, f"{n}d") for n in (30, 60, 90) if n < total]
    options.append((total, "All"))
    return "".join(
        f'<button type="button" data-range="{value}" aria-pressed="false">{html.escape(label)}</button>'
        for value, label in options
    )


def render(
    analysis: Analysis,
    suggestions: Sequence[Suggestion],
    *,
    title: str = "Oura dashboard",
    banner: str | None = None,
) -> str:
    rows = analysis.rows
    today = analysis.today
    css = (ASSETS / "dashboard.css").read_text(encoding="utf-8")
    js = (ASSETS / "dashboard.js").read_text(encoding="utf-8")
    payload = json.dumps(_payload(analysis, analysis.sleep_need_h), separators=(",", ":"))

    lead = suggestions[0] if suggestions else None
    hero_value = "--"
    hero_label = "Readiness today"
    if today is not None and today.readiness_score is not None:
        hero_value = f"{today.readiness_score:.0f}"
    elif today is not None and today.sleep_score is not None:
        hero_value = f"{today.sleep_score:.0f}"
        hero_label = "Sleep score today"

    latest_day = rows[-1].day.strftime("%A %d %B %Y") if rows else "no data yet"
    debt = analysis.sleep_debt_h
    consistency = analysis.bedtime_consistency_min
    summary_bits = [f"{analysis.days_tracked} days tracked"]
    if debt is not None:
        summary_bits.append(
            f"{abs(debt):.1f}h sleep {'debt' if debt > 0 else 'surplus'} this week"
        )
    if consistency is not None:
        summary_bits.append(f"bedtime varies ±{consistency:.0f} min")

    banner_html = ""
    if banner:
        banner_html = f'  <p class="banner">{html.escape(banner)}</p>\n'

    focus_html = ""
    if lead is not None:
        focus_html = f"""        <div class="focus-body">
          <h2>{html.escape(lead.title)}</h2>
          <p>{html.escape(lead.detail)}</p>
          <p class="do">{html.escape(lead.action)}</p>
        </div>"""

    cards = "\n".join(_suggestion_card(s) for s in suggestions[1:]) if len(suggestions) > 1 else ""
    more_section = ""
    if cards:
        more_section = f"""    <h2 class="section-title">Everything else worth knowing</h2>
    <div class="cards">
{cards}
    </div>"""

    return f"""<title>{html.escape(title)}</title>
<meta name="color-scheme" content="light dark">
<style>
{css}
</style>
<div class="wrap">
{banner_html}  <header>
    <p class="eyebrow">Oura · morning dashboard</p>
    <h1>{html.escape(latest_day)}</h1>
    <p class="sub">{html.escape(" · ".join(summary_bits))}</p>
  </header>

  <div class="focus">
    <div class="hero">
      <div class="hero-value">{hero_value}</div>
      <div class="hero-label">{html.escape(hero_label)}</div>
    </div>
{focus_html}
  </div>

  <div class="controls">
    <span class="label">Range</span>
    <div class="seg">{_range_buttons(len(rows))}</div>
  </div>

{more_section}

  <h2 class="section-title">Today at a glance</h2>
  <div class="tiles">
{_tiles_html(analysis)}
  </div>

  <h2 class="section-title">Trends</h2>
  <div class="charts">
{_chart_html(rows)}
  </div>

{_table_html(rows)}

  <footer>
    <p>Generated {date.today().isoformat()} from your Oura account. Suggestions are
    pattern observations from your own trailing data, not medical advice.</p>
    <p>Range controls and hover apply to every chart above. All values are also in the table view.</p>
  </footer>
</div>
<script>window.__OURA__ = {payload};</script>
<script>
{js}
</script>
"""


def write(
    analysis: Analysis,
    suggestions: Sequence[Suggestion],
    path: Path,
    *,
    title: str = "Oura dashboard",
    banner: str | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render(analysis, suggestions, title=title, banner=banner), encoding="utf-8"
    )
    return path
