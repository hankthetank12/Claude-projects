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
                "OURA_SLEEP_NEED_HOURS", "OURA_SANDBOX", "OURA_TIMEZONE",
                "OURA_CLIENT_ID", "OURA_CLIENT_SECRET", "OURA_REFRESH_TOKEN",
                "GITHUB_ACTIONS", "GITHUB_REPOSITORY", "GH_TOKEN"):
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


def test_sync_without_credentials_points_at_oauth(env):
    """Personal access tokens are deprecated, so the guidance must not suggest one."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["sync"])
    message = str(exc.value)
    assert "OURA_CLIENT_ID" in message
    assert "authorize" in message
    assert "personal-access-tokens" not in message


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


# -- OAuth in the daily job -------------------------------------------
def test_morning_in_actions_rotates_the_secret(env, monkeypatch, capsys):
    """The whole scheduled path: refresh, write the new token back, send."""
    import time as _time

    from oura_dashboard import auth, gh_secrets

    monkeypatch.setenv("OURA_CLIENT_ID", "cid")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "sec")
    monkeypatch.setenv("OURA_REFRESH_TOKEN", "rt-old")
    monkeypatch.setenv("MAIL_TO", "a@b.c")
    monkeypatch.setenv("MAIL_FROM", "d@e.f")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/repo")

    spent = {}

    def fake_refresh(*, client_id, client_secret, refresh_token):
        spent["used"] = refresh_token
        return auth.TokenSet("at-new", "rt-new", _time.time() + 86400)

    written = {}
    monkeypatch.setattr("oura_dashboard.auth.refresh_tokens", fake_refresh)
    monkeypatch.setattr(
        gh_secrets, "set_secret",
        lambda name, value, repository=None: written.update({name: value}),
    )

    tokens_seen = {}

    def fake_fetch_all(self, start, end, endpoints=None):
        tokens_seen["token"] = self.token
        return sample.generate(60)

    monkeypatch.setattr("oura_dashboard.client.OuraClient.fetch_all", fake_fetch_all)
    monkeypatch.setattr("oura_dashboard.mailer.send", lambda *a, **k: None)

    assert cli.main(["morning"]) == 0
    assert spent["used"] == "rt-old"
    assert tokens_seen["token"] == "at-new"
    assert written == {"OURA_REFRESH_TOKEN": "rt-new"}


def test_morning_goes_red_when_the_rotation_cannot_be_saved(env, monkeypatch, capsys):
    """The brief still sends, but the run must fail so the user notices."""
    import time as _time

    from oura_dashboard import auth, gh_secrets

    monkeypatch.setenv("OURA_CLIENT_ID", "cid")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "sec")
    monkeypatch.setenv("OURA_REFRESH_TOKEN", "rt-old")
    monkeypatch.setenv("MAIL_TO", "a@b.c")
    monkeypatch.setenv("MAIL_FROM", "d@e.f")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/repo")

    monkeypatch.setattr(
        "oura_dashboard.auth.refresh_tokens",
        lambda **kw: auth.TokenSet("at-new", "rt-new", _time.time() + 86400),
    )

    def refuse(name, value, repository=None):
        raise gh_secrets.SecretWriteError("GH_TOKEN is not set")

    monkeypatch.setattr(gh_secrets, "set_secret", refuse)
    monkeypatch.setattr(
        "oura_dashboard.client.OuraClient.fetch_all",
        lambda self, start, end, endpoints=None: sample.generate(60),
    )
    sent = {}
    monkeypatch.setattr(
        "oura_dashboard.mailer.send",
        lambda message, **kw: sent.update({
            "subject": message["Subject"],
            "body": message.get_body(("plain",)).get_content(),
        }),
    )

    assert cli.main(["morning"]) == 1
    assert "action needed" in sent["subject"]
    assert "GH_TOKEN is not set" in sent["body"]
    assert "GH_TOKEN" in capsys.readouterr().err


def test_a_spent_refresh_token_exits_with_reauthorize_guidance(env, monkeypatch, capsys):
    from oura_dashboard import auth

    monkeypatch.setenv("OURA_CLIENT_ID", "cid")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "sec")
    monkeypatch.setenv("OURA_REFRESH_TOKEN", "spent")

    def dead(**kwargs):
        raise auth.ReauthorizationRequired("Oura rejected the refresh token")

    monkeypatch.setattr("oura_dashboard.auth.refresh_tokens", dead)
    assert cli.main(["sync"]) == 1
    assert "refresh token" in capsys.readouterr().err


def test_a_personal_token_still_works_for_now(env, monkeypatch, capsys):
    """Existing PATs keep working even though new ones cannot be created."""
    monkeypatch.setenv("OURA_TOKEN", "pat-legacy")

    def boom(**kwargs):
        raise AssertionError("a PAT must not hit the OAuth endpoint")

    monkeypatch.setattr("oura_dashboard.auth.refresh_tokens", boom)
    seen = {}

    def fake_fetch_all(self, start, end, endpoints=None):
        seen["token"] = self.token
        return sample.generate(30)

    monkeypatch.setattr("oura_dashboard.client.OuraClient.fetch_all", fake_fetch_all)
    assert cli.main(["sync"]) == 0
    assert seen["token"] == "pat-legacy"


def test_authorize_needs_client_credentials_first(env):
    with pytest.raises(SystemExit) as exc:
        cli.main(["authorize"])
    assert "OURA_CLIENT_ID" in str(exc.value)


def test_authorize_saves_the_token_set_and_prints_the_secret(env, monkeypatch, capsys):
    import time as _time

    from oura_dashboard import auth, authorize as authorize_module

    monkeypatch.setenv("OURA_CLIENT_ID", "cid")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "sec")
    monkeypatch.setattr(
        authorize_module, "run_flow",
        lambda **kw: auth.TokenSet("at", "rt-fresh", _time.time() + 3600, "daily"),
    )
    assert cli.main(["authorize"]) == 0

    output = capsys.readouterr().out
    assert "rt-fresh" in output
    assert "OURA_REFRESH_TOKEN" in output
    assert "single use" in output

    saved = auth.TokenStore(env / "data" / ".oauth.json").load()
    assert saved is not None and saved.refresh_token == "rt-fresh"


def test_the_local_token_file_is_not_inside_the_history(env, monkeypatch):
    """Credentials must never end up in the committed history file."""
    from oura_dashboard.config import Config

    config = Config.from_env()
    assert config.token_file.name == ".oauth.json"
    assert config.token_file != config.data_dir / "history.json"


# -- the check command -------------------------------------------------
def test_check_fails_clearly_without_credentials(env, capsys):
    assert cli.main(["check"]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "OURA_CLIENT_ID" in out


def test_check_reports_every_section_when_configured(env, monkeypatch, capsys):
    monkeypatch.setenv("OURA_TOKEN", "pat")
    monkeypatch.setenv("MAIL_TO", "a@b.c")
    monkeypatch.setenv("MAIL_FROM", "d@e.f")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
    monkeypatch.setattr(
        "oura_dashboard.client.OuraClient.fetch",
        lambda self, endpoint, start=None, end=None: [{"id": "x"}],
    )
    assert cli.main(["check"]) == 0
    out = capsys.readouterr().out
    for label in ("Oura credentials", "Access token", "Endpoint daily_sleep",
                  "Email settings", "Local history"):
        assert label in out
    assert "FAIL" not in out
    assert "Everything checks out" in out


def test_check_flags_missing_mail_settings(env, monkeypatch, capsys):
    monkeypatch.setenv("OURA_TOKEN", "pat")
    monkeypatch.setattr(
        "oura_dashboard.client.OuraClient.fetch",
        lambda self, endpoint, start=None, end=None: [],
    )
    assert cli.main(["check"]) == 1
    out = capsys.readouterr().out
    assert "GMAIL_APP_PASSWORD" in out


def test_check_can_send_a_test_email(env, monkeypatch, capsys):
    monkeypatch.setenv("OURA_TOKEN", "pat")
    monkeypatch.setenv("MAIL_TO", "a@b.c")
    monkeypatch.setenv("MAIL_FROM", "d@e.f")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
    monkeypatch.setattr(
        "oura_dashboard.client.OuraClient.fetch",
        lambda self, endpoint, start=None, end=None: [{"id": "x"}],
    )
    sent = {}
    monkeypatch.setattr(
        "oura_dashboard.mailer.send",
        lambda message, **kw: sent.update({"subject": message["Subject"]}),
    )
    assert cli.main(["check", "--email"]) == 0
    assert sent["subject"] == "Oura dashboard test"
    assert "Test email" in capsys.readouterr().out


def test_check_surfaces_a_rejected_app_password(env, monkeypatch, capsys):
    """Better to learn the password is wrong now than at 7am tomorrow."""
    from oura_dashboard import mailer

    monkeypatch.setenv("OURA_TOKEN", "pat")
    monkeypatch.setenv("MAIL_TO", "a@b.c")
    monkeypatch.setenv("MAIL_FROM", "d@e.f")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "wrong")
    monkeypatch.setattr(
        "oura_dashboard.client.OuraClient.fetch",
        lambda self, endpoint, start=None, end=None: [{"id": "x"}],
    )

    def refuse(message, **kwargs):
        raise mailer.MailError("Gmail rejected the login")

    monkeypatch.setattr("oura_dashboard.mailer.send", refuse)
    assert cli.main(["check", "--email"]) == 1
    assert "Gmail rejected the login" in capsys.readouterr().out


def test_check_reports_an_unreachable_api(env, monkeypatch, capsys):
    from oura_dashboard import client as client_module

    monkeypatch.setenv("OURA_TOKEN", "pat")

    def boom(self, endpoint, start=None, end=None):
        raise client_module.OuraError("403 forbidden")

    monkeypatch.setattr("oura_dashboard.client.OuraClient.fetch", boom)
    assert cli.main(["check"]) == 1
    out = capsys.readouterr().out
    assert "403 forbidden" in out
    assert "grant every scope" in out
