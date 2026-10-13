"""M4 HTTP contracts with real private FFmpeg exports and simulated AI only."""

import pytest
import test_credits
import test_media
import test_rendering
from fastapi.testclient import TestClient

from zoclip.main import create_app
from zoclip.media.storage import LocalStorage

financial_database = test_credits.concurrent_db
media = test_media.media
video_bytes = test_media.video_bytes
selected = test_rendering.selected


@pytest.fixture
def editor_http(selected, monkeypatch):
    ((factory, users, settings, storage), video, job), clip_id, simulator = selected
    app = create_app(settings.model_copy(update={"cookie_secure": False}))
    app.state.session_factory = factory
    import fakeredis

    app.state.redis = fakeredis.FakeRedis()
    monkeypatch.setattr(LocalStorage, "free_bytes", lambda self: 1024**4)
    with TestClient(app, base_url="http://localhost:8000") as client:
        headers = test_credits.authenticate(client, app, users["alice"])
        yield client, app, headers, users, video, job, clip_id, simulator


def test_transcript_suggestions_private_export_and_revision_http(editor_http, selected):
    client, app, headers, users, video, job, clip_id, simulator = editor_http
    transcript = client.get(f"/api/v1/videos/{video}/transcript", params={"job_id": str(job)})
    assert transcript.status_code == 200
    assert transcript.json()["data"]["text"]
    suggestions = client.get(f"/api/v1/videos/{video}/suggestions").json()
    assert suggestions["items"][0]["score"] == 85
    assert suggestions["rendered"] is False
    assert client.get(f"/api/v1/clips/{clip_id}/download").status_code == 404
    test_rendering.render_selected(selected)
    download = client.get(f"/api/v1/clips/{clip_id}/download?revision=1")
    assert download.status_code == 200
    assert download.headers["content-type"] == "video/mp4"
    assert b"ftyp" in download.content[:32]
    outputs = client.get(f"/api/v1/clips/{clip_id}/renders").json()
    assert outputs[0]["metadata"]["width"] == 720
    assert outputs[0]["metadata"]["height"] == 1280
    prefs = client.get(f"/api/v1/clips/{clip_id}").json()["preferences"]
    prefs.update({"preset": "classic", "frame": "pad", "title": "Edited source", "end_ms": 2000})
    edit = client.patch(
        f"/api/v1/clips/{clip_id}", json=prefs, headers={**headers, "If-Match": '"1"'}
    )
    assert edit.status_code == 200 and edit.json()["revision"] == 2
    conflict = client.patch(
        f"/api/v1/clips/{clip_id}", json=prefs, headers={**headers, "If-Match": '"1"'}
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "revision_conflict"
    assert client.get(f"/api/v1/clips/{clip_id}/download").status_code == 404
    assert client.get(f"/api/v1/clips/{clip_id}/download?revision=1").status_code == 200
    assert simulator.calls == ["deepgram", "gemini"]


def test_editor_all_foreign_reads_mutations_and_download_denied(editor_http):
    client, app, headers, users, video, job, clip_id, _ = editor_http
    prefs = client.get(f"/api/v1/clips/{clip_id}").json()["preferences"]
    suggestion = client.get(f"/api/v1/videos/{video}/suggestions").json()["items"][0]["id"]
    headers = test_credits.authenticate(client, app, users["bob"])
    for path in [
        f"/videos/{video}/transcript",
        f"/videos/{video}/suggestions",
        f"/clips/{clip_id}",
        f"/clips/{clip_id}/renders",
        f"/clips/{clip_id}/download?revision=1",
    ]:
        assert client.get("/api/v1" + path).status_code == 404
    assert (
        client.post(
            "/api/v1/clips", json={"suggestion_id": suggestion}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/clips/{clip_id}", json=prefs, headers={**headers, "If-Match": '"1"'}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/clips/{clip_id}/render", json={"revision": 1}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/jobs/{job}/renders", json={"clip_ids": [str(clip_id)]}, headers=headers
        ).status_code
        == 404
    )


def test_caption_preset_format_and_revision_contract_rejects_unimplemented_values(
    editor_http, selected
):
    client, _, headers, _, _, _, clip_id, _ = editor_http
    test_rendering.render_selected(selected)
    prefs = client.get(f"/api/v1/clips/{clip_id}").json()["preferences"]
    for patch in [
        {"preset": "neon"},
        {"aspect_ratio": "16:9"},
        {"format": "webm"},
        {"end_ms": 200},
        {"words": [{"text": "overlap", "start_ms": 0, "end_ms": 99999}]},
    ]:
        assert (
            client.patch(
                f"/api/v1/clips/{clip_id}",
                json={**prefs, **patch},
                headers={**headers, "If-Match": '"1"'},
            ).status_code
            == 422
        )
    assert client.patch(f"/api/v1/clips/{clip_id}", json=prefs, headers=headers).status_code == 422
    no_csrf = client.patch(
        f"/api/v1/clips/{clip_id}",
        json=prefs,
        headers={"Origin": "http://localhost:3000", "If-Match": '"1"'},
    )
    assert no_csrf.status_code == 403
