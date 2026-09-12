"""Write a rotated refresh token back into the repository's Actions secrets.

Oura's refresh tokens are single use, so a scheduled job that reads one from a
secret has to put the replacement back or tomorrow's run has nothing to spend.
The `gh` CLI is preinstalled on GitHub-hosted runners and handles the
libsodium sealed-box encryption that the REST API requires, so shelling out to
it keeps this dependency-free.

The default ``GITHUB_TOKEN`` cannot write secrets; this needs a PAT with
"Secrets: write" on the repository, passed as ``GH_TOKEN``.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

log = logging.getLogger(__name__)


class SecretWriteError(RuntimeError):
    """The rotated token could not be persisted."""


def in_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def set_secret(name: str, value: str, *, repository: str | None = None) -> None:
    """Set an Actions secret via `gh secret set`, reading the value from stdin."""
    repository = repository or os.environ.get("GITHUB_REPOSITORY") or ""
    if not repository:
        raise SecretWriteError(
            "GITHUB_REPOSITORY is not set, so there is no repository to write to."
        )
    if not os.environ.get("GH_TOKEN"):
        raise SecretWriteError(
            "GH_TOKEN is not set. The rotated Oura refresh token could not be "
            "saved, so the next scheduled run will fail. Add a fine-grained "
            "personal access token with 'Secrets: write' on this repository as "
            "the GH_TOKEN secret, then re-run `oura-dashboard authorize`."
        )
    if not shutil.which("gh"):
        raise SecretWriteError("The `gh` CLI is not available to write the secret.")

    try:
        # The value goes through stdin so it never appears in a process list.
        completed = subprocess.run(
            ["gh", "secret", "set", name, "--repo", repository, "--body-file", "-"],
            input=value,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SecretWriteError(f"Could not run `gh secret set`: {exc}") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[:400]
        raise SecretWriteError(
            f"`gh secret set {name}` failed: {detail or 'no output'}. The rotated "
            "refresh token was not saved, so the next run will need a fresh "
            "`oura-dashboard authorize`."
        )
    log.info("wrote the rotated refresh token to the %s secret", name)
