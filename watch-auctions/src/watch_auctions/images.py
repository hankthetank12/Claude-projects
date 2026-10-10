"""Embed lot photos in the page as small JPEG data URIs.

Hosted pages (like a claude.ai artifact) block images from other sites, and
an offline copy can't load them either, so the page carries its own photos.
Downloads are cached on disk, so re-running only fetches new lots' photos.
"""
from __future__ import annotations

import base64
import hashlib
import io
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from watch_auctions.http import USER_AGENT

WIDTH, QUALITY = 320, 72
# Stay well under hosting limits (16MB per page); past this, lots keep their remote URL.
BUDGET_BYTES = 12_000_000


def _thumb(url: str, cache: Path) -> bytes | None:
    from PIL import Image

    path = cache / (hashlib.sha1(url.encode()).hexdigest() + ".jpg")
    if path.exists():
        return path.read_bytes()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
        with urllib.request.urlopen(req, timeout=20) as r:
            img = Image.open(io.BytesIO(r.read()))
            img.load()
    except Exception:
        return None
    img = img.convert("RGB")
    if img.width > WIDTH:
        img = img.resize((WIDTH, round(img.height * WIDTH / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    data = buf.getvalue()
    path.write_bytes(data)
    return data


def embed(urls: list[str], cache: Path, workers: int = 16) -> dict[str, str]:
    """Map each image URL to a data: URI, in order, until the size budget runs out."""
    cache.mkdir(parents=True, exist_ok=True)
    unique = list(dict.fromkeys(u for u in urls if u and u.startswith("http")))
    with ThreadPoolExecutor(workers) as pool:
        thumbs = list(pool.map(lambda u: _thumb(u, cache), unique))
    out, used = {}, 0
    for url, data in zip(unique, thumbs):
        if not data:
            continue
        uri = "data:image/jpeg;base64," + base64.b64encode(data).decode()
        if used + len(uri) > BUDGET_BYTES:
            break
        out[url] = uri
        used += len(uri)
    return out
