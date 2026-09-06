"""Outbound email.

PLAN.md Section 0.5 checkpoint: no new dependency was adopted for this.
Python's own `smtplib`/`email` (standard library) already speak plain SMTP,
which is all sending to Mailpit - or to any real provider later - requires;
reaching for an extra library (e.g. `aiosmtplib`) would trade nothing but a
Section 0.5-worth of justification for a marginal API convenience this
project's one call site does not need.

`smtplib` is synchronous. The one send call is pushed onto a thread
(`asyncio.to_thread`) so it cannot block the event loop every other request
is sharing - the same reasoning `services/reports.py` applies to its
synchronous PDF/XLSX rendering.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


class MailError(Exception):
    """Sending failed. Callers decide whether that should block the action
    that triggered it (see `invite()`'s own docstring in users.py) - an SMTP
    outage must never be able to silently pretend an invite was delivered."""


def _send_sync(message: EmailMessage) -> None:
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
        smtp.send_message(message)


async def send_email(*, to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        await asyncio.to_thread(_send_sync, message)
    except OSError as exc:
        # OSError covers smtplib's own SMTPException family (all subclass
        # it) plus a bare connection failure (Mailpit not up yet) - one
        # catch, one generic failure, matching this codebase's auth-error
        # convention of not multiplying error shapes for what the caller
        # treats identically either way.
        raise MailError(f"Could not send email to {to}: {exc}") from exc

    logger.info("Sent email to %s (%s) - view at %s", to, subject, settings.SMTP_WEB_URL)


async def send_invitation_email(
    *, to: str, full_name: str, invite_url: str, role_name: str
) -> None:
    body = (
        f"Hi {full_name},\n\n"
        f"You've been invited to DealFlow360 as a {role_name}.\n\n"
        f"Set up your account here:\n{invite_url}\n\n"
        "This link is a one-time use and will expire - if it has, ask whoever invited you "
        "for a new one.\n\n"
        "- DealFlow360"
    )
    await send_email(to=to, subject="You're invited to DealFlow360", body=body)
