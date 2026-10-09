from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.tasks import filesystem


@pytest.fixture
def fs_client(tmp_path: Path) -> TestClient:
    root = tmp_path / "root"
    root.mkdir()
    (root / "clip.mp4").write_bytes(b"x")
    (root / "song.mp3").write_bytes(b"x")
    (root / "notes.txt").write_bytes(b"x")
    (root / "mystery.unknownext").write_bytes(b"x")
    (root / "sub").mkdir()
    (root / "sub" / "nested.mkv").write_bytes(b"x")
    (root / ".hidden.mp4").write_bytes(b"x")
    (root / ".secret.txt").write_bytes(b"x")
    (root / ".hidden_dir").mkdir()
    (root / ".hidden_dir" / "inside.mp4").write_bytes(b"x")

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[filesystem.get_user_root] = lambda: root
    return TestClient(app)


def names(resp) -> set[str]:
    return {e["name"] for e in resp.json()["entries"]}


def test_lists_dirs_and_files_when_no_filter(fs_client: TestClient) -> None:
    r = fs_client.get("/fs")

    assert r.status_code == 200
    assert names(r) == {
        "clip.mp4",
        "song.mp3",
        "notes.txt",
        "mystery.unknownext",
        "sub",
    }


def test_wildcard_mime_keeps_dirs_and_matching_files(fs_client: TestClient) -> None:
    r = fs_client.get("/fs", params={"mime": "video/*"})

    assert r.status_code == 200
    assert names(r) == {"clip.mp4", "sub"}


def test_exact_mime_matches_only_that_type(fs_client: TestClient) -> None:
    r = fs_client.get("/fs", params={"mime": "audio/mpeg"})

    assert r.status_code == 200
    assert names(r) == {"song.mp3", "sub"}


def test_unknown_type_excluded_when_filter_present(fs_client: TestClient) -> None:
    r = fs_client.get("/fs", params={"mime": "video/*"})

    assert r.status_code == 200
    assert "mystery.unknownext" not in names(r)


def test_hidden_files_and_dirs_are_skipped(fs_client: TestClient) -> None:
    r = fs_client.get("/fs")

    assert r.status_code == 200
    assert not any(n.startswith(".") for n in names(r))
    assert names(r) == {"clip.mp4", "song.mp3", "notes.txt", "mystery.unknownext", "sub"}


def test_multiple_mime_params_are_ored(fs_client: TestClient) -> None:
    r = fs_client.get("/fs", params=[("mime", "video/*"), ("mime", "audio/*")])

    assert r.status_code == 200
    assert names(r) == {"clip.mp4", "song.mp3", "sub"}


def test_path_escape_is_403(fs_client: TestClient) -> None:
    r = fs_client.get("/fs", params={"path": "../"})

    assert r.status_code == 403
