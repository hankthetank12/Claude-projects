"""The localhost consent flow and the Actions secret write-back."""

import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from oura_dashboard import auth, authorize, gh_secrets


def drive_callback(url_holder, query, results):
    """Hit the local callback once the server is listening."""
    for _ in range(100):
        if url_holder.get("ready"):
            break
        time.sleep(0.02)
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{url_holder['port']}/callback?{query}", timeout=5
        ) as response:
            results["status"] = response.status
            results["body"] = response.read().decode()
    except urllib.error.HTTPError as exc:
        results["status"] = exc.code
        results["body"] = exc.read().decode()


@pytest.fixture
def port():
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run_flow_against(monkeypatch, port, make_query, exchange=None):
    """Run the flow with the browser stubbed and a scripted callback."""
    holder = {"port": port}
    results: dict[str, object] = {}
    captured = {}

    def fake_open(url):
        holder["ready"] = True
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        captured.update(params)
        threading.Thread(
            target=drive_callback,
            args=(holder, make_query(params), results),
            daemon=True,
        ).start()
        return True

    monkeypatch.setattr(authorize.webbrowser, "open", fake_open)
    monkeypatch.setattr(
        authorize, "exchange_code",
        exchange or (lambda **kw: auth.TokenSet("at", "rt", time.time() + 3600)),
    )
    return holder, results, captured


def test_a_successful_redirect_yields_tokens(monkeypatch, port):
    holder, results, captured = run_flow_against(
        monkeypatch, port,
        lambda params: urllib.parse.urlencode(
            {"code": "the-code", "state": params["state"]}
        ),
    )
    tokens = authorize.run_flow(
        client_id="cid", client_secret="sec", port=port, timeout=15
    )
    assert tokens.access_token == "at"
    assert tokens.refresh_token == "rt"
    assert captured["client_id"] == "cid"
    assert captured["redirect_uri"] == f"http://localhost:{port}/callback"
    assert results["status"] == 200
    assert "close this tab" in str(results["body"])


def test_the_code_is_exchanged_with_the_matching_redirect_uri(monkeypatch, port):
    seen = {}

    def exchange(**kwargs):
        seen.update(kwargs)
        return auth.TokenSet("at", "rt")

    run_flow_against(
        monkeypatch, port,
        lambda params: urllib.parse.urlencode({"code": "c1", "state": params["state"]}),
        exchange=exchange,
    )
    authorize.run_flow(client_id="cid", client_secret="sec", port=port, timeout=15)
    assert seen["code"] == "c1"
    # Oura matches redirect_uri exactly, so it must be identical here.
    assert seen["redirect_uri"] == f"http://localhost:{port}/callback"


def test_a_mismatched_state_is_rejected(monkeypatch, port):
    """Protects against a code injected through the user's browser."""
    holder, results, _ = run_flow_against(
        monkeypatch, port,
        lambda params: urllib.parse.urlencode({"code": "c", "state": "not-the-state"}),
    )
    with pytest.raises(auth.OAuthError) as exc:
        authorize.run_flow(client_id="cid", client_secret="sec", port=port, timeout=15)
    assert "state mismatch" in str(exc.value).lower()
    assert results["status"] == 400


def test_a_declined_consent_reports_the_reason(monkeypatch, port):
    run_flow_against(
        monkeypatch, port,
        lambda params: urllib.parse.urlencode(
            {"error": "access_denied", "error_description": "User said no",
             "state": params["state"]}
        ),
    )
    with pytest.raises(auth.OAuthError) as exc:
        authorize.run_flow(client_id="cid", client_secret="sec", port=port, timeout=15)
    assert "User said no" in str(exc.value)


def test_a_redirect_without_a_code_is_an_error(monkeypatch, port):
    run_flow_against(
        monkeypatch, port,
        lambda params: urllib.parse.urlencode({"state": params["state"]}),
    )
    with pytest.raises(auth.OAuthError) as exc:
        authorize.run_flow(client_id="cid", client_secret="sec", port=port, timeout=15)
    assert "authorization code" in str(exc.value)


def test_the_flow_times_out_rather_than_hanging(monkeypatch, port):
    monkeypatch.setattr(authorize.webbrowser, "open", lambda url: True)
    with pytest.raises(auth.OAuthError) as exc:
        authorize.run_flow(
            client_id="cid", client_secret="sec", port=port, timeout=0.3
        )
    assert "Timed out" in str(exc.value)


def test_a_busy_port_explains_itself(monkeypatch, port):
    import socket

    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)
    try:
        with pytest.raises(auth.OAuthError) as exc:
            authorize.run_flow(
                client_id="cid", client_secret="sec", port=port, timeout=2
            )
        assert str(port) in str(exc.value)
    finally:
        blocker.close()


def test_the_port_is_released_after_the_flow(monkeypatch, port):
    """A leaked listener would make the next authorize attempt fail."""
    run_flow_against(
        monkeypatch, port,
        lambda params: urllib.parse.urlencode({"code": "c", "state": params["state"]}),
    )
    authorize.run_flow(client_id="cid", client_secret="sec", port=port, timeout=15)

    import socket

    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))  # must not raise


# -- secret write-back -------------------------------------------------
def test_in_github_actions_reads_the_env(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert gh_secrets.in_github_actions() is False
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert gh_secrets.in_github_actions() is True


def test_set_secret_passes_the_value_on_stdin(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/repo")
    monkeypatch.setenv("GH_TOKEN", "ghp_x")
    monkeypatch.setattr(gh_secrets.shutil, "which", lambda name: "/usr/bin/gh")
    calls = {}

    def fake_run(args, **kwargs):
        calls["args"] = args
        calls["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(gh_secrets.subprocess, "run", fake_run)
    gh_secrets.set_secret("OURA_REFRESH_TOKEN", "rt-new")

    assert calls["args"][:3] == ["gh", "secret", "set"]
    assert "me/repo" in calls["args"]
    # The token must not land in argv, where a process list would expose it.
    assert "rt-new" not in calls["args"]
    assert calls["input"] == "rt-new"


def test_set_secret_without_a_pat_explains_the_consequence(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/repo")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(gh_secrets.SecretWriteError) as exc:
        gh_secrets.set_secret("OURA_REFRESH_TOKEN", "rt")
    assert "GH_TOKEN" in str(exc.value)
    assert "next scheduled run will fail" in str(exc.value)


def test_set_secret_without_a_repository_fails(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setenv("GH_TOKEN", "x")
    with pytest.raises(gh_secrets.SecretWriteError):
        gh_secrets.set_secret("OURA_REFRESH_TOKEN", "rt")


def test_a_failing_gh_command_surfaces_its_output(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/repo")
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setattr(gh_secrets.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(
        gh_secrets.subprocess, "run",
        lambda args, **kw: subprocess.CompletedProcess(args, 1, "", "HTTP 403 forbidden"),
    )
    with pytest.raises(gh_secrets.SecretWriteError) as exc:
        gh_secrets.set_secret("OURA_REFRESH_TOKEN", "rt")
    assert "403" in str(exc.value)


def test_a_missing_gh_binary_is_reported(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/repo")
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setattr(gh_secrets.shutil, "which", lambda name: None)
    with pytest.raises(gh_secrets.SecretWriteError) as exc:
        gh_secrets.set_secret("OURA_REFRESH_TOKEN", "rt")
    assert "gh" in str(exc.value)
