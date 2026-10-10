import asyncio
import json
import uuid as uuid_mod

from app.core.db import init_db
from app.models import Task
from app.tasks.manager import manager
from app.utils.tasklog import remove_log


def make_task(tmp_path, *, status="completed", result=True):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    out = tmp_path / "out.mkv"
    out.write_bytes(b"y")
    params = {"input": str(src), "output": str(out)}
    uuid = uuid_mod.uuid4().hex
    init_db([Task])
    Task.create(
        uuid=uuid,
        name="in.mp4",
        status=status,
        progress=100,
        params=json.dumps(params),
        result=str(out) if result else None,
    )
    return uuid, out


def test_delete_task_without_result_keeps_file(tmp_path):
    uuid, out = make_task(tmp_path)
    try:
        ok = asyncio.run(manager.delete_task(uuid, with_result=False))

        assert ok is True
        assert not Task.select().where(Task.uuid == uuid).exists()
        assert out.is_file()
    finally:
        remove_log(uuid)


def test_delete_task_with_result_removes_file(tmp_path):
    uuid, out = make_task(tmp_path)
    try:
        ok = asyncio.run(manager.delete_task(uuid, with_result=True))

        assert ok is True
        assert not Task.select().where(Task.uuid == uuid).exists()
        assert not out.exists()
    finally:
        remove_log(uuid)


def test_delete_task_with_result_and_no_result_path(tmp_path):
    uuid, out = make_task(tmp_path, result=False)
    try:
        ok = asyncio.run(manager.delete_task(uuid, with_result=True))

        assert ok is True
        assert not Task.select().where(Task.uuid == uuid).exists()
        assert out.is_file()
    finally:
        remove_log(uuid)


def test_delete_running_task_keeps_file(tmp_path):
    uuid, out = make_task(tmp_path, status="running")
    try:
        ok = asyncio.run(manager.delete_task(uuid, with_result=True))

        assert ok is False
        assert Task.select().where(Task.uuid == uuid).exists()
        assert out.is_file()
    finally:
        task = Task.get_or_none(Task.uuid == uuid)
        if task:
            task.delete_instance()
        remove_log(uuid)
