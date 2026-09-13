"""Command line entry point.

    oura-dashboard sync       fetch new data into the local history
    oura-dashboard build      regenerate the HTML dashboard
    oura-dashboard brief      print the morning brief (text or html)
    oura-dashboard send       email the morning brief
    oura-dashboard morning    sync + build + send, the daily job
    oura-dashboard demo       build everything from synthetic sample data
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import (
    __version__, analysis, auth, authorize, brief, client, dashboard, gh_secrets,
    mailer, metrics, sample, store, suggestions,
)
from .config import Config

log = logging.getLogger("oura_dashboard")


def _history_path(config: Config) -> Path:
    return config.data_dir / "history.json"


def _credentials(config: Config) -> auth.Credentials:
    """Assemble how this run should get an access token, and where to save one.

    In GitHub Actions there is no filesystem that survives the run, so a
    rotated refresh token has to go back into the repository secret; locally
    the token file is enough.
    """
    credentials = auth.Credentials(
        personal_token=config.token,
        client_id=config.client_id,
        client_secret=config.client_secret,
        refresh_token=config.refresh_token,
        store=auth.TokenStore(config.token_file),
    )

    if gh_secrets.in_github_actions():
        def persist(tokens: auth.TokenSet) -> None:
            if not tokens.refresh_token:
                return
            try:
                gh_secrets.set_secret("OURA_REFRESH_TOKEN", tokens.refresh_token)
            except gh_secrets.SecretWriteError as exc:
                raise gh_secrets.SecretWriteError(str(exc)) from exc

        credentials.on_rotate = persist

    return credentials


def _api(config: Config, credentials: auth.Credentials) -> client.OuraClient:
    return client.OuraClient(credentials.access_token(), sandbox=config.sandbox)


def _load(config: Config) -> tuple[store.History, analysis.Analysis, list[suggestions.Suggestion]]:
    history = store.History.load(_history_path(config))
    rows = metrics.build_rows(history)
    if not rows:
        raise SystemExit(
            "No data in the local history yet. Run `oura-dashboard sync` first "
            "(or `oura-dashboard demo` to see it working with sample data)."
        )
    result = analysis.analyse(rows, config.sleep_need_hours)
    return history, result, suggestions.generate(result)


def _sync(config: Config, days: int, credentials: auth.Credentials | None = None) -> store.History:
    if not config.has_credentials:
        raise SystemExit(
            "No Oura credentials. Personal access tokens are deprecated and can "
            "no longer be created, so register an application at "
            f"{auth.APPLICATIONS_URL}, set OURA_CLIENT_ID and OURA_CLIENT_SECRET, "
            "then run `oura-dashboard authorize`."
        )
    credentials = credentials if credentials is not None else _credentials(config)
    api = _api(config, credentials)
    start, end = client.default_window(days)
    log.info("fetching %s .. %s", start, end)
    fetched = api.fetch_all(start, end)

    history = store.History.load(_history_path(config))
    changes = history.merge(fetched)
    history.save(_history_path(config))
    if changes:
        summary = ", ".join(f"{name} +{count}" for name, count in sorted(changes.items()))
        log.info("history updated: %s", summary)
    else:
        log.info("history already up to date")
    print(f"Synced {history.total_documents} documents into {_history_path(config)}")
    return history


def _build(config: Config) -> Path:
    _, result, found = _load(config)
    target = config.out_dir / "index.html"
    dashboard.write(result, found, target)
    print(f"Dashboard written to {target} ({target.stat().st_size:,} bytes)")
    return target


def _send(
    config: Config,
    dashboard_url: str | None,
    dry_run: bool,
    attach_dashboard: bool = False,
    notices: list[str] | None = None,
) -> None:
    notices = notices or []
    _, result, found = _load(config)
    subject = brief.subject_with_notices(result, found, notices)
    text_body = brief.render_text(
        result, found, dashboard_url=dashboard_url, notices=notices
    )
    html_body = brief.render_html(
        result, found, dashboard_url=dashboard_url, notices=notices
    )

    if dry_run or not config.can_send_mail:
        if not dry_run:
            missing = [
                name
                for name, value in (
                    ("MAIL_TO", config.mail_to),
                    ("MAIL_FROM", config.mail_from),
                    ("GMAIL_APP_PASSWORD", config.gmail_app_password),
                )
                if not value
            ]
            print(f"Not sending: {', '.join(missing)} not set. Brief follows.\n", file=sys.stderr)
        print(f"Subject: {subject}\n")
        print(text_body)
        return

    attachments: list[Path] = []
    if attach_dashboard:
        candidate = config.out_dir / "index.html"
        if candidate.is_file():
            attachments.append(candidate)
        else:
            log.warning("no dashboard at %s to attach; run build first", candidate)

    message = mailer.build_message(
        subject=subject,
        sender=config.mail_from or "",
        recipient=config.mail_to or "",
        text_body=text_body,
        html_body=html_body,
        attachments=attachments,
    )
    mailer.send(
        message,
        username=config.mail_from or "",
        password=config.gmail_app_password or "",
    )
    print(f"Morning brief sent to {config.mail_to}: {subject}")


def _check(config: Config, send_test: bool) -> int:
    """Verify everything the daily job needs, and say what is missing.

    Better to find a broken scope or a rejected app password now than at 7am.
    """
    ok = True

    def line(good: bool, label: str, detail: str = "") -> None:
        nonlocal ok
        mark = "  ok  " if good else " FAIL "
        print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))
        if not good:
            ok = False

    # 1. Credentials
    if config.token:
        line(True, "Oura credentials", "using the legacy personal access token")
    elif config.client_id and config.client_secret:
        line(True, "Oura credentials", "OAuth client configured")
    else:
        line(False, "Oura credentials",
             "set OURA_CLIENT_ID and OURA_CLIENT_SECRET, then run `authorize`")
        print("\nFix the above and run `oura-dashboard check` again.")
        return 1

    # 2. A usable access token
    credentials = _credentials(config)
    try:
        token = credentials.access_token()
        line(bool(token), "Access token", "obtained")
    except (auth.OAuthError, client.OuraError) as exc:
        line(False, "Access token", str(exc)[:220])
        print("\nFix the above and run `oura-dashboard check` again.")
        return 1
    for notice in credentials.notices:
        line(False, "Token persistence", notice[:220])

    # 3. The API actually answers, which also proves the scopes
    api = client.OuraClient(token, sandbox=config.sandbox)
    start, end = client.default_window(7)
    reachable = 0
    for endpoint in ("daily_sleep", "daily_readiness", "daily_activity"):
        try:
            documents = api.fetch(endpoint, start, end)
            reachable += 1
            line(True, f"Endpoint {endpoint}", f"{len(documents)} documents in the last 7 days")
        except client.OuraError as exc:
            line(False, f"Endpoint {endpoint}", str(exc)[:180])
    if not reachable:
        print("\nNo endpoint responded. Re-run `authorize` and grant every scope.")
        return 1

    # 4. Mail
    if config.can_send_mail:
        line(True, "Email settings", f"{config.mail_from} -> {config.mail_to}")
    else:
        missing = [
            name for name, value in (
                ("MAIL_TO", config.mail_to),
                ("MAIL_FROM", config.mail_from),
                ("GMAIL_APP_PASSWORD", config.gmail_app_password),
            ) if not value
        ]
        line(False, "Email settings", f"missing {', '.join(missing)}")

    # 5. Local history
    history = store.History.load(_history_path(config))
    rows = metrics.build_rows(history)
    if rows:
        line(True, "Local history",
             f"{len(rows)} days, {rows[0].day} to {rows[-1].day}")
    else:
        line(True, "Local history", "empty — run `sync` to fill it")

    # 6. Optional live send
    if send_test and config.can_send_mail:
        try:
            message = mailer.build_message(
                subject="Oura dashboard test",
                sender=config.mail_from or "",
                recipient=config.mail_to or "",
                text_body=(
                    "This is a test from `oura-dashboard check`.\n"
                    "If you are reading it, the morning brief can reach you."
                ),
            )
            mailer.send(
                message,
                username=config.mail_from or "",
                password=config.gmail_app_password or "",
            )
            line(True, "Test email", f"sent to {config.mail_to}")
        except mailer.MailError as exc:
            line(False, "Test email", str(exc)[:220])

    print()
    print("Everything checks out." if ok else "Some checks failed — see above.")
    return 0 if ok else 1


def _authorize(config: Config, port: int, no_browser: bool) -> None:
    if not (config.client_id and config.client_secret):
        raise SystemExit(
            "Set OURA_CLIENT_ID and OURA_CLIENT_SECRET first. Register an "
            f"application at {auth.APPLICATIONS_URL} — add "
            f"http://localhost:{port}/callback to its redirect URIs."
        )

    tokens = authorize.run_flow(
        client_id=config.client_id,
        client_secret=config.client_secret,
        port=port,
        open_browser=not no_browser,
    )

    store_ = auth.TokenStore(config.token_file)
    store_.save(tokens)

    print(f"\nAuthorized. Token set saved to {config.token_file}")
    if tokens.scope:
        print(f"Granted scopes: {tokens.scope}")
    print(
        "\nFor the daily GitHub Actions job, set this as the OURA_REFRESH_TOKEN "
        "secret:\n"
    )
    print(f"  {tokens.refresh_token}\n")
    print(
        "Oura refresh tokens are single use. The workflow rotates this secret "
        "itself after every run, so do not reuse this value locally as well — "
        "run `authorize` again if you need a separate local token."
    )


def _demo(config: Config, days: int) -> None:
    history = store.History()
    history.merge(sample.generate(days))
    rows = metrics.build_rows(history)
    result = analysis.analyse(rows, config.sleep_need_hours)
    found = suggestions.generate(result)

    config.out_dir.mkdir(parents=True, exist_ok=True)
    target = config.out_dir / "index.html"
    dashboard.write(
        result,
        found,
        target,
        title="Oura Morning Readout",
        banner=(
            "Sample data — this page is built from synthetic readings to show the "
            "layout, not from a real Oura account. Run `sync` with your own token "
            "for the real thing."
        ),
    )
    brief_path = config.out_dir / "brief.html"
    brief_path.write_text(brief.render_html(result, found), encoding="utf-8")

    print(f"Sample dashboard: {target}")
    print(f"Sample brief:     {brief_path}")
    print()
    print(brief.render_text(result, found))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="oura-dashboard",
        description="Track Oura ring stats, build a dashboard, and send a morning brief.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="log what it is doing")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="fetch new data from the Oura API")
    p_sync.add_argument("--days", type=int, default=120, help="how far back to fetch (default 120)")

    sub.add_parser("build", help="regenerate the HTML dashboard from local history")

    p_brief = sub.add_parser("brief", help="print the morning brief without sending it")
    p_brief.add_argument("--html", action="store_true", help="print the HTML version")
    p_brief.add_argument("--url", help="dashboard link to include")

    p_send = sub.add_parser("send", help="email the morning brief")
    p_send.add_argument("--url", help="dashboard link to include")
    p_send.add_argument("--dry-run", action="store_true", help="print instead of sending")
    p_send.add_argument(
        "--attach-dashboard",
        action="store_true",
        help="attach the built dashboard HTML (useful without GitHub Pages)",
    )

    p_morning = sub.add_parser("morning", help="sync, rebuild the dashboard, and send the brief")
    p_morning.add_argument("--days", type=int, default=120)
    p_morning.add_argument("--url", help="dashboard link to include")
    p_morning.add_argument("--skip-send", action="store_true", help="sync and build only")
    p_morning.add_argument(
        "--attach-dashboard",
        action="store_true",
        help="attach the built dashboard HTML to the email",
    )

    p_auth = sub.add_parser(
        "authorize", help="grant access in the browser and save a refresh token"
    )
    p_auth.add_argument(
        "--port", type=int, default=authorize.DEFAULT_PORT,
        help=f"local callback port, must match your app's redirect URI (default {authorize.DEFAULT_PORT})",
    )
    p_auth.add_argument(
        "--no-browser", action="store_true", help="print the URL instead of opening it"
    )

    p_check = sub.add_parser(
        "check", help="verify credentials, API access and email settings"
    )
    p_check.add_argument(
        "--email", action="store_true", help="also send a test email"
    )

    p_demo = sub.add_parser("demo", help="build from synthetic sample data")
    p_demo.add_argument("--days", type=int, default=120)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    config = Config.from_env()

    try:
        if args.command == "sync":
            _sync(config, args.days)
        elif args.command == "build":
            _build(config)
        elif args.command == "brief":
            _, result, found = _load(config)
            if args.html:
                print(brief.render_html(result, found, dashboard_url=args.url))
            else:
                print(f"Subject: {brief.subject(result, found)}\n")
                print(brief.render_text(result, found, dashboard_url=args.url))
        elif args.command == "authorize":
            _authorize(config, args.port, args.no_browser)
        elif args.command == "check":
            return _check(config, args.email)
        elif args.command == "send":
            _send(config, args.url, args.dry_run, args.attach_dashboard)
        elif args.command == "morning":
            # One credentials object for the whole job, so a rotation that
            # happens during the sync is reported in the email that follows.
            credentials = _credentials(config)
            _sync(config, args.days, credentials)
            _build(config)
            if not args.skip_send:
                _send(config, args.url, False, args.attach_dashboard, credentials.notices)
            for notice in credentials.notices:
                print(f"error: {notice}", file=sys.stderr)
            if credentials.notices:
                # The brief went out, but tomorrow's run will not work until
                # this is fixed, so the workflow run must go red.
                return 1
        elif args.command == "demo":
            _demo(config, args.days)
    except (
        client.OuraError,
        mailer.MailError,
        auth.OAuthError,
        gh_secrets.SecretWriteError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
