"""Command line entry point.

    whole-foods import FILES...   parse saved receipt emails into the history
    whole-foods sync              pull receipts from a mailbox over IMAP
    whole-foods items             what the history says gets bought, and how often
    whole-foods order             build the next order
    whole-foods cart              resolve the order towards a cart back end
    whole-foods send              email the order sheet
    whole-foods demo              run the whole thing on synthetic data
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

from . import __version__, basket, cart as cart_mod, catalog as catalog_mod, mailer, render, sample, store
from .config import Config
from .receipts import ReceiptError, parse_file

log = logging.getLogger("whole_foods_agent")


def _orders_path(config: Config) -> Path:
    return config.data_dir / "orders.json"


def _load_catalog(config: Config) -> catalog_mod.Catalog:
    orders = store.OrderStore.load(_orders_path(config)).orders()
    if not orders:
        raise SystemExit(
            "No orders in the local history yet. Run `whole-foods import` with "
            "saved receipt emails, or `whole-foods sync` with a mailbox "
            "configured (or `whole-foods demo` to see it work on sample data)."
        )
    return catalog_mod.build(orders)


def _build_proposal(config: Config, args: argparse.Namespace, catalog: catalog_mod.Catalog):
    on_date = date.fromisoformat(args.date) if getattr(args, "date", None) else date.today()
    return basket.build(
        catalog,
        on_date=on_date,
        due_threshold=getattr(args, "threshold", None) or config.due_threshold,
        budget=getattr(args, "budget", None) if getattr(args, "budget", None) is not None else config.budget,
        max_items=getattr(args, "max_items", None) if getattr(args, "max_items", None) is not None else config.max_items,
    )


def _import(config: Config, paths: list[str]) -> None:
    found: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for suffix in ("*.eml", "*.html", "*.htm", "*.txt"):
                found.extend(sorted(path.glob(suffix)))
        elif path.is_file():
            found.append(path)
        else:
            print(f"warning: {path} does not exist", file=sys.stderr)

    orders = []
    failed = 0
    for path in found:
        try:
            orders.append(parse_file(path))
        except (ReceiptError, OSError) as exc:
            failed += 1
            log.warning("could not parse %s: %s", path, exc)

    history = store.OrderStore.load(_orders_path(config))
    changed = history.merge(orders)
    history.save(_orders_path(config))
    print(
        f"Parsed {len(orders)} of {len(found)} files"
        f"{f' ({failed} unreadable)' if failed else ''}; "
        f"{changed} new or updated. History now holds {len(history)} orders."
    )


def _sync(config: Config, since: str | None, limit: int | None) -> None:
    from .gmail import MailboxError, fetch_receipts

    address = os.environ.get("GMAIL_ADDRESS") or config.mail_from
    password = config.gmail_app_password
    if not address or not password:
        raise SystemExit(
            "Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD for the mailbox that "
            "receives the receipts. The App Password must be created by that "
            "account holder at https://myaccount.google.com/apppasswords."
        )

    try:
        orders = list(fetch_receipts(address, password, since=since, limit=limit))
    except MailboxError as exc:
        raise SystemExit(f"error: {exc}") from exc

    history = store.OrderStore.load(_orders_path(config))
    changed = history.merge(orders)
    history.save(_orders_path(config))
    print(
        f"Read {len(orders)} receipts from {address}; {changed} new or updated. "
        f"History now holds {len(history)} orders."
    )


def _items(config: Config) -> None:
    catalog = _load_catalog(config)
    print(f"{len(catalog.items)} distinct items across {len(catalog.orders)} orders\n")
    print(f"{'buys':>4}  {'every':>7}  {'last bought':>11}  {'price':>7}  item")
    for stats in catalog.ranked():
        interval = f"~{round(stats.median_interval)}d" if stats.median_interval else "—"
        price = f"${stats.last_price:.2f}" if stats.last_price is not None else "—"
        print(
            f"{stats.times_bought:>4}  {interval:>7}  {stats.last_bought.isoformat():>11}  "
            f"{price:>7}  {stats.name}"
        )


def _order(config: Config, args: argparse.Namespace) -> None:
    catalog = _load_catalog(config)
    proposal = _build_proposal(config, args, catalog)

    if args.html:
        target = config.out_dir / "order.html"
        render.write_html(proposal, target, order_count=len(catalog.orders))
        print(f"Order sheet written to {target} ({target.stat().st_size:,} bytes)")
    else:
        print(render.render_text(proposal))


def _cart(config: Config, args: argparse.Namespace) -> None:
    catalog = _load_catalog(config)
    proposal = _build_proposal(config, args, catalog)
    try:
        adapter = cart_mod.get_adapter(args.via)
        entries = adapter.submit(proposal.lines)
    except cart_mod.CartUnavailable as exc:
        raise SystemExit(f"error: {exc}") from exc

    added = sum(1 for entry in entries if entry.added)
    for entry in entries:
        quantity = f"{entry.quantity:g} {entry.unit}" if entry.unit != "each" else f"{entry.quantity:g}"
        print(f"{'[added]' if entry.added else '[link] '} {quantity} x {entry.name}")
        if entry.url:
            print(f"          {entry.url}")
    print(f"\n{len(entries)} items, {added} added to a cart automatically.")


def _send(config: Config, args: argparse.Namespace) -> None:
    catalog = _load_catalog(config)
    proposal = _build_proposal(config, args, catalog)
    subject = render.subject(proposal)
    text_body = render.render_text(proposal)
    html_body = render.render_html(proposal, order_count=len(catalog.orders))

    if args.dry_run or not config.can_send_mail:
        if not args.dry_run:
            missing = [
                name
                for name, value in (
                    ("WFA_MAIL_TO", config.mail_to),
                    ("WFA_MAIL_FROM", config.mail_from),
                    ("GMAIL_APP_PASSWORD", config.gmail_app_password),
                )
                if not value
            ]
            print(f"Not sending: {', '.join(missing)} not set. Order follows.\n", file=sys.stderr)
        print(f"Subject: {subject}\n")
        print(text_body)
        return

    message = mailer.build_message(
        subject=subject,
        sender=config.mail_from or "",
        recipient=config.mail_to or "",
        text_body=text_body,
        html_body=html_body,
    )
    mailer.send(message, username=config.mail_from or "", password=config.gmail_app_password or "")
    print(f"Order sheet sent to {config.mail_to}: {subject}")


def _demo(config: Config, args: argparse.Namespace) -> None:
    orders = sample.generate(args.days)
    catalog = catalog_mod.build(orders)
    proposal = basket.build(
        catalog,
        due_threshold=config.due_threshold,
        budget=args.budget,
        max_items=args.max_items,
    )

    target = config.out_dir / "order.html"
    render.write_html(
        proposal,
        target,
        order_count=len(catalog.orders),
        title="Whole Foods order (sample)",
        banner=(
            "Sample data — built from a synthetic shopping history to show the "
            "layout, not from a real account. Run `import` or `sync` for the "
            "real thing."
        ),
    )
    print(render.render_text(proposal))
    print(f"\nSample order sheet: {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="whole-foods",
        description="Build the next Whole Foods order from what actually gets bought.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="log what it is doing")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="parse saved receipt emails (.eml/.html) or a folder of them")
    p_import.add_argument("paths", nargs="+")

    p_sync = sub.add_parser("sync", help="pull receipts from a mailbox over IMAP")
    p_sync.add_argument("--since", help='only messages after an IMAP date, e.g. "01-Jan-2026"')
    p_sync.add_argument("--limit", type=int, help="only the most recent N messages")

    sub.add_parser("items", help="show what gets bought and how often")

    def _order_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--date", help="build the order as of this date (YYYY-MM-DD)")
        p.add_argument("--threshold", type=float, help="how far through its usual gap an item must be (default 0.8)")
        p.add_argument("--budget", type=float, help="cap the estimated total")
        p.add_argument("--max-items", type=int, dest="max_items", help="cap the number of items")

    p_order = sub.add_parser("order", help="build the next order")
    _order_args(p_order)
    p_order.add_argument("--html", action="store_true", help="write the HTML order sheet instead of printing")

    p_cart = sub.add_parser("cart", help="resolve the order towards a cart back end")
    _order_args(p_cart)
    p_cart.add_argument("--via", default="links", help="cart back end: links (default) or browser")

    p_send = sub.add_parser("send", help="email the order sheet")
    _order_args(p_send)
    p_send.add_argument("--dry-run", action="store_true", help="print instead of sending")

    p_demo = sub.add_parser("demo", help="run on synthetic sample data")
    p_demo.add_argument("--days", type=int, default=140)
    p_demo.add_argument("--budget", type=float)
    p_demo.add_argument("--max-items", type=int, dest="max_items")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    config = Config.from_env()

    try:
        if args.command == "import":
            _import(config, args.paths)
        elif args.command == "sync":
            _sync(config, args.since, args.limit)
        elif args.command == "items":
            _items(config)
        elif args.command == "order":
            _order(config, args)
        elif args.command == "cart":
            _cart(config, args)
        elif args.command == "send":
            _send(config, args)
        elif args.command == "demo":
            _demo(config, args)
    except mailer.MailError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
