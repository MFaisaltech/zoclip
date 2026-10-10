"""Archive security tests for the standalone backup tools, no credentials or providers."""

import importlib.util
import io
import os
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("backup_ops", Path("deploy/backup.py"))
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def archive(entries):
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode="w") as output:
        for name, kind, body in entries:
            item = tarfile.TarInfo(name)
            item.type, item.mode = kind, 0o777
            item.linkname = "../../outside"
            item.size = len(body) if kind == tarfile.REGTYPE else 0
            output.addfile(item, io.BytesIO(body) if item.size else None)
    content.seek(0)
    return tarfile.open(fileobj=content, mode="r|")


def test_restore_streams_private_files_without_archived_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda _: SimpleNamespace(free=1024**4))
    with archive(
        [
            (".", tarfile.DIRTYPE, b""),
            ("nested", tarfile.DIRTYPE, b""),
            ("nested/fixture", tarfile.REGTYPE, b"fictional"),
        ]
    ) as source:
        backup.extract_media(source, tmp_path)
    target = tmp_path / "nested/fixture"
    assert target.read_bytes() == b"fictional"
    if os.name != "nt":
        assert target.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize(
    "name,kind",
    [
        ("/outside", tarfile.REGTYPE),
        ("../outside", tarfile.REGTYPE),
        ("nested/../../outside", tarfile.REGTYPE),
        ("C:/outside", tarfile.REGTYPE),
        ("nested\\..\\outside", tarfile.REGTYPE),
        ("link", tarfile.SYMTYPE),
        ("hard", tarfile.LNKTYPE),
    ],
)
def test_restore_rejects_paths_and_links(tmp_path, name, kind):
    with archive([(name, kind, b"fictional")]) as source:
        with pytest.raises(RuntimeError, match="Unsafe media archive"):
            backup.extract_media(source, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_restore_never_overwrites_duplicate_member(tmp_path, monkeypatch):
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda _: SimpleNamespace(free=1024**4))
    with archive(
        [
            ("fixture", tarfile.REGTYPE, b"first"),
            ("fixture", tarfile.REGTYPE, b"second"),
        ]
    ) as source:
        with pytest.raises(FileExistsError):
            backup.extract_media(source, tmp_path)
    assert (tmp_path / "fixture").read_bytes() == b"first"


def test_restore_refuses_insufficient_headroom_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    with archive([("fixture", tarfile.REGTYPE, b"fictional")]) as source:
        with pytest.raises(RuntimeError, match="disk headroom"):
            backup.extract_media(source, tmp_path)
    assert list(tmp_path.iterdir()) == []
