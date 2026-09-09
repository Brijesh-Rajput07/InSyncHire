# LOCATION: services/notification_service/notification_service/email/email_sender.py

"""
Email sending abstraction (Section 3: "Sends email (SendGrid/SMTP)").

`EmailSender` is a small `Protocol` so `NotificationDispatchService`
never depends on a concrete provider. Two implementations:

  - `ConsoleEmailSender` (default) -- DEV/TEST ONLY, logs the email
    instead of sending it. Same stopgap pattern as
    `OTP_DEBUG_LOG_ENABLED`/`INVITE_DEBUG_LOG_ENABLED` in earlier
    services: lets the whole notification pipeline be exercised
    end-to-end before real email infrastructure exists downstream.
  - `SendGridEmailSender` -- the real Section-3-named provider. Imports
    the `sendgrid` package lazily (same lazy-import discipline as
    `db_admin.py`'s `asyncpg`/`alembic` imports) so this module stays
    importable in test environments without the dependency installed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger("notification_service.email")


@dataclass
class EmailMessage:
    to_address: str
    subject: str
    body: str


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailSender:
    """DEV/TEST ONLY. Never use in a real deployment -- see
    `EMAIL_PROVIDER` in `.env.example`."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []
        """Every message ever "sent" through this instance -- makes
        tests trivial without mocking a real HTTP client."""

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)
        logger.info("[DEV ONLY] email to=%s subject=%r", message.to_address, message.subject)


class SendGridEmailSender:
    def __init__(self, *, api_key: str, from_address: str):
        if not api_key:
            raise ValueError("SendGridEmailSender requires a non-empty api_key")
        self._api_key = api_key
        self._from_address = from_address

    async def send(self, message: EmailMessage) -> None:
        # Lazily imported so this module (and the whole package) stays
        # importable without the `sendgrid` package installed unless a
        # real deployment actually selects EMAIL_PROVIDER=sendgrid.
        import asyncio

        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        mail = Mail(
            from_email=self._from_address,
            to_emails=message.to_address,
            subject=message.subject,
            plain_text_content=message.body,
        )
        client = SendGridAPIClient(self._api_key)
        # SendGridAPIClient.send is synchronous -- run it off the event
        # loop so a slow/blocked HTTP call doesn't stall the consumer.
        await asyncio.to_thread(client.send, mail)


def build_email_sender(*, provider: str, sendgrid_api_key: str | None, from_address: str) -> EmailSender:
    if provider == "sendgrid":
        if not sendgrid_api_key:
            raise ValueError("EMAIL_PROVIDER=sendgrid requires SENDGRID_API_KEY to be set")
        return SendGridEmailSender(api_key=sendgrid_api_key, from_address=from_address)
    if provider == "console":
        return ConsoleEmailSender()
    raise ValueError(f"Unknown EMAIL_PROVIDER '{provider}' -- expected 'console' or 'sendgrid'")