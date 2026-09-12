"""CLI wiring and config loading."""

import json
from datetime import date

import pytest

from oura_dashboard import cli, metrics, sample, store
from oura_dashboard.config import Config


@pytest.fixture
def env(monkeypatch, tmp_path):
    """A clean environment pointing data and output at a temp directory."""
    for key in ("OURA_TOKEN", "MAIL_TO", "MAIL_FROM", "GMAIL_APP_PASSWORD",
                "OURA_SLEEP_NEED_HOURS", "OURA_SANDBOX", "OURA_TIMEZONE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("oura_dashboard.config.load_dotenv", lambda path=None: None)
    monkeypatch.setenv("OURA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OURA_OUT_DIR", str(tmp_path / "out"))
    return tmp_path


# -- config ------------------------------------------------------------
def test_config_defaults(env):
    config = Config.from_env()
    assert config.token is None
    assert config.sleep_need_hours == 8.0
    assert config.can_send_mail is False


def test_config_reads_the_environment(env, monkeypatch):
    monkeypatch.setenv("OURA_TOKEN", "abc")
    monkeypatch.setenv("MAIL_TO", "a@b.c")
    monkeypatch.setenv("MAIL_FROM", "d@e.f")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
    monkeypatch.setenv("OURA_SLEEP_NEED_HOURS", "7.5")
    config = Config.from_env()
    assert config.token == "abc"
    assert config.sleep_need_hours == 7.5
    assert config.can_send_mail is True


def test_config_ignores_a_nonsense_sleep_need(env, monkeypatch):
    monkeypatch.setenv("OURA_SLEEP_NEED_HOURS", "eight")
    assert Config.from_env().sleep_need_hours == 8.0


def test_dotenv_does_not_override_real_env_vars(tmp_path, monkeypatch):
    from oura_dashboard.config import load_dotenv

    path = tmp_path / ".env"
    path.write_text('OURA_TOKEN="from-file"\nMAIL_TO=file@x.y\n# comment\n\n')
    monkeypatch.setenv("OURA_TOKEN", "from-env")
    monkeypatch.delenv("MAIL_TO", raising=False)
    load_dotenv(path)
    import os
    assert os.environ["OURA_TOKEN"] == "from-env"
    assert os.environ["MAIL_TO"] == "file@x.y"


# -- commands ----------------------------------------------------------
def test_demo_builds_a_dashboard_and_a_brief(env, capsys):
    assert cli.main(["demo", "--days", "45"]) == 0
    assert (env / "out" / "index.html").is_file()
    assert (env / "out" / "brief.html").is_file()
    assert "morning brief" in capsys.readouterr().out


def test_sync_without_a_token_exits_with_guidance(env):
    with pytest.raises(SystemExit) as exc:
        cli.main(["sync"])
    assert "OURA_TOKEN" in str(exc.value)


def test_build_without_history_tells_you_to_sync(env):
    with pytest.raises(SystemExit) as exc:
        cli.main(["build"])
    assert "sync" in str(exc.value)


def test_sync_then_build_then_brief(env, monkeypatch, capsys):
    """The real daily path, with the API faked at the client boundary."""
    monkeypatch.setenv("OURA_TOKEN", "tok")
    documents = sample.generate(60)

    def fake_fetch_all(self, start, end, endpoints=None):
        return documents

    monkeypatch.setattr("oura_dashboard.client.OuraClient.fetch_all", fake_fetch_all)

    assert cli.main(["sync", "--days", "60"]) == 0
    history_file = env / "data" / "history.json"
    assert history_file.is_file()
    saved = json.loads(history_file.read_text())
    assert saved["schema_version"] == 1
    assert "daily_sleep" in saved["endpoints"]

    assert cli.main(["build"]) == 0
    assert (env / "out" / "index.html").is_file()

    capsys.readouterr()
    assert cli.main(["brief"]) == 0
    output = capsys.readouterr().out
    assert "Subject:" in output
    assert "not medical advice" in output


def test_send_without_credentials_prints_instead(env, monkeypatch, capsys):
    monkeypatch.setenv("OURA_TOKEN", "tok")
    monkeypatch.setattr(
        "oura_dashboard.client.OuraClient.fetch_all",
        lambda self, start, end, endpoints=None: sample.generate(40),
    )
    cli.main(["sync"])
    capsys.readouterr()

    assert cli.main(["send"]) == 0
    captured = capsys.readouterr()
    assert "Subject:" in captured.out
    assert "GMAIL_APP_PASSWORD" in captured.err


def test_send_dry_run_never_touches_smtp(env, monkeypatch, capsys):
    monkeypatch.setenv("OURA_TOKEN", "tok")
    monkeypatch.setenv("MAIL_TO", "a@b.c")
    monkeypatch.setenv("MAIL_FROM", "d@e.f")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
    monkeypatch.setattr(
        "oura_dashboard.client.OuraClient.fetch_all",
        lambda self, start, end, endpoints=None: sample.generate(40),
    )

    def explode(*args, **kwargs):
        raise AssertionError("dry run must not send")

    monkeypatch.setattr("oura_dashboard.mailer.send", explode)
    cli.main(["sync"])
    capsys.readouterr()
    assert cli.main(["send", "--dry-run"]) == 0
    assert "Subject:" in capsys.readouterr().out


def test_morning_runs_the_whole_job(env, monkeypatch, capsys):
    monkeypatch.setenv("OURA_TOKEN", "tok")
    monkeypatch.setenv("MAIL_TO", "a@b.c")
    monkeypatch.setenv("MAIL_FROM", "d@e.f")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
    monkeypatch.setattr(
        "oura_dashboard.client.OuraClient.fetch_all",
        lambda self, start, end, endpoints=None: sample.generate(60),
    )
    sent = {}

    def capture(message, *, username, password, host=None, port=None):
        sent["to"] = message["To"]
        sent["subject"] = message["Subject"]
        sent["attachments"] = [p.get_filename() for p in message.iter_attachments()]

    monkeypatch.setattr("oura_dashboard.mailer.send", capture)
    assert cli.main(["morning", "--url", "https://x.y/", "--attach-dashboard"]) == 0
    assert sent["to"] == "a@b.c"
    assert "Readiness" in sent["subject"]
    assert "index.html" in sent["attachments"]


def test_api_errors_become_a_clean_exit_code(env, monkeypatch, capsys):
    from oura_dashboard import client as client_module

    monkeypatch.setenv("OURA_TOKEN", "tok")

    def boom(self, start, end, endpoints=None):
        raise client_module.OuraAuthError("token rejected")

    monkeypatch.setattr("oura_dashboard.client.OuraClient.fetch_all", boom)
    assert cli.main(["sync"]) == 1
    assert "token rejected" in capsys.readouterr().err


# -- sample data -------------------------------------------------------
def test_sample_data_is_deterministic_and_well_shaped():
    first = sample.generate(30, end=date(2026, 9, 1), seed=3)
    second = sample.generate(30, end=date(2026, 9, 1), seed=3)
    assert first == second

    history = store.History()
    history.merge(first)
    rows = metrics.build_rows(history)
    assert len(rows) == 30
    assert rows[-1].day == date(2026, 9, 1)
    for row in rows:
        assert row.total_sleep_h and 3 < row.total_sleep_h < 12
        assert row.sleep_score and 0 < row.sleep_score <= 100
        assert row.steps is not None and row.steps > 0
