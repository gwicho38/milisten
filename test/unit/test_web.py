import json

import pytest
from fastapi.testclient import TestClient

from milisten import library
from milisten.models import Source, SourceKind
from milisten.web import security, server

TOKEN = "test-token"


@pytest.fixture
def client(tmp_path, monkeypatch):
    audio = tmp_path / "audio"
    audio.mkdir()
    monkeypatch.setenv("MILISTEN_HOME", str(tmp_path))
    monkeypatch.setenv("MILISTEN_AUDIO", str(audio))
    library.save(
        (
            Source("https://example.com/a", "Alpha paper", SourceKind.AUTO, "ai"),
            Source("https://example.com/b", "Beta memo", SourceKind.HTML, "ma"),
        )
    )
    server.set_session_token(TOKEN)
    # base_url must be loopback: the security gate checks the Host header, so the
    # default "testserver" host is refused exactly as a real foreign host would be.
    with TestClient(server.app, base_url="http://127.0.0.1") as c:
        c.headers.update({security.TOKEN_HEADER: TOKEN})
        yield c, audio


def test_library_groups_sources_by_area(client):
    c, _ = client
    body = c.get("/api/library").json()
    assert [a["name"] for a in body["areas"]] == ["ai", "ma"]
    assert body["areas"][0]["sources"][0]["title"] == "Alpha paper"
    assert body["areas"][0]["recording"] is None


def test_library_reports_available_voices(client):
    c, _ = client
    assert "heart" in c.get("/api/library").json()["voices"]


def test_recording_is_attached_to_its_area(client):
    c, audio = client
    (audio / "ai.m4b").write_bytes(b"\0" * 2048)
    (audio / "ai.json").write_text(json.dumps({
        "version": 1, "area": "ai", "seconds": 120.0, "engine": "kokoro", "voice": "heart",
        "chapters": [{"title": "Alpha paper", "start": 0.0, "end": 120.0}],
    }))
    area = next(a for a in c.get("/api/library").json()["areas"] if a["name"] == "ai")
    assert area["recording"]["seconds"] == 120.0
    assert area["recording"]["chapters"][0]["title"] == "Alpha paper"


def test_recording_with_no_queued_sources_is_reported_as_an_orphan(client):
    c, audio = client
    (audio / "retired.m4b").write_bytes(b"\0" * 512)
    body = c.get("/api/library").json()
    assert [o["area"] for o in body["orphans"]] == ["retired"]


def test_adding_a_url_returns_the_updated_library(client):
    c, _ = client
    body = c.post("/api/sources", json={"ref": "https://example.com/c", "area": "ai"}).json()
    titles = [s["title"] for s in body["areas"][0]["sources"]]
    assert len(titles) == 2


def test_adding_a_missing_local_path_is_rejected(client):
    c, _ = client
    res = c.post("/api/sources", json={"ref": "/no/such/file.pdf"})
    assert res.status_code == 422
    assert "does not exist" in res.json()["error"]


def test_adding_an_empty_ref_is_rejected(client):
    c, _ = client
    assert c.post("/api/sources", json={"ref": "   "}).status_code == 422


def test_removing_a_source_drops_it(client):
    c, _ = client
    body = c.post("/api/sources/remove", json={"ref": "https://example.com/a"}).json()
    assert [a["name"] for a in body["areas"]] == ["ma"]


def test_preview_of_an_unqueued_ref_is_a_404(client):
    c, _ = client
    assert c.post("/api/preview", json={"ref": "https://example.com/zzz"}).status_code == 404


def test_building_an_unknown_area_is_a_404_that_lists_the_real_ones(client):
    c, _ = client
    res = c.post("/api/build", json={"area": "nope"})
    assert res.status_code == 404
    assert "ai" in res.json()["hint"]


def test_unknown_engine_is_rejected(client):
    c, _ = client
    assert c.post("/api/build", json={"area": "ai", "engine": "espeak"}).status_code == 422


def test_no_build_is_live_initially(client):
    c, _ = client
    assert c.get("/api/build").json()["live"] is None


def test_unknown_job_id_is_a_404(client):
    c, _ = client
    assert c.get("/api/build/deadbeef").status_code == 404


def test_cancelling_an_unknown_job_is_a_409(client):
    c, _ = client
    assert c.post("/api/build/deadbeef/cancel").status_code == 409


def test_deleting_a_recording_removes_audio_and_manifest(client):
    c, audio = client
    (audio / "ai.m4b").write_bytes(b"\0" * 64)
    (audio / "ai.json").write_text("{}")
    assert c.delete("/api/recordings/ai").status_code == 200
    assert not (audio / "ai.m4b").exists()
    assert not (audio / "ai.json").exists()


def test_deleting_a_missing_recording_is_a_404(client):
    c, _ = client
    assert c.delete("/api/recordings/ghost").status_code == 404


def test_area_name_cannot_escape_the_audio_directory(client):
    c, _ = client
    assert c.delete("/api/recordings/..%2f..%2fetc%2fpasswd").status_code == 404
    assert c.get("/audio/..%2f..%2fetc%2fpasswd.m4b").status_code == 404


def test_audio_advertises_byte_ranges(client):
    c, audio = client
    (audio / "ai.m4b").write_bytes(bytes(range(256)) * 4)
    res = c.get("/audio/ai.m4b")
    assert res.status_code == 200
    assert res.headers["accept-ranges"] == "bytes"


def test_audio_serves_a_partial_response_for_a_range(client):
    c, audio = client
    (audio / "ai.m4b").write_bytes(bytes(range(256)) * 4)
    res = c.get("/audio/ai.m4b", headers={"Range": "bytes=10-19"})
    assert res.status_code == 206
    assert res.headers["content-range"] == "bytes 10-19/1024"
    assert res.content == bytes(range(10, 20))


def test_missing_audio_is_a_404(client):
    c, _ = client
    assert c.get("/audio/ghost.m4b").status_code == 404


def test_api_requires_the_session_token(client):
    c, _ = client
    res = c.get("/api/library", headers={security.TOKEN_HEADER: "wrong"})
    assert res.status_code == 401
    assert "hint" in res.json()


def test_index_and_audio_do_not_require_the_token(client):
    c, audio = client
    (audio / "ai.m4b").write_bytes(b"\0" * 16)
    assert c.get("/", headers={security.TOKEN_HEADER: ""}).status_code == 200
    assert c.get("/audio/ai.m4b", headers={security.TOKEN_HEADER: ""}).status_code == 200


def test_a_foreign_host_header_is_refused(client):
    c, _ = client
    assert c.get("/api/library", headers={"Host": "evil.example.com"}).status_code == 403


def test_a_cross_origin_request_is_refused(client):
    c, _ = client
    res = c.get("/api/library", headers={"Origin": "https://evil.example.com"})
    assert res.status_code == 403


def test_loopback_origins_are_allowed():
    assert security.origin_is_loopback("http://127.0.0.1:8321")
    assert security.origin_is_loopback("http://localhost:8321")
    assert not security.origin_is_loopback("https://example.com")


def test_static_and_audio_paths_are_token_exempt():
    assert security.is_exempt("/static/app.js")
    assert security.is_exempt("/audio/ai.m4b")
    assert not security.is_exempt("/api/library")
