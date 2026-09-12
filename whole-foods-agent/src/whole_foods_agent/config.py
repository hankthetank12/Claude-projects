"""Configuration loaded from the environment (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# .../whole-foods-agent/src/whole_foods_agent/config.py -> .../whole-foods-agent
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
    """Everything the agent reads from the environment.

    The shopper is whoever's history we are reading; nothing here assumes it is
    the person running the tool, so a shared household account works by setting
    the mailbox or export path to theirs.
    """

    # How often the household actually shops. Cadence maths is relative to this.
    shop_interval_days: float
    # An item is proposed once this much of its usual gap has elapsed.
    due_threshold: float
    # Optional ceiling on the proposed order's estimated cost.
    budget: float | None
    max_items: int | None
    mail_to: str | None
    mail_from: str | None
    gmail_app_password: str | None
    data_dir: Path
    out_dir: Path

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()

        def _float(name: str, default: float) -> float:
            raw = os.environ.get(name, "").strip()
            try:
                return float(raw) if raw else default
            except ValueError:
                return default

        def _opt_float(name: str) -> float | None:
            raw = os.environ.get(name, "").strip()
            try:
                return float(raw) if raw else None
            except ValueError:
                return None

        def _opt_int(name: str) -> int | None:
            raw = os.environ.get(name, "").strip()
            try:
                return int(raw) if raw else None
            except ValueError:
                return None

        return cls(
            shop_interval_days=_float("WFA_SHOP_INTERVAL_DAYS", 7.0),
            due_threshold=_float("WFA_DUE_THRESHOLD", 0.8),
            budget=_opt_float("WFA_BUDGET"),
            max_items=_opt_int("WFA_MAX_ITEMS"),
            mail_to=os.environ.get("WFA_MAIL_TO") or None,
            mail_from=os.environ.get("WFA_MAIL_FROM") or None,
            gmail_app_password=os.environ.get("GMAIL_APP_PASSWORD") or None,
            data_dir=Path(os.environ.get("WFA_DATA_DIR") or DEFAULT_DATA_DIR),
            out_dir=Path(os.environ.get("WFA_OUT_DIR") or DEFAULT_OUT_DIR),
        )

    @property
    def can_send_mail(self) -> bool:
        return bool(self.mail_to and self.mail_from and self.gmail_app_password)
