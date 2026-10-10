import asyncio
import json
import uuid as uuid_mod
from pathlib import Path

import pytest

from app.core.db import init_db
from app.models import Task
from app.tasks.manager import manager
from app.utils.tasklog import remove_log

_created: list = []


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
def clean_manager():
    manager._running_uuid = None
    manager._proc = None
    yield
    manager._running_uuid = None
    manager._proc = None
    if _created:
        Task.delete().where(Task.uuid.in_(list(_created))).execute()
        _created.clear()


def make_task(tmp_path: Path, *, status="pending", with_result=False):
    src = tmp_path / f"in-{uuid_mod.uuid4().hex}.mp4"
    src.write_bytes(b"x")
    out = tmp_path / f"out-{uuid_mod.uuid4().hex}.mkv"
    if with_result:
        out.write_bytes(b"y")
    params = {"input": str(src), "output": str(out)}
    u = uuid_mod.uuid4().hex
    init_db([Task])
    Task.create(
        uuid=u,
        name=src.name,
        status=status,
        progress=100,
        params=json.dumps(params),
        result=str(out) if with_result else None,
    )
    _created.append(u)
    return u, out


# --- pause_pending ----------------------------------------------------------

def test_pause_pending_moves_only_pending_to_paused(tmp_path):
    pending, _ = make_task(tmp_path, status="pending")
    running, _ = make_task(tmp_path, status="running")
    paused, _ = make_task(tmp_path, status="paused")
    completed, _ = make_task(tmp_path, status="completed")

    try:
        count = asyncio.run(manager.pause_pending())

        assert count == 1
        assert Task.get(Task.uuid == pending).status == "paused"
        assert Task.get(Task.uuid == running).status == "running"
        assert Task.get(Task.uuid == paused).status == "paused"
        assert Task.get(Task.uuid == completed).status == "completed"
    finally:
        for u in (pending, running, paused, completed):
            remove_log(u)


def test_pause_pending_with_nothing_pending_returns_zero(tmp_path):
    completed, _ = make_task(tmp_path, status="completed")
    try:
        assert asyncio.run(manager.pause_pending()) == 0
    finally:
        remove_log(completed)


# --- delete_by_status -------------------------------------------------------

def test_delete_by_status_removes_records_and_keeps_files(tmp_path):
    first, out1 = make_task(tmp_path, status="completed", with_result=True)
    second, out2 = make_task(tmp_path, status="completed", with_result=True)

    try:
        count = asyncio.run(manager.delete_by_status(("completed",)))

        assert count == 2
        assert not Task.select().where(Task.uuid.in_([first, second])).exists()
        assert out1.is_file()
        assert out2.is_file()
    finally:
        remove_log(first)
        remove_log(second)


def test_delete_by_status_with_result_removes_files(tmp_path):
    first, out1 = make_task(tmp_path, status="completed", with_result=True)
    second, out2 = make_task(tmp_path, status="completed", with_result=True)

    try:
        count = asyncio.run(
            manager.delete_by_status(("completed",), with_result=True)
        )

        assert count == 2
        assert not Task.select().where(Task.uuid.in_([first, second])).exists()
        assert not out1.exists()
        assert not out2.exists()
    finally:
        remove_log(first)
        remove_log(second)


def test_delete_by_status_only_matches_given_statuses(tmp_path):
    completed, _ = make_task(tmp_path, status="completed")
    failed, _ = make_task(tmp_path, status="failed")
    pending, _ = make_task(tmp_path, status="pending")
    running, _ = make_task(tmp_path, status="running")

    try:
        count = asyncio.run(manager.delete_by_status(("completed", "failed")))

        assert count == 2
        assert not Task.select().where(Task.uuid.in_([completed, failed])).exists()
        assert Task.select().where(Task.uuid == pending).exists()
        assert Task.select().where(Task.uuid == running).exists()
    finally:
        for u in (completed, failed, pending, running):
            remove_log(u)


def test_delete_by_status_never_removes_running(tmp_path):
    running, _ = make_task(tmp_path, status="running")

    try:
        count = asyncio.run(manager.delete_by_status(("running",)))

        assert count == 0
        assert Task.select().where(Task.uuid == running).exists()
    finally:
        remove_log(running)
