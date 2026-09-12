"""Minimal, dependency-free client for the Oura API v2."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Any, Iterator

log = logging.getLogger(__name__)

API_HOST = "https://api.ouraring.com"
LIVE_PREFIX = "/v2/usercollection"
SANDBOX_PREFIX = "/v2/sandbox/usercollection"

# Endpoints keyed by the query-parameter style they use.
DATE_ENDPOINTS = (
    "daily_sleep",
    "daily_readiness",
    "daily_activity",
    "daily_stress",
    "daily_spo2",
    "daily_resilience",
    "daily_cardiovascular_age",
    "sleep",
    "sleep_time",
    "workout",
    "session",
    "tag",
    "enhanced_tag",
    "vO2_max",  # note the capital O; "vo2_max" is not a valid path
    "rest_mode_period",
)
SINGLETON_ENDPOINTS = ("personal_info", "ring_configuration", "ring_battery_level")


class OuraError(RuntimeError):
    """An Oura API call failed."""


class OuraAuthError(OuraError):
    """The token is missing, malformed, or rejected."""


class OuraClient:
    """Fetches documents from the Oura API, following pagination.

    The API returns ``{"data": [...], "next_token": str | None}``; a token that
    is present means another page is waiting.
    """

    def __init__(
        self,
        token: str,
        *,
        sandbox: bool = False,
        max_retries: int = 4,
        timeout: float = 30.0,
        sleep: Any = time.sleep,
    ) -> None:
        if not token:
            raise OuraAuthError(
                "No Oura token. Set OURA_TOKEN to a personal access token from "
                "https://cloud.ouraring.com/personal-access-tokens"
            )
        self.token = token
        self.prefix = SANDBOX_PREFIX if sandbox else LIVE_PREFIX
        self.max_retries = max_retries
        self.timeout = timeout
        self._sleep = sleep

    # -- transport ---------------------------------------------------------
    def _get(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v})
        url = f"{API_HOST}{self.prefix}/{endpoint}"
        if query:
            url = f"{url}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "User-Agent": "oura-dashboard/1.0",
            },
        )

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")[:400]
                if exc.code in (401, 403):
                    raise OuraAuthError(
                        f"Oura rejected the token ({exc.code}). Check OURA_TOKEN. {body}"
                    ) from exc
                if exc.code == 400:
                    raise OuraError(f"Bad request to {endpoint}: {body}") from exc
                if exc.code == 429 or exc.code >= 500:
                    last_error = OuraError(f"{endpoint} returned {exc.code}: {body}")
                    backoff = 2.0 * (2**attempt)
                    log.warning(
                        "Oura %s -> %s, retrying in %.0fs (attempt %d/%d)",
                        endpoint, exc.code, backoff, attempt + 1, self.max_retries,
                    )
                    self._sleep(backoff)
                    continue
                raise OuraError(f"{endpoint} returned {exc.code}: {body}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = OuraError(f"{endpoint} request failed: {exc}")
                backoff = 2.0 * (2**attempt)
                log.warning(
                    "Oura %s failed (%s), retrying in %.0fs (attempt %d/%d)",
                    endpoint, exc, backoff, attempt + 1, self.max_retries,
                )
                self._sleep(backoff)

        raise last_error or OuraError(f"{endpoint} failed after {self.max_retries} attempts")

    # -- documents ---------------------------------------------------------
    def iter_documents(
        self, endpoint: str, start: date | None = None, end: date | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield every document for an endpoint, following ``next_token``."""
        params: dict[str, str] = {}
        if endpoint in DATE_ENDPOINTS:
            if start:
                params["start_date"] = start.isoformat()
            if end:
                # end_date is inclusive but can lag behind sync; callers pad it.
                params["end_date"] = end.isoformat()

        seen_tokens: set[str] = set()
        while True:
            payload = self._get(endpoint, params)
            data = payload.get("data")
            if data is None:  # singleton endpoints return the object itself
                yield payload
                return
            yield from data
            token = payload.get("next_token")
            if not token or token in seen_tokens:
                return
            seen_tokens.add(token)
            params["next_token"] = token

    def fetch(
        self, endpoint: str, start: date | None = None, end: date | None = None
    ) -> list[dict[str, Any]]:
        return list(self.iter_documents(endpoint, start, end))

    def fetch_all(
        self, start: date, end: date, endpoints: tuple[str, ...] | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch every tracked endpoint, tolerating per-endpoint failures.

        One endpoint your plan or firmware does not populate should not sink the
        whole run, so non-auth errors are logged and the endpoint comes back empty.
        """
        wanted = endpoints or (DATE_ENDPOINTS + SINGLETON_ENDPOINTS)
        out: dict[str, list[dict[str, Any]]] = {}
        for endpoint in wanted:
            try:
                out[endpoint] = self.fetch(endpoint, start, end)
                log.info("fetched %s: %d documents", endpoint, len(out[endpoint]))
            except OuraAuthError:
                raise
            except OuraError as exc:
                log.warning("skipping %s: %s", endpoint, exc)
                out[endpoint] = []
        return out


def default_window(days: int = 120, today: date | None = None) -> tuple[date, date]:
    """A fetch window ending tomorrow, so today's documents are never cut off."""
    today = today or date.today()
    return today - timedelta(days=days), today + timedelta(days=1)
