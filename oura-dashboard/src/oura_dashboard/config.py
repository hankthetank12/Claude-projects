"""Configuration loaded from the environment (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# .../oura-dashboard/src/oura_dashboard/config.py -> .../oura-dashboard
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_OUT_DIR = PROJECT_ROOT / "out"


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from a .env file without overriding real env vars."""
    path = path or PROJECT_ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Config:
    token: str | None            # legacy personal access token (deprecated by Oura)
    client_id: str | None
    client_secret: str | None
    refresh_token: str | None
    timezone: str
    sleep_need_hours: float
    mail_to: str | None
    mail_from: str | None
    gmail_app_password: str | None
    data_dir: Path
    out_dir: Path
    sandbox: bool

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()

        def _float(name: str, default: float) -> float:
            raw = os.environ.get(name, "").strip()
            try:
                return float(raw) if raw else default
            except ValueError:
                return default

        return cls(
            token=os.environ.get("OURA_TOKEN") or None,
            client_id=os.environ.get("OURA_CLIENT_ID") or None,
            client_secret=os.environ.get("OURA_CLIENT_SECRET") or None,
            refresh_token=os.environ.get("OURA_REFRESH_TOKEN") or None,
            timezone=os.environ.get("OURA_TIMEZONE", "UTC").strip() or "UTC",
            sleep_need_hours=_float("OURA_SLEEP_NEED_HOURS", 8.0),
            mail_to=os.environ.get("MAIL_TO") or None,
            mail_from=os.environ.get("MAIL_FROM") or None,
            gmail_app_password=os.environ.get("GMAIL_APP_PASSWORD") or None,
            data_dir=Path(os.environ.get("OURA_DATA_DIR") or DEFAULT_DATA_DIR),
            out_dir=Path(os.environ.get("OURA_OUT_DIR") or DEFAULT_OUT_DIR),
            sandbox=os.environ.get("OURA_SANDBOX", "").lower() in {"1", "true", "yes"},
        )

    @property
    def can_send_mail(self) -> bool:
        return bool(self.mail_to and self.mail_from and self.gmail_app_password)

    @property
    def token_file(self) -> Path:
        """Where the rotated OAuth token set is cached. Never commit this."""
        return self.data_dir / ".oauth.json"

    @property
    def has_credentials(self) -> bool:
        return bool(self.token or (self.client_id and self.client_secret))
