"""M3 browser-facing HTTP contracts; real PostgreSQL/FFmpeg, existing AI simulator."""

import hashlib
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from test_ai import Simulator, configure
from test_credits import authenticate, seed

from zoclip.ai import worker as ai
from zoclip.core.db import utcnow
from zoclip.credits.models import CreditReservation
from zoclip.media import worker
from zoclip.media.models import Job
from zoclip.media.storage import LocalStorage

pytestmark = pytest.mark.integration


@pytest.fixture
def media_http(app, monkeypatch):
    users = seed(app.state.session_factory)
    monkeypatch.setattr(LocalStorage, "free_bytes", lambda self: 1024**4)
    app.state.settings.media_allowed_import_hosts = ["media.example.com"]
    return users


def upload(client, app, users, data):
    headers = authenticate(client, app, users["alice"])
    payload = dict(
        size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), rights_attested=True
    )
    response = client.post("/api/v1/uploads", json=payload, headers=headers)
    assert response.status_code == 201
    session = response.json()
    assert (
        client.post("/api/v1/uploads", json=payload, headers=headers).json()["id"] == session["id"]
    )
    path = f"/api/v1/uploads/{session['id']}"
    parts = [
        data[i : i + session["part_bytes"]] for i in range(0, len(data), session["part_bytes"])
    ]
    for number, part in enumerate(parts):
        chunk_headers = {
            **headers,
            "Content-Type": "application/octet-stream",
            "X-Content-SHA256": hashlib.sha256(part).hexdigest(),
        }
        for _ in range(2):
            result = client.put(f"{path}/parts/{number}", content=part, headers=chunk_headers)
            assert result.status_code == 200
            assert result.json()["size_bytes"] == len(part)
        assert client.get(path).json()["received_parts"] == list(range(number + 1))
    headers["Idempotency-Key"] = "http-complete"
    complete = client.post(path + "/complete", headers=headers)
    assert complete.status_code == 202
    job = complete.json()
    assert client.post(path + "/complete", headers=headers).json()["id"] == job["id"]
    worker.run_job(
        UUID(job["id"]),
        0,
        app.state.session_factory,
        app.state.settings,
        LocalStorage(app.state.settings.media_root),
    )
    return session, headers, job


def test_http_upload_quote_confirm_simulated_pipeline_and_cancellation(
    client, app, media_http, monkeypatch
):
    from pathlib import Path

    users = media_http
    session, headers, validation = upload(
        client, app, users, Path("tests/fixtures/source.mp4").read_bytes()
    )
    assert client.get(f"/api/v1/jobs/{validation['id']}").json()["stage"] == "SOURCE_READY"
    source = client.get(f"/api/v1/videos/{session['video_id']}").json()
    assert source["state"] == "READY" and source["metadata_json"]["duration_seconds"] == 3
    headers["Idempotency-Key"] = "http-quote"
    quote = client.post(
        "/api/v1/jobs/quote",
        headers=headers,
        json={"source_seconds": 3, "output_count": 1, "captions": False, "reframe": False},
    ).json()
    assert quote["credits"] == 1
    assert client.get("/api/v1/me/credits").json()["reserved_credits"] == 0
    settings = configure(app.state.session_factory, users, app.state.settings)
    app.state.settings = settings
    headers["Idempotency-Key"] = "http-confirmed-generation"
    generate_path = f"/api/v1/videos/{session['video_id']}/generate"
    response = client.post(generate_path, headers=headers, json={"quote_id": quote["id"]})
    assert response.status_code == 202
    job = response.json()
    for _ in range(3):
        assert (
            client.post(generate_path, headers=headers, json={"quote_id": quote["id"]}).json()["id"]
            == job["id"]
        )
    assert client.get("/api/v1/me/credits").json()["reserved_credits"] == 1
    simulator = Simulator()
    monkeypatch.setattr(ai, "HTTPProviders", lambda settings: simulator)
    for _ in range(12):
        with app.state.session_factory() as db:
            current = db.get(Job, UUID(job["id"]))
            if current.state != "QUEUED":
                break
            generation = current.generation
        worker.run_job(
            UUID(job["id"]),
            generation,
            app.state.session_factory,
            settings,
            LocalStorage(settings.media_root),
        )
    actual = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert actual["state"] == "SUGGESTIONS_READY" and actual["progress_percent"] is None
    assert simulator.calls == ["deepgram", "gemini"]
    events = client.get(f"/api/v1/jobs/{job['id']}/events").json()
    assert any(event["code"] == "analyzing" for event in events)
    for _ in range(2):
        assert (
            client.post(f"/api/v1/jobs/{job['id']}/cancel", headers=headers).json()["state"]
            == "CANCELED"
        )
    assert client.get("/api/v1/me/credits").json()["reserved_credits"] == 0
    with app.state.session_factory() as db:
        assert (
            db.scalar(
                select(CreditReservation).where(CreditReservation.job_id == UUID(job["id"]))
            ).state
            == "RELEASED"
        )


def test_http_foreign_upload_and_job_every_supported_operation_denied(client, app, media_http):
    from pathlib import Path

    session, _, job = upload(
        client, app, media_http, Path("tests/fixtures/source.mp4").read_bytes()
    )
    headers = authenticate(client, app, media_http["bob"])
    paths = [
        ("GET", f"/uploads/{session['id']}"),
        ("DELETE", f"/uploads/{session['id']}"),
        ("POST", f"/uploads/{session['id']}/complete"),
        ("GET", f"/jobs/{job['id']}"),
        ("GET", f"/jobs/{job['id']}/events"),
        ("POST", f"/jobs/{job['id']}/cancel"),
        ("GET", f"/videos/{session['video_id']}"),
    ]
    for method, path in paths:
        assert client.request(method, "/api/v1" + path, headers=headers).status_code == 404
    headers.update(
        {
            "Content-Type": "application/octet-stream",
            "X-Content-SHA256": hashlib.sha256(b"x").hexdigest(),
        }
    )
    assert (
        client.put(
            f"/api/v1/uploads/{session['id']}/parts/0", headers=headers, content=b"x"
        ).status_code
        == 404
    )


def test_http_rights_https_allowlist_limits_and_expired_session(client, app, media_http):
    headers = authenticate(client, app, media_http["alice"])
    data = {"size_bytes": 10, "sha256": "a" * 64, "rights_attested": False}
    assert client.post("/api/v1/uploads", headers=headers, json=data).status_code == 422
    for url in [
        "https://youtube.com/watch?v=test",
        "https://127.0.0.1/source.mp4",
        "http://media.example.com/source.mp4",
    ]:
        result = client.post(
            "/api/v1/videos/import-url",
            headers=headers,
            json={"url": url, "max_bytes": 100, "rights_attested": True},
        )
        assert result.status_code == 422 and result.json()["code"] == "unsupported_source"
    app.state.settings.media_max_bytes = 9
    data["rights_attested"] = True
    assert client.post("/api/v1/uploads", headers=headers, json=data).status_code == 413
    client.post("/api/v1/auth/logout", headers=headers)
    assert client.post("/api/v1/uploads", headers=headers, json=data).status_code == 401


def test_http_expired_quote_does_not_create_paid_job(client, app, media_http, monkeypatch):
    from pathlib import Path

    session, headers, _ = upload(
        client, app, media_http, Path("tests/fixtures/source.mp4").read_bytes()
    )
    headers["Idempotency-Key"] = "expiring-quote"
    quote = client.post(
        "/api/v1/jobs/quote", headers=headers, json={"source_seconds": 3, "output_count": 1}
    ).json()
    from zoclip.credits import service as credits

    later = utcnow() + timedelta(minutes=16)
    monkeypatch.setattr(credits, "utcnow", lambda: later)
    headers["Idempotency-Key"] = "expired-confirm"
    response = client.post(
        f"/api/v1/videos/{session['video_id']}/generate",
        headers=headers,
        json={"quote_id": quote["id"]},
    )
    assert response.status_code == 409 and response.json()["code"] == "quote_expired"
    assert client.get("/api/v1/me/credits").json()["reserved_credits"] == 0
