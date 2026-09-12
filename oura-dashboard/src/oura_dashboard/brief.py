"""The morning brief: the same suggestions as plain text and as email HTML.

Email clients strip external CSS and most modern layout, so the HTML version
uses inline styles and a table-free, single-column structure.
"""

from __future__ import annotations

import html
from datetime import date
from typing import Sequence

from .analysis import Analysis
from .suggestions import Suggestion

ACCENT = {
    "critical": "#d03b3b",
    "warn": "#ec835a",
    "info": "#2a78d6",
    "win": "#0ca30c",
}
SEVERITY_WORD = {
    "critical": "Act today",
    "warn": "Worth noting",
    "info": "Insight",
    "win": "Win",
}


def subject(analysis: Analysis, suggestions: Sequence[Suggestion]) -> str:
    """A subject line that says something before the mail is even opened."""
    today = analysis.today
    score = today.readiness_score if today else None
    lead = suggestions[0].title if suggestions else "Your Oura brief"
    prefix = f"Readiness {score:.0f}" if score is not None else "Oura brief"
    return f"{prefix} — {lead}"


def subject_with_notices(
    analysis: Analysis, suggestions: Sequence[Suggestion], notices: Sequence[str]
) -> str:
    """Same subject, flagged when the run needs the user to intervene."""
    base = subject(analysis, suggestions)
    return f"[action needed] {base}" if notices else base


# The email stat row is only ~600px wide, so it uses abbreviated labels.
SHORT_LABELS = {
    "Sleep score": "Sleep",
    "Time asleep": "Asleep",
    "Avg HRV": "HRV",
    "Resting HR": "RHR",
}


def _headline_stats(analysis: Analysis) -> list[tuple[str, str]]:
    today = analysis.today
    if today is None:
        return []

    def fmt_hours(value: float | None) -> str:
        if value is None:
            return "--"
        total = int(round(value * 60))
        return f"{total // 60}h {total % 60:02d}m"

    stats: list[tuple[str, str]] = []
    if today.readiness_score is not None:
        stats.append(("Readiness", f"{today.readiness_score:.0f}"))
    if today.sleep_score is not None:
        stats.append(("Sleep score", f"{today.sleep_score:.0f}"))
    if today.total_sleep_h is not None:
        stats.append(("Time asleep", fmt_hours(today.total_sleep_h)))
    if today.avg_hrv is not None:
        stats.append(("Avg HRV", f"{today.avg_hrv:.0f} ms"))
    if today.lowest_hr is not None:
        stats.append(("Resting HR", f"{today.lowest_hr:.0f} bpm"))
    if today.activity_score is not None:
        stats.append(("Activity", f"{today.activity_score:.0f}"))
    if today.steps is not None:
        stats.append(("Steps", f"{today.steps:,.0f}"))
    return stats


def render_text(
    analysis: Analysis,
    suggestions: Sequence[Suggestion],
    *,
    dashboard_url: str | None = None,
    notices: Sequence[str] = (),
) -> str:
    lines: list[str] = []
    day = analysis.today.day if analysis.today else date.today()
    lines.append(f"Your Oura morning brief — {day.strftime('%A %d %B %Y')}")
    lines.append("=" * 52)
    lines.append("")

    for notice in notices:
        lines.append(f"!! NEEDS ATTENTION: {notice}")
    if notices:
        lines.append("")

    stats = _headline_stats(analysis)
    if stats:
        lines.append("  ".join(f"{name}: {value}" for name, value in stats))
        lines.append("")

    for index, suggestion in enumerate(suggestions, start=1):
        tag = SEVERITY_WORD.get(suggestion.severity, suggestion.severity)
        lines.append(f"{index}. [{tag}] {suggestion.title}")
        lines.append(f"   {suggestion.detail}")
        if suggestion.action:
            lines.append(f"   -> {suggestion.action}")
        lines.append("")

    if analysis.sleep_debt_h is not None:
        word = "debt" if analysis.sleep_debt_h > 0 else "surplus"
        lines.append(
            f"7-day sleep {word}: {abs(analysis.sleep_debt_h):.1f}h "
            f"(target {analysis.sleep_need_h:.1f}h a night)"
        )
    if analysis.bedtime_consistency_min is not None:
        lines.append(
            f"Bedtime consistency: ±{analysis.bedtime_consistency_min:.0f} minutes over 28 days"
        )
    lines.append(f"Days tracked: {analysis.days_tracked}")

    if dashboard_url:
        lines.append("")
        lines.append(f"Full dashboard: {dashboard_url}")

    lines.append("")
    lines.append(
        "These are pattern observations from your own trailing Oura data, "
        "not medical advice."
    )
    return "\n".join(lines)


def render_html(
    analysis: Analysis,
    suggestions: Sequence[Suggestion],
    *,
    dashboard_url: str | None = None,
    notices: Sequence[str] = (),
) -> str:
    day = analysis.today.day if analysis.today else date.today()
    stats = _headline_stats(analysis)

    stat_cells = "".join(
        f"""<td style="padding:0 16px 0 0;vertical-align:top;white-space:nowrap">
             <div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#898781;white-space:nowrap">{html.escape(SHORT_LABELS.get(name, name))}</div>
             <div style="font-size:20px;font-weight:600;color:#0b0b0b;margin-top:2px;white-space:nowrap">{html.escape(value)}</div>
           </td>"""
        for name, value in stats
    )
    stats_block = (
        f"""<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 24px">
          <tr>{stat_cells}</tr>
        </table>"""
        if stats
        else ""
    )

    notice_block = "".join(
        f"""<div style="border:1px solid #d03b3b;border-left-width:3px;border-radius:8px;
                    padding:12px 14px;margin:0 0 16px;background:#fcf4f4">
          <div style="font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:#d03b3b;margin-bottom:4px">Needs attention</div>
          <p style="margin:0;font-size:13px;color:#0b0b0b">{html.escape(notice)}</p>
        </div>"""
        for notice in notices
    )

    blocks: list[str] = []
    for suggestion in suggestions:
        accent = ACCENT.get(suggestion.severity, "#898781")
        word = SEVERITY_WORD.get(suggestion.severity, suggestion.severity)
        action = (
            f'<p style="margin:0;font-size:14px;color:#0b0b0b">{html.escape(suggestion.action)}</p>'
            if suggestion.action
            else ""
        )
        blocks.append(
            f"""<div style="border-left:3px solid {accent};padding:2px 0 2px 14px;margin:0 0 20px">
              <div style="font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:{accent};margin-bottom:4px">{html.escape(word)}</div>
              <h2 style="font-size:16px;line-height:1.35;margin:0 0 6px;color:#0b0b0b;font-weight:600">{html.escape(suggestion.title)}</h2>
              <p style="margin:0 0 6px;font-size:14px;color:#52514e">{html.escape(suggestion.detail)}</p>
              {action}
            </div>"""
        )

    footer_bits: list[str] = []
    if analysis.sleep_debt_h is not None:
        word = "debt" if analysis.sleep_debt_h > 0 else "surplus"
        footer_bits.append(f"7-day sleep {word} {abs(analysis.sleep_debt_h):.1f}h")
    if analysis.bedtime_consistency_min is not None:
        footer_bits.append(f"bedtime ±{analysis.bedtime_consistency_min:.0f} min")
    footer_bits.append(f"{analysis.days_tracked} days tracked")

    link = ""
    if dashboard_url:
        link = f"""<p style="margin:0 0 10px">
          <a href="{html.escape(dashboard_url, quote=True)}"
             style="display:inline-block;background:#2a78d6;color:#ffffff;text-decoration:none;
                    font-size:14px;font-weight:600;padding:10px 18px;border-radius:8px">
            Open the full dashboard</a>
        </p>"""

    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Oura morning brief</title></head>
<body style="margin:0;padding:0;background:#f9f9f7">
  <div style="max-width:600px;margin:0 auto;padding:28px 20px 40px;
              font-family:system-ui,-apple-system,'Segoe UI',sans-serif;
              background:#fcfcfb;color:#0b0b0b">
    <p style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#898781;margin:0 0 6px">
      Oura · morning brief</p>
    <h1 style="font-size:22px;line-height:1.25;margin:0 0 22px;font-weight:600">
      {html.escape(day.strftime("%A %d %B %Y"))}</h1>

    {notice_block}
    {stats_block}
    {"".join(blocks)}
    {link}
    <p style="margin:18px 0 0;font-size:12px;color:#898781;border-top:1px solid #e1e0d9;padding-top:14px">
      {html.escape(" · ".join(footer_bits))}</p>
    <p style="margin:8px 0 0;font-size:12px;color:#898781">
      Pattern observations from your own trailing Oura data, not medical advice.</p>
  </div>
</body>
</html>
"""
