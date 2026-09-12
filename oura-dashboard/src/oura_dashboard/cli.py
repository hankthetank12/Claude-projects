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

from . import __version__, analysis, brief, client, dashboard, mailer, metrics, sample, store, suggestions
from .config import Config

log = logging.getLogger("oura_dashboard")


def _history_path(config: Config) -> Path:
    return config.data_dir / "history.json"


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


def _sync(config: Config, days: int) -> store.History:
    if not config.token:
        raise SystemExit(
            "OURA_TOKEN is not set. Create a personal access token at "
            "https://cloud.ouraring.com/personal-access-tokens and put it in "
            ".env or the environment."
        )
    api = client.OuraClient(config.token, sandbox=config.sandbox)
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
) -> None:
    _, result, found = _load(config)
    subject = brief.subject(result, found)
    text_body = brief.render_text(result, found, dashboard_url=dashboard_url)
    html_body = brief.render_html(result, found, dashboard_url=dashboard_url)

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
        elif args.command == "send":
            _send(config, args.url, args.dry_run, args.attach_dashboard)
        elif args.command == "morning":
            _sync(config, args.days)
            _build(config)
            if not args.skip_send:
                _send(config, args.url, False, args.attach_dashboard)
        elif args.command == "demo":
            _demo(config, args.days)
    except (client.OuraError, mailer.MailError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
