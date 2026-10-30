import asyncio
import json
from pathlib import Path

import pytest

from app.api.schemas import TaskCreate
from app.core.db import init_db
from app.models import Task
from app.tasks.manager import manager
from app.utils.tasklog import log_path, remove_log


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    from app.core import db as db_module

    target = db_module.db
    original = target.database
    target.close()
    target.init(tmp_path / "tasks.db")
    target.connect(reuse_if_open=True)
    target.create_tables([Task])
    yield
    target.close()
    target.init(original)


@pytest.fixture(autouse=True)
def clean_submit_q():
    while not manager._submit_q.empty():
        manager._submit_q.get_nowait()
    manager._queued.clear()
    manager._running_uuid = None
    manager._proc = None
    yield
    while not manager._submit_q.empty():
        manager._submit_q.get_nowait()
    manager._queued.clear()


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
            "audio": None,
            "audio_add": [],
        }
        assert log_path(uuid).is_file()
    finally:
        row.delete_instance()
        remove_log(uuid)


def test_submit_convert_stores_source_size(tmp_path: Path):
    src = tmp_path / "movie.mp4"
    src.write_bytes(b"x" * 765)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    input_path = src.resolve()
    output_path = (out_dir / "movie.mkv").resolve()
    body = TaskCreate(input=str(src), software=True)

    init_db([Task])
    uuid = asyncio.run(manager.submit_convert(body, input_path, output_path))

    row = Task.get(Task.uuid == uuid)
    try:
        assert json.loads(row.data) == {"source_size": 765}
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


def test_submit_convert_stores_audio_selection(tmp_path: Path):
    src = tmp_path / "movie.mp4"
    src.write_bytes(b"x")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    input_path = src.resolve()
    output_path = (out_dir / "movie.mkv").resolve()
    body = TaskCreate(input=str(src), audio=[1, 3])

    init_db([Task])
    uuid = asyncio.run(manager.submit_convert(body, input_path, output_path))

    row = Task.get(Task.uuid == uuid)
    try:
        assert json.loads(row.params)["audio"] == [1, 3]
    finally:
        row.delete_instance()
        remove_log(uuid)


def test_submit_convert_created_paused(tmp_path: Path):
    src = tmp_path / "movie.mp4"
    src.write_bytes(b"x")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    input_path = src.resolve()
    output_path = (out_dir / "movie.mkv").resolve()
    body = TaskCreate(input=str(src), paused=True)

    init_db([Task])
    uuid = asyncio.run(manager.submit_convert(body, input_path, output_path))

    try:
        row = Task.get(Task.uuid == uuid)
        assert row.status == "paused"
        # paused tasks must not enter the execution queue
        assert manager._submit_q.empty()
        assert uuid not in manager._queued
        assert "created paused" in log_path(uuid).read_text(encoding="utf-8")
    finally:
        row.delete_instance()
        remove_log(uuid)


def test_submit_convert_default_is_queued(tmp_path: Path):
    src = tmp_path / "movie.mp4"
    src.write_bytes(b"x")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    input_path = src.resolve()
    output_path = (out_dir / "movie.mkv").resolve()
    body = TaskCreate(input=str(src))

    init_db([Task])
    uuid = asyncio.run(manager.submit_convert(body, input_path, output_path))

    try:
        row = Task.get(Task.uuid == uuid)
        assert row.status == "pending"
        assert not manager._submit_q.empty()
    finally:
        row.delete_instance()
        remove_log(uuid)
        while not manager._submit_q.empty():
            manager._submit_q.get_nowait()
        manager._queued.clear()
