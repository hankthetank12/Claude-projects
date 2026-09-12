"""Send the order sheet through Gmail's SMTP endpoint.

Gmail requires an App Password here, not the account password: normal sign-in is
blocked for SMTP. Create one at https://myaccount.google.com/apppasswords.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from typing import Sequence

log = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465  # implicit TLS


class MailError(RuntimeError):
    """Sending the order failed."""


def build_message(
    *,
    subject: str,
    sender: str,
    recipient: str,
    text_body: str,
    html_body: str | None = None,
    attachments: Sequence[Path] = (),
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message["Date"] = formatdate(localtime=True)
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    for path in attachments:
        if not path.is_file():
            log.warning("attachment %s does not exist, skipping", path)
            continue
        subtype = "html" if path.suffix.lower() in {".html", ".htm"} else "octet-stream"
        maintype = "text" if subtype == "html" else "application"
        message.add_attachment(
            path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
        )
    return message


def send(
    message: EmailMessage,
    *,
    username: str,
    password: str,
    host: str = SMTP_HOST,
    port: int = SMTP_PORT,
) -> None:
    """Deliver a message, translating SMTP failures into a clear error."""
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=45) as server:
            server.login(username, password)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(
            "Gmail rejected the login. GMAIL_APP_PASSWORD must be a 16-character "
            "App Password (https://myaccount.google.com/apppasswords), not an "
            f"account password. Server said: {exc.smtp_error!r}"
        ) from exc
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise MailError(f"Could not send the order via {host}:{port}: {exc}") from exc
    log.info("order sheet sent to %s", message["To"])
