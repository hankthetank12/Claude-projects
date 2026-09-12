"""One-time browser consent, captured on a localhost redirect.

Oura matches ``redirect_uri`` exactly against the whitelist on your
application, so the port here has to match what you registered.
"""

from __future__ import annotations

import http.server
import logging
import secrets
import threading
import time
import urllib.parse
import webbrowser
from typing import Sequence

from .auth import DEFAULT_SCOPES, OAuthError, TokenSet, authorize_url, exchange_code

log = logging.getLogger(__name__)

DEFAULT_PORT = 8731
DEFAULT_REDIRECT = f"http://localhost:{DEFAULT_PORT}/callback"

_PAGE = """<!doctype html>
<meta charset="utf-8"><title>{title}</title>
<style>
  body {{ font: 15px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
         max-width: 34rem; margin: 12vh auto; padding: 0 20px; color: #0b0b0b;
         background: #fcfcfb; }}
  h1 {{ font-size: 20px; margin: 0 0 8px; }}
  p {{ color: #52514e; margin: 0 0 8px; }}
  code {{ background: #f0efec; padding: 1px 5px; border-radius: 4px; }}
</style>
<h1>{title}</h1>
<p>{body}</p>
"""


class _Handler(http.server.BaseHTTPRequestHandler):
    """Captures a single OAuth redirect and hands it to the waiting thread."""

    result: dict[str, str] = {}
    expected_state: str = ""
    done: threading.Event

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in ("/callback", "/"):
            self.send_error(404)
            return

        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

        if params.get("error"):
            _Handler.result = {"error": params.get("error_description") or params["error"]}
            self._reply("Authorization declined", _Handler.result["error"], status=400)
        elif not params.get("code"):
            _Handler.result = {"error": "the redirect carried no authorization code"}
            self._reply("Something went wrong", _Handler.result["error"], status=400)
        elif params.get("state") != _Handler.expected_state:
            # Guards against another site walking a code through your browser.
            _Handler.result = {"error": "state mismatch — ignoring this redirect"}
            self._reply("State mismatch", _Handler.result["error"], status=400)
        else:
            _Handler.result = {"code": params["code"]}
            self._reply(
                "Oura connected",
                "You can close this tab and go back to the terminal.",
            )
        _Handler.done.set()

    def _reply(self, title: str, body: str, status: int = 200) -> None:
        page = _PAGE.format(title=title, body=body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)
        # Flush before signalling, so shutting the server down cannot truncate
        # the page the browser is still reading.
        self.wfile.flush()

    def log_message(self, *args: object) -> None:
        """Keep the local server quiet; the CLI does the talking."""


def run_flow(
    *,
    client_id: str,
    client_secret: str,
    port: int = DEFAULT_PORT,
    redirect_uri: str | None = None,
    scopes: Sequence[str] = DEFAULT_SCOPES,
    open_browser: bool = True,
    timeout: float = 300.0,
) -> TokenSet:
    """Walk the authorization-code flow and return the resulting token set."""
    redirect_uri = redirect_uri or f"http://localhost:{port}/callback"
    url, state = authorize_url(
        client_id, redirect_uri, scopes=scopes, state=secrets.token_urlsafe(24)
    )

    _Handler.result = {}
    _Handler.expected_state = state
    _Handler.done = threading.Event()

    try:
        server = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    except OSError as exc:
        raise OAuthError(
            f"Could not listen on port {port} ({exc}). Close whatever is using it, "
            "or pass --port with a port your Oura application also whitelists."
        ) from exc

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        print("Open this URL to grant access:\n")
        print(f"  {url}\n")
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:  # headless box, no browser configured
                pass
        print(f"Waiting for the redirect to {redirect_uri} ...")

        if not _Handler.done.wait(timeout):
            raise OAuthError(
                f"Timed out after {timeout:.0f}s waiting for the redirect. "
                "Re-run and complete the consent screen in the browser."
            )
        # Let the response finish reaching the browser before tearing down.
        time.sleep(0.3)
    finally:
        server.shutdown()
        server.server_close()

    if "error" in _Handler.result:
        raise OAuthError(f"Authorization failed: {_Handler.result['error']}")

    return exchange_code(
        client_id=client_id,
        client_secret=client_secret,
        code=_Handler.result["code"],
        redirect_uri=redirect_uri,
    )
