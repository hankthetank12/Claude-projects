"""Oura OAuth2, including the single-use refresh token dance.

Personal access tokens are deprecated and can no longer be created, so the
supported path is the authorization-code flow:

    client_id + client_secret  ->  (browser consent)  ->  refresh_token
    refresh_token              ->  access_token + a NEW refresh_token

Oura's refresh tokens are **single use**: the moment one is exchanged it is
invalidated and a replacement comes back in the same response. Losing that
replacement means re-authorizing by hand, so every refresh here goes through
``on_rotate`` before the caller is allowed to use the access token.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"
APPLICATIONS_URL = "https://cloud.ouraring.com/oauth/applications"

# Everything the dashboard reads. `daily` covers the daily_* endpoints
# (sleep, readiness, activity, stress, resilience, cardiovascular age);
# SpO2 and the rest each need their own scope.
DEFAULT_SCOPES: tuple[str, ...] = (
    "personal",
    "daily",
    "heartrate",
    "workout",
    "tag",
    "session",
    "spo2Daily",
)

# Refresh a little early rather than racing the expiry mid-run.
EXPIRY_MARGIN_SECONDS = 120


class OAuthError(RuntimeError):
    """An OAuth2 exchange failed."""


class ReauthorizationRequired(OAuthError):
    """The refresh token is gone or spent; only a human can fix this."""


@dataclass
class TokenSet:
    """An access token and the refresh token that replaced its predecessor."""

    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None
    scope: str | None = None
    token_type: str = "bearer"

    @classmethod
    def from_response(cls, payload: dict[str, Any], *, fallback_refresh: str | None = None) -> "TokenSet":
        access = payload.get("access_token")
        if not access:
            raise OAuthError(f"Token response had no access_token: {payload}")
        expires_in = payload.get("expires_in")
        expires_at: float | None = None
        if isinstance(expires_in, (int, float)):
            expires_at = time.time() + float(expires_in)
        return cls(
            access_token=str(access),
            # Oura returns a replacement on every refresh, but keep the old one
            # if a response ever omits it rather than losing the chain.
            refresh_token=str(payload.get("refresh_token") or fallback_refresh or "") or None,
            expires_at=expires_at,
            scope=payload.get("scope"),
            token_type=str(payload.get("token_type") or "bearer"),
        )

    @property
    def expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= self.expires_at - EXPIRY_MARGIN_SECONDS

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scope": self.scope,
            "token_type": self.token_type,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TokenSet":
        return cls(
            access_token=str(payload.get("access_token") or ""),
            refresh_token=payload.get("refresh_token") or None,
            expires_at=payload.get("expires_at"),
            scope=payload.get("scope"),
            token_type=str(payload.get("token_type") or "bearer"),
        )


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------
def _post_token(data: dict[str, str], *, timeout: float = 30.0) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "oura-dashboard/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        code = parsed.get("error", "")
        description = parsed.get("error_description") or raw[:300]

        if code == "invalid_client":
            raise OAuthError(
                "Oura rejected the client credentials. Check OURA_CLIENT_ID and "
                f"OURA_CLIENT_SECRET against {APPLICATIONS_URL}. ({description})"
            ) from exc
        if code == "invalid_grant":
            raise ReauthorizationRequired(
                "Oura rejected the refresh token. These are single use, so this "
                "usually means it was already spent by another run (or the local "
                "CLI and the daily job are sharing one token). Re-authorize with "
                f"`oura-dashboard authorize`. ({description})"
            ) from exc
        raise OAuthError(f"Token request failed ({exc.code}): {description}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise OAuthError(f"Could not reach the Oura token endpoint: {exc}") from exc


def authorize_url(
    client_id: str,
    redirect_uri: str,
    *,
    scopes: Sequence[str] = DEFAULT_SCOPES,
    state: str | None = None,
) -> tuple[str, str]:
    """Build the consent URL. Returns ``(url, state)``."""
    state = state or secrets.token_urlsafe(24)
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}", state


def exchange_code(
    *, client_id: str, client_secret: str, code: str, redirect_uri: str
) -> TokenSet:
    return TokenSet.from_response(
        _post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            }
        )
    )


def refresh_tokens(
    *, client_id: str, client_secret: str, refresh_token: str
) -> TokenSet:
    """Spend a refresh token. The old one is dead once this returns."""
    return TokenSet.from_response(
        _post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            }
        ),
        fallback_refresh=refresh_token,
    )


# --------------------------------------------------------------------------
# local storage
# --------------------------------------------------------------------------
class TokenStore:
    """Caches the token set on disk so a rotation is never lost locally.

    The file holds live credentials, so it is written user-readable only and
    belongs outside version control.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> TokenSet | None:
        if not self.path.is_file():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("could not read %s (%s); ignoring it", self.path, exc)
            return None
        tokens = TokenSet.from_dict(payload)
        return tokens if (tokens.access_token or tokens.refresh_token) else None

    def save(self, tokens: TokenSet) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(tokens.to_dict(), indent=1), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:  # best effort; Windows and odd filesystems
            pass
        tmp.replace(self.path)


# --------------------------------------------------------------------------
# resolution
# --------------------------------------------------------------------------
@dataclass
class Credentials:
    """How to obtain an access token, and where a rotation should be recorded."""

    personal_token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    refresh_token: str | None = None
    store: TokenStore | None = None
    on_rotate: Callable[[TokenSet], None] | None = None
    notices: list[str] = field(default_factory=list)

    @property
    def can_oauth(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def access_token(self) -> str:
        """Return a usable bearer token, refreshing and persisting if needed."""
        # 1. A legacy personal access token needs nothing else. Deprecated by
        #    Oura, but existing ones still work, so honour it if set.
        if self.personal_token:
            log.info("using the personal access token from OURA_TOKEN")
            return self.personal_token

        if not self.can_oauth:
            raise ReauthorizationRequired(
                "No Oura credentials. Register an application at "
                f"{APPLICATIONS_URL}, then set OURA_CLIENT_ID and "
                "OURA_CLIENT_SECRET and run `oura-dashboard authorize`."
            )

        stored = self.store.load() if self.store else None

        # 2. A cached access token that is still valid avoids spending the
        #    refresh token at all, which matters when it is single use.
        if stored and stored.access_token and not stored.expired:
            log.info("reusing the cached access token")
            return stored.access_token

        refresh_token = self.refresh_token or (stored.refresh_token if stored else None)
        if not refresh_token:
            raise ReauthorizationRequired(
                "No refresh token available. Run `oura-dashboard authorize` to "
                "grant access, then set OURA_REFRESH_TOKEN (or keep the local "
                "token file)."
            )

        log.info("exchanging the refresh token for a new access token")
        tokens = refresh_tokens(
            client_id=self.client_id or "",
            client_secret=self.client_secret or "",
            refresh_token=refresh_token,
        )

        # 3. The old refresh token is now dead. Persist the replacement before
        #    anything else can fail, and complain loudly if that does not stick.
        if self.store:
            try:
                self.store.save(tokens)
            except OSError as exc:
                self.notices.append(
                    f"Could not write the rotated refresh token to {self.store.path}: {exc}"
                )
        if self.on_rotate and tokens.refresh_token:
            try:
                self.on_rotate(tokens)
            except Exception as exc:  # persistence is the caller's mechanism
                self.notices.append(str(exc))

        return tokens.access_token
