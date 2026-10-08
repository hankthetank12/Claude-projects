from __future__ import annotations

import json
import time
import urllib.request

USER_AGENT = "Mozilla/5.0 (compatible; watch-auctions/0.1; personal catalog aggregator)"


def fetch(url: str, *, data: dict | None = None, headers: dict | None = None,
          retries: int = 3, timeout: int = 30) -> str:
    h = {"User-Agent": USER_AGENT, "Accept-Language": "en-US"}
    h.update(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")
