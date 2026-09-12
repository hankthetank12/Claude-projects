"""OAuth2: URL building, exchanges, single-use rotation, and persistence."""

import io
import json
import time
import urllib.error
import urllib.parse

import pytest

from oura_dashboard import auth


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_token_endpoint(monkeypatch, payload, status=None, body=None):
    """Patch urlopen; returns a list that captures the posted form fields."""
    posted = []

    def fake_urlopen(request, timeout=None):
        posted.append(dict(urllib.parse.parse_qsl(request.data.decode())))
        if status is not None:
            raise urllib.error.HTTPError(
                url=auth.TOKEN_URL, code=status, msg="err", hdrs=None,
                fp=io.BytesIO(json.dumps(body or {}).encode()),
            )
        return FakeResponse(json.dumps(payload).encode())

    monkeypatch.setattr(auth.urllib.request, "urlopen", fake_urlopen)
    return posted


# -- authorize URL -----------------------------------------------------
def test_authorize_url_carries_the_required_parameters():
    url, state = auth.authorize_url("cid", "http://localhost:8731/callback")
    parsed = urllib.parse.urlparse(url)
    params = dict(urllib.parse.parse_qsl(parsed.query))
    assert url.startswith(auth.AUTHORIZE_URL)
    assert params["response_type"] == "code"
    assert params["client_id"] == "cid"
    assert params["redirect_uri"] == "http://localhost:8731/callback"
    assert params["state"] == state and len(state) > 16
    assert "daily" in params["scope"] and "spo2Daily" in params["scope"]


def test_authorize_url_state_is_random_each_time():
    _, first = auth.authorize_url("cid", "http://x/cb")
    _, second = auth.authorize_url("cid", "http://x/cb")
    assert first != second


def test_default_scopes_cover_every_endpoint_group():
    # `daily` covers the daily_* documents; the others each need their own.
    for scope in ("personal", "daily", "heartrate", "workout", "tag", "session", "spo2Daily"):
        assert scope in auth.DEFAULT_SCOPES


# -- exchanges ---------------------------------------------------------
def test_exchange_code_posts_the_authorization_code_grant(monkeypatch):
    posted = fake_token_endpoint(monkeypatch, {
        "access_token": "at1", "refresh_token": "rt1",
        "expires_in": 86400, "token_type": "bearer", "scope": "daily",
    })
    tokens = auth.exchange_code(
        client_id="cid", client_secret="sec", code="abc",
        redirect_uri="http://localhost:8731/callback",
    )
    assert posted[0]["grant_type"] == "authorization_code"
    assert posted[0]["code"] == "abc"
    assert posted[0]["client_id"] == "cid"
    assert posted[0]["client_secret"] == "sec"
    assert tokens.access_token == "at1"
    assert tokens.refresh_token == "rt1"
    assert tokens.expires_at is not None and tokens.expires_at > time.time()


def test_refresh_posts_the_refresh_token_grant(monkeypatch):
    posted = fake_token_endpoint(monkeypatch, {
        "access_token": "at2", "refresh_token": "rt2", "expires_in": 86400,
    })
    tokens = auth.refresh_tokens(client_id="cid", client_secret="sec", refresh_token="rt1")
    assert posted[0]["grant_type"] == "refresh_token"
    assert posted[0]["refresh_token"] == "rt1"
    assert tokens.refresh_token == "rt2"


def test_refresh_keeps_the_old_token_if_none_comes_back(monkeypatch):
    """Losing the chain would force a manual re-authorize, so never drop it."""
    fake_token_endpoint(monkeypatch, {"access_token": "at", "expires_in": 3600})
    tokens = auth.refresh_tokens(client_id="c", client_secret="s", refresh_token="rt-old")
    assert tokens.refresh_token == "rt-old"


def test_a_response_without_an_access_token_is_an_error(monkeypatch):
    fake_token_endpoint(monkeypatch, {"token_type": "bearer"})
    with pytest.raises(auth.OAuthError):
        auth.refresh_tokens(client_id="c", client_secret="s", refresh_token="r")


def test_invalid_client_names_the_credentials(monkeypatch):
    fake_token_endpoint(monkeypatch, None, status=400, body={
        "error": "invalid_client", "error_description": "Invalid client_id."
    })
    with pytest.raises(auth.OAuthError) as exc:
        auth.refresh_tokens(client_id="c", client_secret="s", refresh_token="r")
    assert "OURA_CLIENT_ID" in str(exc.value)
    assert not isinstance(exc.value, auth.ReauthorizationRequired)


def test_invalid_grant_demands_reauthorization(monkeypatch):
    """A spent refresh token cannot be recovered in code; say so plainly."""
    fake_token_endpoint(monkeypatch, None, status=400, body={
        "error": "invalid_grant", "error_description": "Invalid refresh token."
    })
    with pytest.raises(auth.ReauthorizationRequired) as exc:
        auth.refresh_tokens(client_id="c", client_secret="s", refresh_token="spent")
    assert "single use" in str(exc.value)
    assert "authorize" in str(exc.value)


def test_network_failure_is_wrapped(monkeypatch):
    def boom(request, timeout=None):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(auth.urllib.request, "urlopen", boom)
    with pytest.raises(auth.OAuthError):
        auth.refresh_tokens(client_id="c", client_secret="s", refresh_token="r")


# -- TokenSet ----------------------------------------------------------
def test_expiry_uses_a_margin():
    assert auth.TokenSet("at", expires_at=time.time() + 3600).expired is False
    assert auth.TokenSet("at", expires_at=time.time() + 5).expired is True
    assert auth.TokenSet("at", expires_at=time.time() - 1).expired is True


def test_a_token_without_an_expiry_is_never_considered_expired():
    assert auth.TokenSet("at").expired is False


def test_token_set_round_trips_through_a_dict():
    original = auth.TokenSet("at", "rt", 123.0, "daily", "bearer")
    assert auth.TokenSet.from_dict(original.to_dict()) == original


# -- TokenStore --------------------------------------------------------
def test_store_round_trip_and_permissions(tmp_path):
    path = tmp_path / "sub" / ".oauth.json"
    store = auth.TokenStore(path)
    store.save(auth.TokenSet("at", "rt", time.time() + 60))

    loaded = store.load()
    assert loaded is not None and loaded.refresh_token == "rt"
    # Live credentials: owner-only.
    assert path.stat().st_mode & 0o077 == 0
    assert not list(path.parent.glob("*.tmp"))


def test_store_returns_none_when_absent_or_corrupt(tmp_path):
    assert auth.TokenStore(tmp_path / "nope.json").load() is None
    bad = tmp_path / "bad.json"
    bad.write_text("{broken")
    assert auth.TokenStore(bad).load() is None


def test_store_ignores_an_empty_token_set(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"access_token": "", "refresh_token": None}))
    assert auth.TokenStore(path).load() is None


# -- Credentials resolution -------------------------------------------
def test_personal_token_short_circuits_everything(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("must not call the token endpoint")

    monkeypatch.setattr(auth, "refresh_tokens", boom)
    credentials = auth.Credentials(personal_token="pat-123")
    assert credentials.access_token() == "pat-123"


def test_missing_everything_asks_for_registration():
    with pytest.raises(auth.ReauthorizationRequired) as exc:
        auth.Credentials().access_token()
    assert "oauth/applications" in str(exc.value)


def test_client_credentials_without_a_refresh_token_ask_for_authorize(tmp_path):
    credentials = auth.Credentials(
        client_id="c", client_secret="s",
        store=auth.TokenStore(tmp_path / ".oauth.json"),
    )
    with pytest.raises(auth.ReauthorizationRequired) as exc:
        credentials.access_token()
    assert "authorize" in str(exc.value)


def test_a_valid_cached_access_token_avoids_spending_the_refresh_token(tmp_path, monkeypatch):
    """Refresh tokens are single use, so don't burn one we don't need."""
    store = auth.TokenStore(tmp_path / ".oauth.json")
    store.save(auth.TokenSet("cached-at", "rt", time.time() + 7200))

    def boom(*args, **kwargs):
        raise AssertionError("should not refresh while the token is valid")

    monkeypatch.setattr(auth, "refresh_tokens", boom)
    credentials = auth.Credentials(client_id="c", client_secret="s", store=store)
    assert credentials.access_token() == "cached-at"


def test_an_expired_cached_token_triggers_a_refresh(tmp_path, monkeypatch):
    store = auth.TokenStore(tmp_path / ".oauth.json")
    store.save(auth.TokenSet("old-at", "rt-old", time.time() - 10))
    monkeypatch.setattr(
        auth, "refresh_tokens",
        lambda **kw: auth.TokenSet("new-at", "rt-new", time.time() + 3600),
    )
    credentials = auth.Credentials(client_id="c", client_secret="s", store=store)
    assert credentials.access_token() == "new-at"
    # The rotation must be on disk, or the next run has a dead token.
    assert store.load().refresh_token == "rt-new"


def test_the_env_refresh_token_wins_over_the_cached_one(tmp_path, monkeypatch):
    """In Actions the secret is the source of truth for the current token."""
    store = auth.TokenStore(tmp_path / ".oauth.json")
    store.save(auth.TokenSet("", "rt-stale", None))
    seen = {}

    def capture(**kwargs):
        seen.update(kwargs)
        return auth.TokenSet("at", "rt-next", time.time() + 3600)

    monkeypatch.setattr(auth, "refresh_tokens", capture)
    auth.Credentials(
        client_id="c", client_secret="s", refresh_token="rt-from-env", store=store
    ).access_token()
    assert seen["refresh_token"] == "rt-from-env"


def test_on_rotate_receives_the_replacement(tmp_path, monkeypatch):
    monkeypatch.setattr(
        auth, "refresh_tokens",
        lambda **kw: auth.TokenSet("at", "rt-new", time.time() + 3600),
    )
    rotated = []
    credentials = auth.Credentials(
        client_id="c", client_secret="s", refresh_token="rt-old",
        store=auth.TokenStore(tmp_path / ".oauth.json"),
        on_rotate=lambda tokens: rotated.append(tokens.refresh_token),
    )
    credentials.access_token()
    assert rotated == ["rt-new"]
    assert credentials.notices == []


def test_a_failed_rotation_becomes_a_notice_not_a_crash(tmp_path, monkeypatch):
    """The access token still works today; the user must hear about tomorrow."""
    monkeypatch.setattr(
        auth, "refresh_tokens",
        lambda **kw: auth.TokenSet("at", "rt-new", time.time() + 3600),
    )

    def failing(tokens):
        raise RuntimeError("could not write the secret")

    credentials = auth.Credentials(
        client_id="c", client_secret="s", refresh_token="rt-old",
        store=auth.TokenStore(tmp_path / ".oauth.json"),
        on_rotate=failing,
    )
    assert credentials.access_token() == "at"
    assert credentials.notices == ["could not write the secret"]
