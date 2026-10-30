from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes
from app.api.routes import router
from app.tasks import filesystem


@pytest.fixture
def probe_client(tmp_path: Path) -> TestClient:
    root = tmp_path / "root"
    root.mkdir()
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def user_root(probe_client: TestClient, tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    monkeypatch.setattr(routes.filesystem, "get_user_root", lambda: root)
    return root


def test_probe_reports_1based_tracks_with_tags(probe_client, audio_clip: Path):
    r = probe_client.get("/probe", params={"path": str(audio_clip)})

    assert r.status_code == 200
    body = r.json()
    assert [t["track"] for t in body["audio"]] == [1, 2]
    first, second = body["audio"]
    assert first["language"] == "rus"
    assert first["title"] == "Original"
    assert first["codec"] == "aac"
    assert second["language"] == "eng"
    assert second["title"] == "Commentary"


def test_probe_missing_file_is_404(probe_client, tmp_path):
    r = probe_client.get("/probe", params={"path": str(tmp_path / "nope.mkv")})

    assert r.status_code == 404
    assert "input file not found" in r.json()["detail"]


def test_probe_unreadable_media_is_422(probe_client, tmp_path):
    bad = tmp_path / "bad.mkv"
    bad.write_bytes(b"not a video")

    r = probe_client.get("/probe", params={"path": str(bad)})

    assert r.status_code == 422
    assert "could not probe" in r.json()["detail"]


def test_probe_relative_path_resolves_under_user_root(
    probe_client, user_root: Path, audio_clip: Path
):
    (user_root / "clip.mkv").symlink_to(audio_clip)

    r = probe_client.get("/probe", params={"path": "clip.mkv"})

    assert r.status_code == 200
    assert len(r.json()["audio"]) == 2


def test_probe_remaps_client_path_prefix(
    probe_client, tmp_path, audio_clip: Path, monkeypatch
):
    local_root = tmp_path / "local"
    local_root.mkdir()
    monkeypatch.setattr(routes, "REMAP_PATH", local_root)
    (local_root / "media.mkv").symlink_to(audio_clip)

    r = probe_client.get(
        "/probe",
        params={"path": "/mnt/NAS/media.mkv", "remap_path": "/mnt/NAS"},
    )

    assert r.status_code == 200
    assert len(r.json()["audio"]) == 2


def test_probe_remap_survives_symlinked_client_prefix(
    probe_client, tmp_path, audio_clip: Path, monkeypatch
):
    """A client prefix that exists locally as a dangling symlink must not
    swallow the substitution: remap applies before resolving."""
    srv_root = tmp_path / "srv-nas"
    srv_root.mkdir()
    monkeypatch.setattr(routes, "REMAP_PATH", srv_root)
    (srv_root / "media.mkv").symlink_to(audio_clip)

    local_link = tmp_path / "naslink"
    local_link.symlink_to(tmp_path / "nowhere")

    r = probe_client.get(
        "/probe",
        params={"path": f"{local_link}/media.mkv", "remap_path": str(local_link)},
    )

    assert r.status_code == 200
    assert len(r.json()["audio"]) == 2


def test_probe_relative_path_is_not_remapped(
    probe_client, user_root: Path, tmp_path, audio_clip: Path, monkeypatch
):
    """Server-relative paths resolve under the user root regardless of remap."""
    monkeypatch.setattr(routes, "REMAP_PATH", tmp_path / "elsewhere")
    (user_root / "clip.mkv").symlink_to(audio_clip)

    r = probe_client.get(
        "/probe",
        params={"path": "clip.mkv", "remap_path": str(tmp_path)},
    )

    assert r.status_code == 200
    assert len(r.json()["audio"]) == 2
