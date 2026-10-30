"""YouTube link import: URL validation and the yt-dlp subprocess contract."""

import subprocess

import pytest

from zoclip.core.config import Settings
from zoclip.core.errors import ApiError
from zoclip.media import link_import


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://unused:unused@localhost/link_import_test",
        media_root=str(tmp_path),
        link_proxy_url="socks5://127.0.0.1:40000",
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
        "https://youtube.com/watch?v=aqz-KE-bpKQ&t=42s",
        "https://m.youtube.com/watch?v=aqz-KE-bpKQ",
        "https://music.youtube.com/watch?v=aqz-KE-bpKQ",
        "https://www.youtube.com/shorts/aqz-KE-bpKQ",
        "https://www.youtube.com/live/aqz-KE-bpKQ",
        "https://youtu.be/aqz-KE-bpKQ",
        "https://youtu.be/aqz-KE-bpKQ?si=xyz",
        "https://www.youtube.com/embed/aqz-KE-bpKQ",
        " https://youtu.be/aqz-KE-bpKQ?si=xyz#t=42 ",
    ],
)
def test_valid_youtube_urls(url):
    assert link_import.youtube_video_id(url) == "aqz-KE-bpKQ"


@pytest.mark.parametrize(
    "url",
    [
        "https://vimeo.com/12345678901",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/watch",
        "https://www.youtube.com/channel/UCaqzKEbpKQ0",
        "https://evil-youtube.com/watch?v=aqz-KE-bpKQ",
        "https://www.youtube.com.evil.com/watch?v=aqz-KE-bpKQ",
        "http://www.youtube.com/watch?v=aqz-KE-bpKQ",
        "https://user:pass@www.youtube.com/watch?v=aqz-KE-bpKQ",
        "https://youtu.be/aqz-KE-bpKQ/extra",
        "not a url",
        "https://127.0.0.1/watch?v=aqz-KE-bpKQ",
        "https://youtube.com:8443/watch?v=aqz-KE-bpKQ",
        "https://youtube.com\\@127.0.0.1/watch?v=aqz-KE-bpKQ",
        "https://youtube.com/watch?v=aqz-KE-bpKQ\n",
        "https://youtube.com/watch?v=aqz-KE-bpKQ%0A",
    ],
)
def test_rejected_urls(url):
    with pytest.raises(ApiError) as exc:
        link_import.youtube_video_id(url)
    assert exc.value.code == "unsupported_source"


class FakeProc:
    def __init__(self, dest, size=1234, returncode=0):
        self._dest = dest
        self._size = size
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def communicate(self):
        if self.returncode == 0 and self._size:
            self._dest.write_bytes(b"x" * self._size)
        return b"", b"ERROR: boom" if self.returncode else b""

    def kill(self):
        self.returncode = -9

    def wait(self):
        return self.returncode


def test_download_args_and_size(settings, tmp_path, monkeypatch):
    seen = {}

    def fake_popen(args, **kwargs):
        seen["args"] = args
        assert kwargs["shell"] is False
        return FakeProc(tmp_path / "out.mp4")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    dest = tmp_path / "out.mp4"
    size = link_import.download_youtube(
        "https://www.youtube.com/watch?v=aqz-KE-bpKQ", dest, settings
    )
    assert size == 1234
    args = seen["args"]
    assert args[0] == "yt-dlp"
    assert "--proxy" in args and "socks5://127.0.0.1:40000" in args
    assert "--extractor-args" in args
    assert args[-1] == "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
    assert "--max-filesize" in args
    assert "--ignore-config" in args
    assert args[args.index("--js-runtimes") + 1] == "node"


def test_only_canonical_video_url_reaches_downloader(settings, tmp_path):
    url = "https://youtu.be/aqz-KE-bpKQ?si=share&next=https://127.0.0.1/#t=30"
    args = link_import.build_args(url, tmp_path / "out.mp4", settings)
    assert args[-2:] == ["--", "https://www.youtube.com/watch?v=aqz-KE-bpKQ"]


def test_download_failure_is_422(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(
        subprocess, "Popen", lambda args, **kw: FakeProc(tmp_path / "o.mp4", 0, returncode=1)
    )
    with pytest.raises(ApiError) as exc:
        link_import.download_youtube("https://youtu.be/aqz-KE-bpKQ", tmp_path / "o.mp4", settings)
    assert exc.value.code == "link_download_failed"
    assert "boom" not in exc.value.detail


def test_production_missing_proxy_never_falls_back_to_direct_egress(
    settings, tmp_path, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("Missing proxy must fail before the downloader starts")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    with pytest.raises(ApiError) as exc:
        link_import.download_youtube(
            "https://youtu.be/aqz-KE-bpKQ",
            tmp_path / "out.mp4",
            settings.model_copy(update={"app_env": "production", "link_proxy_url": ""}),
        )
    assert exc.value.code == "link_runtime_unavailable"
