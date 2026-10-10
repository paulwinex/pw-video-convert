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
        self.delete_calls = []
        self.pause_calls = []
        self.start_calls = []
        self.stop_calls = []
        self.pause_pending_calls = 0
        self.bulk_delete_calls = []
        self.pause_result = True
        self.start_result = True
        self.stop_result = True
        self.pause_pending_result = 0
        self.bulk_delete_result = 0

    async def submit_convert(self, body, input_path: Path, output_path: Path) -> str:
        self.calls.append((body, input_path, output_path))
        return "stub-uuid"

    async def list_tasks(self):
        return []

    async def delete_task(self, task_uuid: str, with_result: bool = False) -> bool:
        self.delete_calls.append((task_uuid, with_result))
        return True

    async def pause_task(self, task_uuid: str) -> bool:
        self.pause_calls.append(task_uuid)
        return self.pause_result

    async def start_task(self, task_uuid: str) -> bool:
        self.start_calls.append(task_uuid)
        return self.start_result

    async def stop_task(self, task_uuid: str) -> bool:
        self.stop_calls.append(task_uuid)
        return self.stop_result

    async def pause_pending(self) -> int:
        self.pause_pending_calls += 1
        return self.pause_pending_result

    async def delete_by_status(self, statuses, with_result: bool = False) -> int:
        self.bulk_delete_calls.append((tuple(statuses), with_result))
        return self.bulk_delete_result


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


def test_output_resolves_away_from_input_on_collision(
    client, tmp_path, monkeypatch
):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(routes, "DEFAULT_OUTPUT_DIR", root)
    src = root / "src.mkv"
    src.write_bytes(b"x")

    r = client.post("/tasks", json={"input": str(src), "container": "mkv"})

    assert r.status_code == 200
    _, _, output_path = client.stub.calls[0]
    assert output_path == (root / "src.av1.mkv").resolve()
    assert output_path != src.resolve()


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
    # different dir than source -> <stem>.av1.<ext>
    assert output_path == (DEFAULT_OUTPUT_DIR / "src.av1.mp4").resolve()
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


def test_create_subfolder_output_without_slash_is_dir(
    client, tmp_path, monkeypatch
):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(routes, "DEFAULT_OUTPUT_DIR", root)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")

    r = client.post("/tasks", json={"input": str(src), "output": "subdir"})

    assert r.status_code == 200
    _, _, output_path = client.stub.calls[0]
    assert output_path == (root / "subdir" / "src.av1.mkv").resolve()
    assert output_path.is_relative_to(root.resolve())


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
    assert output_path == (root / "subdir" / "custom.mkv" / "src.av1.mkv").resolve()
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
    assert output_path == (root / "subdir" / "src.av1.mkv").resolve()
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
    assert output_path == (root / "src.av1.mkv").resolve()
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


def test_resolution_valid_is_accepted(client, tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")

    r = client.post("/tasks", json={"input": str(src), "resolution": [1920, 1080]})

    assert r.status_code == 200
    body, _, _ = client.stub.calls[0]
    assert body.resolution == [1920, 1080]


@pytest.mark.parametrize("bad", [
    "1920", "1920x1080", "abc", [1920], [1920, 1080, 720], [0, 1080],
    [1920, -1], ["a", "b"], 1920,
])
def test_bad_resolution_is_422(client, bad):
    r = client.post("/tasks", json={"input": "/tmp/x.mp4", "resolution": bad})
    assert r.status_code == 422


def test_resolution_defaults_to_none(client, tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")

    r = client.post("/tasks", json={"input": str(src)})

    assert r.status_code == 200
    body, _, _ = client.stub.calls[0]
    assert body.resolution is None


def test_relative_input_resolves_under_user_root(client, tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    src = root / "sub" / "clip.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(routes.filesystem, "get_user_root", lambda: root)

    r = client.post("/tasks", json={"input": "sub/clip.mp4"})

    assert r.status_code == 200
    _, input_path, _ = client.stub.calls[0]
    assert input_path == src.resolve()


def test_absolute_input_is_not_prefixed_with_user_root(
    client, tmp_path, monkeypatch
):
    root = tmp_path / "root"
    root.mkdir()
    src = tmp_path / "abs.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(routes.filesystem, "get_user_root", lambda: root)

    r = client.post("/tasks", json={"input": str(src)})

    assert r.status_code == 200
    _, input_path, _ = client.stub.calls[0]
    assert input_path == src.resolve()


def test_relative_input_missing_under_user_root_is_400(
    client, tmp_path, monkeypatch
):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(routes.filesystem, "get_user_root", lambda: root)

    r = client.post("/tasks", json={"input": "sub/nope.mp4"})

    assert r.status_code == 400
    assert "input file not found" in r.json()["detail"]
    assert client.stub.calls == []


def test_delete_defaults_to_keeping_result(client):
    r = client.delete("/tasks/abc")

    assert r.status_code == 200
    assert client.stub.delete_calls == [("abc", False)]


def test_delete_forwards_with_result_flag(client):
    r = client.delete("/tasks/abc?with_result=true")

    assert r.status_code == 200
    assert client.stub.delete_calls == [("abc", True)]


def test_pause_task_ok(client):
    r = client.post("/tasks/abc/pause")

    assert r.status_code == 200
    assert client.stub.pause_calls == ["abc"]


def test_pause_task_conflict_when_not_pausable(client):
    client.stub.pause_result = False

    r = client.post("/tasks/abc/pause")

    assert r.status_code == 409


def test_start_task_ok(client):
    r = client.post("/tasks/abc/start")

    assert r.status_code == 200
    assert client.stub.start_calls == ["abc"]


def test_start_task_conflict_when_not_restartable(client):
    client.stub.start_result = False

    r = client.post("/tasks/abc/start")

    assert r.status_code == 409


def test_stop_task_ok(client):
    r = client.post("/tasks/abc/stop")

    assert r.status_code == 200
    assert client.stub.stop_calls == ["abc"]


def test_stop_task_conflict_when_not_running(client):
    client.stub.stop_result = False

    r = client.post("/tasks/abc/stop")

    assert r.status_code == 409


def test_pause_unstarted_returns_count(client):
    client.stub.pause_pending_result = 3

    r = client.post("/tasks/pause-unstarted")

    assert r.status_code == 200
    assert r.json() == {"count": 3}
    assert client.stub.pause_pending_calls == 1


def test_delete_completed_forwards_with_result_flag(client):
    client.stub.bulk_delete_result = 2

    r = client.delete("/tasks/completed?with_result=true")

    assert r.status_code == 200
    assert r.json() == {"count": 2}
    assert client.stub.bulk_delete_calls == [(("completed",), True)]


def test_delete_completed_defaults_to_keeping_files(client):
    r = client.delete("/tasks/completed")

    assert r.status_code == 200
    assert client.stub.bulk_delete_calls == [(("completed",), False)]


def test_delete_failed_forwards_with_result_flag(client):
    r = client.delete("/tasks/failed?with_result=true")

    assert r.status_code == 200
    assert client.stub.bulk_delete_calls == [(("failed",), True)]
