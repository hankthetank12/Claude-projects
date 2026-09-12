"""On-disk history of raw Oura documents.

The API keeps your data, but pulling a long window every morning is slow and
trend maths wants a stable local record, so each run upserts documents into a
single JSON file that the daily workflow commits.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class History:
    """Raw documents grouped by endpoint, keyed by document id."""

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        self.schema_version: int = payload.get("schema_version", SCHEMA_VERSION)
        self.updated_at: str | None = payload.get("updated_at")
        self.endpoints: dict[str, dict[str, Any]] = payload.get("endpoints", {})

    # -- persistence -------------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "History":
        if not path.is_file():
            return cls()
        try:
            return cls(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("could not read history at %s (%s); starting fresh", path, exc)
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": self.updated_at,
            "endpoints": self.endpoints,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    # -- mutation ----------------------------------------------------------
    @staticmethod
    def _key(endpoint: str, doc: dict[str, Any], index: int) -> str:
        for field in ("id", "day", "timestamp", "start_datetime"):
            value = doc.get(field)
            if value:
                return str(value)
        return f"{endpoint}-{index}"

    def merge(self, fetched: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
        """Upsert fetched documents; returns the count of new/changed docs."""
        changes: dict[str, int] = {}
        for endpoint, documents in fetched.items():
            bucket = self.endpoints.setdefault(endpoint, {})
            changed = 0
            for index, doc in enumerate(documents):
                key = self._key(endpoint, doc, index)
                if bucket.get(key) != doc:
                    bucket[key] = doc
                    changed += 1
            if changed:
                changes[endpoint] = changed
        return changes

    # -- access ------------------------------------------------------------
    def documents(self, endpoint: str) -> list[dict[str, Any]]:
        """Documents for an endpoint, sorted by day/timestamp."""
        bucket = self.endpoints.get(endpoint, {})

        def sort_key(doc: dict[str, Any]) -> str:
            return str(doc.get("day") or doc.get("timestamp") or "")

        return sorted(bucket.values(), key=sort_key)

    def singleton(self, endpoint: str) -> dict[str, Any]:
        docs = self.documents(endpoint)
        return docs[-1] if docs else {}

    @property
    def total_documents(self) -> int:
        return sum(len(bucket) for bucket in self.endpoints.values())
