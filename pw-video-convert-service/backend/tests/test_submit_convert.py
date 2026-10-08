import asyncio
import json
from pathlib import Path

from app.api.schemas import TaskCreate
from app.core.db import init_db
from app.models import Task
from app.tasks.manager import manager
from app.utils.tasklog import log_path, remove_log


def test_submit_convert_persists_resolved_params(tmp_path: Path):
    src = tmp_path / "movie.mp4"
    src.write_bytes(b"x")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    input_path = src.resolve()
    output_path = (out_dir / "movie.mkv").resolve()
    body = TaskCreate(input=str(src), quality=7, container="mkv", software=True)

    init_db([Task])
    uuid = asyncio.run(manager.submit_convert(body, input_path, output_path))

    row = Task.get(Task.uuid == uuid)
    try:
        assert row.name == "movie.mp4"
        assert row.status == "pending"
        assert row.progress == 0
        assert json.loads(row.params) == {
            "input": str(input_path),
            "output": str(output_path),
            "quality": 7,
            "container": "mkv",
            "software": True,
            "resolution": None,
        }
        assert log_path(uuid).is_file()
    finally:
        row.delete_instance()
        remove_log(uuid)


def test_submit_convert_stores_resolution(tmp_path: Path):
    src = tmp_path / "movie.mp4"
    src.write_bytes(b"x")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    input_path = src.resolve()
    output_path = (out_dir / "movie.mkv").resolve()
    body = TaskCreate(input=str(src), resolution=[1280, 720])

    init_db([Task])
    uuid = asyncio.run(manager.submit_convert(body, input_path, output_path))

    row = Task.get(Task.uuid == uuid)
    try:
        assert json.loads(row.params)["resolution"] == [1280, 720]
    finally:
        row.delete_instance()
        remove_log(uuid)
