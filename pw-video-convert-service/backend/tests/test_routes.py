import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps, routes
from app.api.routes import router
from app.core.config import DEFAULT_OUTPUT_DIR


class StubManager:
    def __init__(self):
        self.calls = []

    async def submit_convert(self, body, input_path: Path, output_path: Path) -> str:
        self.calls.append((body, input_path, output_path))
        return "stub-uuid"

    async def list_tasks(self):
        return []

    async def delete_task(self, task_uuid: str) -> bool:
        return True


@pytest.fixture
def client():
    stub = StubManager()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[deps.get_manager] = lambda: stub
    c = TestClient(app)
    c.stub = stub
    return c


def test_quality_out_of_range_is_422(client):
    r = client.post("/tasks", json={"input": "/tmp/x.mp4", "quality": 0})
    assert r.status_code == 422
    r = client.post("/tasks", json={"input": "/tmp/x.mp4", "quality": 11})
    assert r.status_code == 422


def test_bad_container_is_422(client):
    r = client.post("/tasks", json={"input": "/tmp/x.mp4", "container": "avi"})
    assert r.status_code == 422


def test_missing_input_field_is_422(client):
    r = client.post("/tasks", json={"quality": 5})
    assert r.status_code == 422


def test_nonexistent_input_is_400(client, tmp_path):
    r = client.post("/tasks", json={"input": str(tmp_path / "nope.mp4")})
    assert r.status_code == 400
    assert "input file not found" in r.json()["detail"]


def test_output_equal_to_input_is_400(client, tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(routes, "DEFAULT_OUTPUT_DIR", root)
    src = root / "src.mp4"
    src.write_bytes(b"x")

    r = client.post("/tasks", json={"input": str(src), "output": "src.mp4"})
    assert r.status_code == 400
    assert "input file" in r.json()["detail"]


def test_create_resolves_default_output_dir(client, tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")

    r = client.post(
        "/tasks",
        json={"input": str(src), "quality": 7, "container": "mp4", "software": True},
    )

    assert r.status_code == 200
    assert r.json() == {"uuid": "stub-uuid", "status": "pending"}
    body, input_path, output_path = client.stub.calls[0]
    assert input_path == src.resolve()
    # different dir than source -> <stem>.<ext>, no .qN.av1 suffix
    assert output_path == (DEFAULT_OUTPUT_DIR / "src.mp4").resolve()
    assert body.quality == 7 and body.container == "mp4" and body.software is True


def test_create_absolute_output_dir_is_400(client, tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    out_dir = tmp_path / "outdir"
    out_dir.mkdir()

    r = client.post("/tasks", json={"input": str(src), "output": str(out_dir)})

    assert r.status_code == 400
    assert "relative path" in r.json()["detail"]
    assert client.stub.calls == []


def test_create_absolute_file_output_is_400(client, tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    explicit = tmp_path / "custom_name.mkv"

    r = client.post("/tasks", json={"input": str(src), "output": str(explicit)})

    assert r.status_code == 400
    assert "relative path" in r.json()["detail"]
    assert client.stub.calls == []


def test_create_relative_output_lands_under_default_dir(
    client, tmp_path, monkeypatch
):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(routes, "DEFAULT_OUTPUT_DIR", root)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")

    r = client.post("/tasks", json={"input": str(src), "output": "subdir/custom.mkv"})

    assert r.status_code == 200
    _, _, output_path = client.stub.calls[0]
    assert output_path == (root / "subdir" / "custom.mkv").resolve()
    assert output_path.is_relative_to(root.resolve())


def test_create_relative_output_dir_with_trailing_sep(
    client, tmp_path, monkeypatch
):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(routes, "DEFAULT_OUTPUT_DIR", root)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")

    r = client.post("/tasks", json={"input": str(src), "output": "subdir/"})

    assert r.status_code == 200
    _, _, output_path = client.stub.calls[0]
    assert output_path == (root / "subdir" / "src.mkv").resolve()
    assert output_path.is_relative_to(root.resolve())


def test_empty_output_resolves_to_root_dir(client, tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(routes, "DEFAULT_OUTPUT_DIR", root)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")

    r = client.post("/tasks", json={"input": str(src), "output": ""})

    assert r.status_code == 200
    _, _, output_path = client.stub.calls[0]
    assert output_path == (root / "src.mkv").resolve()
    assert output_path.is_relative_to(root.resolve())


def test_relative_output_escaping_root_is_400(client, tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(routes, "DEFAULT_OUTPUT_DIR", root)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")

    r = client.post("/tasks", json={"input": str(src), "output": "../escape.mkv"})

    assert r.status_code == 400
    assert "escapes" in r.json()["detail"]
    assert client.stub.calls == []


def test_multi_level_relative_output_escaping_root_is_400(
    client, tmp_path, monkeypatch
):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(routes, "DEFAULT_OUTPUT_DIR", root)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")

    r = client.post("/tasks", json={"input": str(src), "output": "a/../../x.mkv"})

    assert r.status_code == 400
    assert "escapes" in r.json()["detail"]
    assert client.stub.calls == []


def test_symlink_dir_escape_output_is_400(client, tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(routes, "DEFAULT_OUTPUT_DIR", root)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    try:
        os.symlink(tmp_path.parent, root / "linkdir", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    r = client.post("/tasks", json={"input": str(src), "output": "linkdir/escape.mkv"})

    assert r.status_code == 400
    assert "escapes" in r.json()["detail"]
    assert client.stub.calls == []


def test_home_expanded_output_is_400(client, tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")

    r = client.post("/tasks", json={"input": str(src), "output": "~/x.mkv"})

    assert r.status_code == 400
    assert "relative path" in r.json()["detail"]
    assert client.stub.calls == []


def test_null_byte_output_is_400(client, tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")

    r = client.post("/tasks", json={"input": str(src), "output": "a\u0000b.mkv"})

    assert r.status_code == 400
    assert client.stub.calls == []


def test_null_byte_input_is_400(client, tmp_path):
    r = client.post("/tasks", json={"input": str(tmp_path / "a\u0000b.mp4")})

    assert r.status_code == 400
    assert client.stub.calls == []
