"""Local private UUID objects. Callers never supply filesystem paths."""

import os
import shutil
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import UUID

from zoclip.core.errors import ApiError


class Storage(Protocol):
    def path(self, object_id: UUID) -> Path: ...
    def open(self, object_id: UUID) -> BinaryIO: ...
    def delete(self, object_id: UUID) -> None: ...
    def free_bytes(self) -> int: ...


class DirectoryCursor(Protocol):
    def __next__(self) -> os.DirEntry[str]: ...
    def close(self) -> None: ...


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.sweep: DirectoryCursor | None = None

    def path(self, object_id: UUID) -> Path:
        if not isinstance(object_id, UUID):
            raise ValueError("UUID storage key required")
        path = self.root / object_id.hex
        if path.is_symlink():
            raise ApiError(503, "storage_unavailable", "Private storage unavailable.")
        return path

    def open(self, object_id: UUID) -> BinaryIO:
        return self.path(object_id).open("rb")

    def create(self, object_id: UUID) -> BinaryIO:
        fd = os.open(self.path(object_id), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        return os.fdopen(fd, "wb")

    def delete(self, object_id: UUID) -> None:
        self.path(object_id).unlink(missing_ok=True)
        self.sync_directory()

    def promote(self, temporary: UUID, target: UUID) -> None:
        os.replace(self.path(temporary), self.path(target))
        # Persist the rename before committing its PostgreSQL receipt. File fsync
        # alone does not make a directory entry durable after host power loss.
        self.sync_directory()

    def sync_directory(self) -> None:
        if os.name != "nt":
            fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def free_bytes(self) -> int:
        return shutil.disk_usage(self.root).free
