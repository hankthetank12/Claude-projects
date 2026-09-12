"""Dashboard, brief and mail assembly."""

import json
import re
from datetime import date, timedelta

from oura_dashboard import brief, dashboard, mailer
from oura_dashboard.analysis import analyse
from oura_dashboard.metrics import DayRow
from oura_dashboard.suggestions import Suggestion, generate


def sample_rows(days=40):
    rows = []
    for index in range(days):
        row = DayRow(day=date(2026, 5, 1) + timedelta(days=index))
        row.sleep_score = 78.0
        row.readiness_score = 82.0
        row.activity_score = 75.0
        row.total_sleep_h = 7.6
        row.deep_h = 1.4
        row.rem_h = 1.7
        row.light_h = 4.5
        row.awake_h = 0.4
        row.efficiency = 92.0
        row.latency_min = 15.0
        row.avg_hrv = 54.0 + (index % 4)
        row.lowest_hr = 51.0
        row.avg_breath = 14.1
        row.temperature_deviation = 0.1
        row.steps = 9100.0
        row.stress_high_min = 40.0
        row.recovery_high_min = 140.0
        row.spo2_avg = 96.4
        row.bedtime_start_h = 23.2
        row.bedtime_end_h = 30.9
        rows.append(row)
    return rows


def built():
    result = analyse(sample_rows(), 8.0)
    return result, generate(result)


# -- dashboard ---------------------------------------------------------
def test_dashboard_is_one_self_contained_file():
    result, found = built()
    page = dashboard.render(result, found)
    assert "<title>" in page
    assert "<style>" in page and "<script>" in page
    # Nothing may be fetched from the network.
    assert "http://" not in page.replace("http://www.w3.org", "")
    assert "src=" not in page


def test_dashboard_embeds_every_day_as_json():
    result, found = built()
    page = dashboard.render(result, found)
    match = re.search(r"window\.__OURA__ = (\{.*?\});", page, re.S)
    assert match
    payload = json.loads(match.group(1))
    assert len(payload["days"]) == 40
    first = payload["days"][0]
    assert first["day"] == "2026-05-01"
    assert first["readiness_score"] == 82.0
    assert "weekday" in first


def test_dashboard_declares_both_theme_scopes():
    result, found = built()
    page = dashboard.render(result, found)
    assert "prefers-color-scheme: dark" in page
    assert '[data-theme="dark"]' in page
    assert '[data-theme="light"]' in page


def test_dashboard_includes_a_table_view_for_accessibility():
    result, found = built()
    page = dashboard.render(result, found)
    assert "table-view" in page
    assert "<table>" in page


def test_dashboard_renders_every_chart_container():
    result, found = built()
    page = dashboard.render(result, found)
    for key in ("scores", "sleepDuration", "stages", "hrv", "rhr",
                "window", "steps", "efficiency", "stress", "temperature",
                "spo2", "weekday"):
        assert f'data-chart="{key}"' in page, f"missing chart {key}"


def test_dashboard_escapes_suggestion_text():
    """Suggestion text is templated into HTML and must not inject markup."""
    result, _ = built()
    nasty = Suggestion(
        id="x", severity="info",
        title="<script>alert(1)</script>",
        detail="a & b <b>bold</b>",
        action="done",
    )
    page = dashboard.render(result, [nasty])
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    assert "a &amp; b" in page


def test_dashboard_writes_to_disk(tmp_path):
    result, found = built()
    target = dashboard.write(result, found, tmp_path / "sub" / "index.html")
    assert target.is_file()
    assert target.stat().st_size > 10_000


def test_dashboard_survives_a_single_day_of_data():
    rows = sample_rows(1)
    result = analyse(rows, 8.0)
    page = dashboard.render(result, generate(result))
    assert "<title>" in page


# -- brief -------------------------------------------------------------
def test_subject_leads_with_readiness_and_the_headline():
    result, found = built()
    subject = brief.subject(result, found)
    assert subject.startswith("Readiness 82")
    assert found[0].title in subject


def test_text_brief_lists_every_suggestion_with_its_action():
    result, found = built()
    text = brief.render_text(result, found)
    for suggestion in found:
        assert suggestion.title in text
        assert suggestion.action in text
    assert "not medical advice" in text


def test_text_brief_includes_the_dashboard_link_when_given():
    result, found = built()
    assert "https://example.com/x" in brief.render_text(
        result, found, dashboard_url="https://example.com/x"
    )
    assert "Full dashboard" not in brief.render_text(result, found)


def test_html_brief_is_inline_styled_for_email_clients():
    result, found = built()
    html_body = brief.render_html(result, found)
    assert "<style>" not in html_body       # email clients strip these
    assert 'style="' in html_body
    assert "<!doctype html>" in html_body.lower()


def test_html_brief_escapes_and_links_safely():
    result, _ = built()
    nasty = Suggestion(id="x", severity="warn", title="a <b>& c", detail="d", action="e")
    html_body = brief.render_html(result, [nasty], dashboard_url="https://e.com/?a=1&b=2")
    assert "a &lt;b&gt;&amp; c" in html_body
    assert "https://e.com/?a=1&amp;b=2" in html_body


def test_brief_handles_an_empty_history():
    result = analyse([], 8.0)
    found = generate(result)
    assert brief.subject(result, found)
    assert brief.render_text(result, found)
    assert brief.render_html(result, found)


# -- mail --------------------------------------------------------------
def test_message_is_multipart_with_text_and_html():
    message = mailer.build_message(
        subject="s", sender="a@b.c", recipient="d@e.f",
        text_body="plain", html_body="<p>rich</p>",
    )
    assert message["Subject"] == "s"
    assert message["To"] == "d@e.f"
    assert message.get_body(("plain",)).get_content().strip() == "plain"
    assert "rich" in message.get_body(("html",)).get_content()


def test_attachment_is_included(tmp_path):
    page = tmp_path / "index.html"
    page.write_text("<p>dash</p>")
    message = mailer.build_message(
        subject="s", sender="a@b.c", recipient="d@e.f",
        text_body="t", html_body="<p>h</p>", attachments=[page],
    )
    names = [part.get_filename() for part in message.iter_attachments()]
    assert "index.html" in names


def test_a_missing_attachment_is_skipped_not_fatal(tmp_path):
    message = mailer.build_message(
        subject="s", sender="a@b.c", recipient="d@e.f",
        text_body="t", attachments=[tmp_path / "gone.html"],
    )
    assert list(message.iter_attachments()) == []


def test_auth_failure_explains_the_app_password(monkeypatch):
    import smtplib

    class Boom:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, *a):
            raise smtplib.SMTPAuthenticationError(535, b"bad creds")
        def send_message(self, *a): pass

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", lambda *a, **k: Boom())
    message = mailer.build_message(
        subject="s", sender="a@b.c", recipient="d@e.f", text_body="t"
    )
    try:
        mailer.send(message, username="a@b.c", password="wrong")
    except mailer.MailError as exc:
        assert "App Password" in str(exc)
    else:
        raise AssertionError("expected MailError")


def test_banner_is_rendered_and_escaped_when_given():
    result, found = built()
    page = dashboard.render(result, found, banner="Sample data <b>only</b>")
    assert 'class="banner"' in page
    assert "Sample data &lt;b&gt;only&lt;/b&gt;" in page


def test_no_banner_element_without_a_banner():
    result, found = built()
    assert 'class="banner"' not in dashboard.render(result, found)
