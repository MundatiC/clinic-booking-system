"""Outgoing email over SMTP (stdlib). One transport for every environment:
Mailpit locally, Gmail SMTP in production (render.yaml). Injected like the Clock.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from app.core.config import Settings

log = logging.getLogger("app.mail")


class Mailer(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def send(self, message: EmailMessage) -> None:
        s = self.s
        context = ssl.create_default_context()
        smtp: smtplib.SMTP
        if s.smtp_security == "ssl":
            smtp = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=context)
        else:
            smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
        with smtp:
            if s.smtp_security == "starttls":
                smtp.starttls(context=context)
            if s.smtp_user and s.smtp_password:
                smtp.login(s.smtp_user, s.smtp_password.get_secret_value())
            smtp.send_message(message)


class MemoryMailer:
    """Test double: keeps sent messages in `outbox`."""

    def __init__(self) -> None:
        self.outbox: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.outbox.append(message)


def send_safely(mailer: Mailer, message: EmailMessage, template: str) -> None:
    """Runs after the response (BackgroundTasks): a mail failure must not break the request.

    shortcut: no retry/outbox, upgrade to an outbox table + worker when delivery must be
    guaranteed. Logs the template name only, never the recipient.
    """
    try:
        mailer.send(message)
        log.info("email sent", extra={"template": template})
    except Exception:
        log.exception("email failed", extra={"template": template})
