"""Pull Whole Foods receipt emails out of a mailbox over IMAP.

Nothing here assumes whose mailbox it is. The household member who actually
does the shopping sets GMAIL_ADDRESS and GMAIL_APP_PASSWORD to their own
account and the rest of the tool is unchanged.

Gmail blocks normal passwords for IMAP, so this needs an App Password from
https://myaccount.google.com/apppasswords, created by the account holder.
"""

from __future__ import annotations

import email
import imaplib
import logging
from typing import Iterator

from .model import Order
from .receipts import RECEIPT_SENDER, RECEIPT_SUBJECT, ReceiptError, parse_email_message

log = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
ALL_MAIL = '"[Gmail]/All Mail"'


class MailboxError(RuntimeError):
    """Reading the mailbox failed."""


def _search_query(since: str | None) -> str:
    parts = [f'FROM "{RECEIPT_SENDER}"', f'SUBJECT "{RECEIPT_SUBJECT}"']
    if since:
        parts.append(f"SINCE {since}")
    return "(" + " ".join(parts) + ")"


def fetch_receipts(
    address: str,
    app_password: str,
    *,
    since: str | None = None,
    limit: int | None = None,
    host: str = IMAP_HOST,
    port: int = IMAP_PORT,
) -> Iterator[Order]:
    """Yield every receipt order found in the mailbox.

    `since` is an IMAP date such as "01-Jan-2026". Messages that do not parse
    are logged and skipped rather than aborting the run, since one odd receipt
    should not cost you the rest of the history.
    """
    try:
        connection = imaplib.IMAP4_SSL(host, port, timeout=60)
    except OSError as exc:
        raise MailboxError(f"could not reach {host}:{port}: {exc}") from exc

    try:
        try:
            connection.login(address, app_password)
        except imaplib.IMAP4.error as exc:
            raise MailboxError(
                "Gmail rejected the IMAP login. GMAIL_APP_PASSWORD must be a "
                "16-character App Password created by the account holder at "
                f"https://myaccount.google.com/apppasswords. Server said: {exc}"
            ) from exc

        status, _ = connection.select(ALL_MAIL, readonly=True)
        if status != "OK":
            # Not every account exposes the All Mail folder by that name.
            status, _ = connection.select("INBOX", readonly=True)
            if status != "OK":
                raise MailboxError("could not open All Mail or INBOX")

        status, data = connection.search(None, _search_query(since))
        if status != "OK":
            raise MailboxError("IMAP search failed")

        ids = data[0].split()
        if limit is not None:
            ids = ids[-limit:]
        log.info("found %d candidate receipt messages", len(ids))

        for message_id in ids:
            status, payload = connection.fetch(message_id, "(RFC822)")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                log.warning("could not fetch message %s", message_id)
                continue
            raw = payload[0][1]
            try:
                message = email.message_from_bytes(raw)
                yield parse_email_message(message, source=message_id.decode())
            except ReceiptError as exc:
                log.warning("skipping message %s: %s", message_id.decode(), exc)
    finally:
        try:
            connection.logout()
        except Exception:  # noqa: BLE001 - logout failures are not interesting
            pass
