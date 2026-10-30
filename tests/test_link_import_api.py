"""Both frontend generations reach YouTube's adapter without weakening direct SSRF rules."""

from pathlib import Path
from uuid import UUID

import pytest
from test_credits import authenticate, seed

from zoclip.media import worker
from zoclip.media.models import Job
from zoclip.media.storage import LocalStorage


@pytest.mark.parametrize("legacy", [False, True])
def test_import_routes_prepare_youtube_with_ownership_limits_and_idempotency(
    client, app, monkeypatch, legacy
):
    users = seed(app.state.session_factory)
    monkeypatch.setattr(LocalStorage, "free_bytes", lambda self: 1024**4)
    headers = authenticate(client, app, users["alice"])
    payload = {"url": "https://youtu.be/aqz-KE-bpKQ?si=shared", "rights_attested": True}
    if legacy:
        payload["max_bytes"] = 1024**2
    path = "/api/v1/videos/" + ("import-url" if legacy else "import-link")
    before = client.get("/api/v1/me/credits").json()
    response = client.post(path, headers=headers, json=payload)
    assert response.status_code == 202
    job = response.json()
    assert client.post(path, headers=headers, json=payload).json()["id"] == job["id"]
    with app.state.session_factory() as db:
        saved = db.get(Job, UUID(job["id"]))
        assert saved.payload["source"] == "youtube"
        assert saved.payload["rights_attested"] is True
        assert saved.payload["max_bytes"] == (
            1024**2 if legacy else app.state.settings.media_max_bytes
        )

    def local_fixture(url, dest, settings, progress):
        assert settings.media_max_bytes == (
            1024**2 if legacy else app.state.settings.media_max_bytes
        )
        data = Path("tests/fixtures/source.mp4").read_bytes()
        dest.write_bytes(data)
        return len(data)

    monkeypatch.setattr(worker, "download_youtube", local_fixture)
    worker.run_job(
        UUID(job["id"]),
        0,
        app.state.session_factory,
        app.state.settings,
        LocalStorage(app.state.settings.media_root),
    )
    assert client.get(f"/api/v1/jobs/{job['id']}").json()["state"] == "COMPLETED"
    assert client.get(f"/api/v1/videos/{job['video_id']}").json()["state"] == "READY"
    assert client.get("/api/v1/me/credits").json() == before
    authenticate(client, app, users["bob"])
    assert client.get(f"/api/v1/videos/{job['video_id']}").status_code == 404


def test_link_admission_preserves_auth_csrf_rights_and_rejects_private_hosts(client, app):
    payload = {"url": "https://youtu.be/aqz-KE-bpKQ", "rights_attested": True}
    path = "/api/v1/videos/import-link"
    assert (
        client.post(path, json=payload, headers={"Idempotency-Key": "anonymous"}).status_code == 401
    )
    users = seed(app.state.session_factory)
    headers = authenticate(client, app, users["alice"])
    assert (
        client.post(path, json=payload, headers={"Idempotency-Key": "no-csrf"}).status_code == 403
    )
    assert (
        client.post(path, json=payload | {"rights_attested": False}, headers=headers).status_code
        == 422
    )
    assert (
        client.post(
            path, json=payload | {"url": "https://127.0.0.1/watch?v=aqz-KE-bpKQ"}, headers=headers
        ).status_code
        == 422
    )
