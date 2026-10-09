import json
import os
from pathlib import Path
from typing import Protocol
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


def build_email(settings: Settings) -> EmailSender:
    if settings.email_mode == "development":
        return DevelopmentMailbox(settings.dev_mailbox_dir)
    return DisabledEmail()
