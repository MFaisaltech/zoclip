import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Protocol
from urllib.parse import quote
from uuid import uuid4

from zoclip.core.config import Settings
from zoclip.core.errors import ApiError


class EmailSender(Protocol):
    def ensure_available(self) -> None: ...
    def send(self, recipient: str, purpose: str, token: str) -> None: ...


class DisabledEmail:
    def ensure_available(self) -> None:
        raise ApiError(503, "email_unconfigured", "Email delivery is not configured.")

    def send(self, recipient: str, purpose: str, token: str) -> None:
        self.ensure_available()


class DevelopmentMailbox:
    """Explicit local mailbox; never returned by HTTP and forbidden in production."""

    def __init__(self, directory: str):
        self.directory = Path(directory)

    def ensure_available(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def send(self, recipient: str, purpose: str, token: str) -> None:
        self.ensure_available()
        path = self.directory / f"{uuid4()}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"recipient": recipient, "purpose": purpose, "token": token}, stream)


class SMTPEmail:
    """Authenticated TLS transport. No token/recipient/SMTP response logging or retries."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def ensure_available(self) -> None:
        if self.settings.email_mode != "smtp":
            raise ApiError(503, "email_unconfigured", "Email delivery is not configured.")

    def send(self, recipient: str, purpose: str, token: str) -> None:
        self.ensure_available()
        destinations = {
            "verify-email": ("Verify your ZoClip email", "verify-email", "24 hours"),
            "password-reset": ("Reset your ZoClip password", "reset-password", "one hour"),
        }
        if purpose not in destinations or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
            raise ValueError("Unsupported transactional email")
        subject, path, expiry = destinations[purpose]
        s = self.settings
        message = EmailMessage()
        message["From"] = str(s.smtp_from)
        message["To"] = recipient
        message["Subject"] = subject
        message["Date"] = formatdate(localtime=False)
        message["Message-ID"] = make_msgid(domain=str(s.smtp_from).split("@", 1)[1])
        link = f"{s.public_app_url}/{path}#token={quote(token, safe='')}"
        message.set_content(
            f"{subject}\n\nOpen this private link to continue:\n{link}\n\n"
            f"This single-use link expires in {expiry}. Opening it does not change your account "
            "until you confirm on the page. If you did not request this, ignore this email.\n"
        )
        context = ssl.create_default_context()
        try:
            if s.smtp_tls == "implicit":
                with smtplib.SMTP_SSL(
                    s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds, context=context
                ) as server:
                    server.login(s.smtp_username, s.smtp_password.get_secret_value())
                    server.send_message(message, from_addr=str(s.smtp_from), to_addrs=[recipient])
            else:
                with smtplib.SMTP(
                    s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds
                ) as server:
                    server.ehlo()
                    server.starttls(context=context)  # Failure never falls back to plaintext.
                    server.ehlo()
                    server.login(s.smtp_username, s.smtp_password.get_secret_value())
                    server.send_message(message, from_addr=str(s.smtp_from), to_addrs=[recipient])
        except (OSError, smtplib.SMTPException):
            raise ApiError(
                503, "email_delivery_failed", "Email could not be delivered. Try again."
            ) from None


def build_email(settings: Settings) -> EmailSender:
    if settings.email_mode == "smtp":
        return SMTPEmail(settings)
    if settings.email_mode == "development":
        return DevelopmentMailbox(settings.dev_mailbox_dir)
    return DisabledEmail()
