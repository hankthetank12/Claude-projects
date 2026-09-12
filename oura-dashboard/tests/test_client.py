"""Client tests: pagination, retries, and error translation, with no network."""

import json
import urllib.error
import io
from datetime import date

import pytest

from oura_dashboard import client


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def http_error(code, body=b'{"detail":"nope"}'):
    return urllib.error.HTTPError(
        url="https://api.ouraring.com/x", code=code, msg="err",
        hdrs=None, fp=io.BytesIO(body),
    )


def make_client(monkeypatch, responses, sleeps=None):
    """Patch urlopen to serve a queue of responses/exceptions in order."""
    calls = []
    queue = list(responses)

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(json.dumps(item).encode())

    monkeypatch.setattr(client.urllib.request, "urlopen", fake_urlopen)
    recorded = sleeps if sleeps is not None else []
    api = client.OuraClient("tok", sleep=lambda s: recorded.append(s))
    return api, calls


def test_requires_a_token():
    with pytest.raises(client.OuraAuthError):
        client.OuraClient("")


def test_sends_bearer_header_and_date_params(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        return FakeResponse(json.dumps({"data": [], "next_token": None}).encode())

    monkeypatch.setattr(client.urllib.request, "urlopen", fake_urlopen)
    api = client.OuraClient("secret-token")
    api.fetch("daily_sleep", date(2026, 9, 1), date(2026, 9, 5))

    assert captured["auth"] == "Bearer secret-token"
    assert "start_date=2026-09-01" in captured["url"]
    assert "end_date=2026-09-05" in captured["url"]
    assert "/v2/usercollection/daily_sleep" in captured["url"]


def test_sandbox_uses_the_sandbox_prefix(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        return FakeResponse(json.dumps({"data": [], "next_token": None}).encode())

    monkeypatch.setattr(client.urllib.request, "urlopen", fake_urlopen)
    client.OuraClient("tok", sandbox=True).fetch("daily_sleep")
    assert "/v2/sandbox/usercollection/" in captured["url"]


def test_follows_pagination(monkeypatch):
    api, calls = make_client(monkeypatch, [
        {"data": [{"id": "a"}], "next_token": "t1"},
        {"data": [{"id": "b"}], "next_token": "t2"},
        {"data": [{"id": "c"}], "next_token": None},
    ])
    docs = api.fetch("daily_sleep")
    assert [d["id"] for d in docs] == ["a", "b", "c"]
    assert "next_token=t1" in calls[1]
    assert "next_token=t2" in calls[2]


def test_stops_on_a_repeated_next_token(monkeypatch):
    """A server that keeps handing back the same token must not loop forever."""
    api, calls = make_client(monkeypatch, [
        {"data": [{"id": "a"}], "next_token": "same"},
        {"data": [{"id": "b"}], "next_token": "same"},
    ])
    docs = api.fetch("daily_sleep")
    assert [d["id"] for d in docs] == ["a", "b"]
    assert len(calls) == 2


def test_singleton_endpoint_returns_the_object(monkeypatch):
    api, _ = make_client(monkeypatch, [{"id": "me", "age": 34}])
    assert api.fetch("personal_info") == [{"id": "me", "age": 34}]


def test_retries_on_429_then_succeeds(monkeypatch):
    sleeps = []
    api, calls = make_client(monkeypatch, [
        http_error(429),
        {"data": [{"id": "a"}], "next_token": None},
    ], sleeps)
    assert len(api.fetch("daily_sleep")) == 1
    assert len(calls) == 2
    assert sleeps == [2.0]


def test_retries_on_500_with_growing_backoff(monkeypatch):
    sleeps = []
    api, _ = make_client(monkeypatch, [
        http_error(503), http_error(503),
        {"data": [], "next_token": None},
    ], sleeps)
    api.fetch("daily_sleep")
    assert sleeps == [2.0, 4.0]


def test_auth_errors_are_not_retried(monkeypatch):
    api, calls = make_client(monkeypatch, [http_error(401)])
    with pytest.raises(client.OuraAuthError):
        api.fetch("daily_sleep")
    assert len(calls) == 1


def test_bad_request_raises_immediately(monkeypatch):
    api, calls = make_client(monkeypatch, [http_error(400)])
    with pytest.raises(client.OuraError):
        api.fetch("daily_sleep")
    assert len(calls) == 1


def test_fetch_all_survives_one_bad_endpoint(monkeypatch):
    def fake_urlopen(request, timeout=None):
        if "daily_stress" in request.full_url:
            raise http_error(400)
        return FakeResponse(json.dumps({"data": [{"id": "x"}], "next_token": None}).encode())

    monkeypatch.setattr(client.urllib.request, "urlopen", fake_urlopen)
    api = client.OuraClient("tok", sleep=lambda s: None)
    result = api.fetch_all(date(2026, 9, 1), date(2026, 9, 2),
                           endpoints=("daily_sleep", "daily_stress"))
    assert result["daily_sleep"] == [{"id": "x"}]
    assert result["daily_stress"] == []


def test_fetch_all_still_aborts_on_auth_failure(monkeypatch):
    api, _ = make_client(monkeypatch, [http_error(403)])
    with pytest.raises(client.OuraAuthError):
        api.fetch_all(date(2026, 9, 1), date(2026, 9, 2), endpoints=("daily_sleep",))


def test_default_window_includes_tomorrow():
    start, end = client.default_window(30, today=date(2026, 9, 12))
    assert start == date(2026, 8, 13)
    assert end == date(2026, 9, 13)


def test_vo2_max_endpoint_keeps_its_odd_casing():
    # The API 404s on "vo2_max"; only "vO2_max" is a valid path.
    assert "vO2_max" in client.DATE_ENDPOINTS
    assert "vo2_max" not in client.DATE_ENDPOINTS
