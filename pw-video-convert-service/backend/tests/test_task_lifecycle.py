import asyncio
import json
import uuid as uuid_mod
from pathlib import Path

import pytest

from app.core.db import init_db
from app.models import Task
from app.tasks.manager import JobSpec, manager
from app.utils.tasklog import remove_log


def _drain_submit_q():
    specs = []
    while not manager._submit_q.empty():
        specs.append(manager._submit_q.get_nowait())
    return specs


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
    _drain_submit_q()
    manager._queued.clear()
    manager._running_uuid = None
    manager._proc = None
    yield
    _drain_submit_q()
    manager._queued.clear()
    manager._running_uuid = None
    manager._proc = None
    if _created:
        Task.delete().where(Task.uuid.in_(list(_created))).execute()
        _created.clear()


def make_task(tmp_path: Path, *, status="pending", valid=True):
    src = tmp_path / f"in-{uuid_mod.uuid4().hex}.mp4"
    src.write_bytes(b"x")
    out = tmp_path / f"out-{uuid_mod.uuid4().hex}.mkv"
    if valid:
        params = {
            "input": str(src),
            "output": str(out),
            "quality": 5,
            "container": "mkv",
            "software": True,
            "resolution": None,
        }
    else:
        params = {"input": str(src)}
    u = uuid_mod.uuid4().hex
    init_db([Task])
    Task.create(
        uuid=u,
        name=src.name,
        status=status,
        progress=0,
        params=json.dumps(params) if params is not None else None,
    )
    _created.append(u)
    return u, out


class FakeProc:
    def __init__(self):
        self.terminated = False
        self.alive = True

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.terminated = True
        self.alive = False

    def kill(self):
        self.alive = False

    def join(self, timeout=None):
        self.alive = False


# --- resume -----------------------------------------------------------------

def test_resume_requeues_pending_and_running_in_creation_order(tmp_path):
    init_db([Task])
    first, _ = make_task(tmp_path, status="pending")
    second, _ = make_task(tmp_path, status="running")
    completed, _ = make_task(tmp_path, status="completed")
    failed, _ = make_task(tmp_path, status="failed")
    paused, _ = make_task(tmp_path, status="paused")
    canceled, _ = make_task(tmp_path, status="canceled")

    try:
        asyncio.run(manager.resume())

        assert [s.uuid for s in _drain_submit_q()] == [first, second]
        assert Task.get(Task.uuid == first).status == "pending"
        assert Task.get(Task.uuid == second).status == "pending"
        assert Task.get(Task.uuid == completed).status == "completed"
        assert Task.get(Task.uuid == failed).status == "failed"
        assert Task.get(Task.uuid == paused).status == "paused"
        assert Task.get(Task.uuid == canceled).status == "canceled"
    finally:
        for u in (first, second, completed, failed, paused, canceled):
            remove_log(u)


def test_resume_marks_task_with_unusable_params_failed(tmp_path):
    init_db([Task])
    broken, _ = make_task(tmp_path, status="pending", valid=False)

    try:
        asyncio.run(manager.resume())

        assert _drain_submit_q() == []
        t = Task.get(Task.uuid == broken)
        assert t.status == "failed"
        assert t.error
    finally:
        remove_log(broken)


def test_resume_with_nothing_to_do_is_noop():
    init_db([Task])
    asyncio.run(manager.resume())
    assert _drain_submit_q() == []


# --- pause ------------------------------------------------------------------

def test_pause_pending_task_sets_paused(tmp_path):
    u, _ = make_task(tmp_path, status="pending")
    try:
        assert asyncio.run(manager.pause_task(u)) is True
        assert Task.get(Task.uuid == u).status == "paused"
    finally:
        remove_log(u)


@pytest.mark.parametrize("status", ["running", "paused", "completed", "failed", "canceled"])
def test_pause_rejects_non_pending_task(tmp_path, status):
    u, _ = make_task(tmp_path, status=status)
    try:
        assert asyncio.run(manager.pause_task(u)) is False
        assert Task.get(Task.uuid == u).status == status
    finally:
        remove_log(u)


def test_pause_unknown_task_returns_false():
    init_db([Task])
    assert asyncio.run(manager.pause_task("nope")) is False


# --- start ------------------------------------------------------------------

@pytest.mark.parametrize("status", ["paused", "canceled"])
def test_start_requeues_resumable_task(tmp_path, status):
    u, out = make_task(tmp_path, status=status)
    Task.update(progress=42, result=str(out)).where(Task.uuid == u).execute()
    try:
        assert asyncio.run(manager.start_task(u)) is True

        t = Task.get(Task.uuid == u)
        assert t.status == "pending"
        assert t.progress == 0
        assert t.result is None
        assert [s.uuid for s in _drain_submit_q()] == [u]
    finally:
        remove_log(u)


@pytest.mark.parametrize("status", ["pending", "running", "completed", "failed"])
def test_start_rejects_non_restartable_task(tmp_path, status):
    u, _ = make_task(tmp_path, status=status)
    try:
        assert asyncio.run(manager.start_task(u)) is False
        assert Task.get(Task.uuid == u).status == status
    finally:
        remove_log(u)


def test_start_does_not_enqueue_twice(tmp_path):
    u, _ = make_task(tmp_path, status="paused")
    try:
        asyncio.run(manager.start_task(u))
        asyncio.run(manager.start_task(u))
        assert [s.uuid for s in _drain_submit_q()] == [u]
    finally:
        remove_log(u)


# --- stop -------------------------------------------------------------------

def test_stop_running_task_cancels_and_removes_partial_output(tmp_path):
    u, out = make_task(tmp_path, status="running")
    out.write_bytes(b"partial")
    fake = FakeProc()
    manager._running_uuid = u
    manager._proc = fake
    try:
        assert asyncio.run(manager.stop_task(u)) is True

        t = Task.get(Task.uuid == u)
        assert t.status == "canceled"
        assert t.result is None
        assert not out.exists()
        assert fake.terminated is True
        assert manager._running_uuid is None
    finally:
        remove_log(u)


def test_stop_non_running_task_is_rejected(tmp_path):
    u, _ = make_task(tmp_path, status="pending")
    try:
        assert asyncio.run(manager.stop_task(u)) is False
        assert Task.get(Task.uuid == u).status == "pending"
    finally:
        remove_log(u)


def test_stop_unknown_task_returns_false():
    init_db([Task])
    assert asyncio.run(manager.stop_task("nope")) is False


# --- dispatcher / pump guards ----------------------------------------------

def test_dispatcher_skips_tasks_that_are_not_pending(tmp_path, monkeypatch):
    init_db([Task])
    pending, _ = make_task(tmp_path, status="pending")
    paused, _ = make_task(tmp_path, status="paused")
    started = []

    async def fake_start(spec):
        started.append(spec.uuid)

    monkeypatch.setattr(manager, "_start_process", fake_start)

    async def run():
        loop_task = asyncio.create_task(manager._dispatcher_loop())
        await manager._submit_q.put(JobSpec(pending, "a", {}))
        await manager._submit_q.put(JobSpec(paused, "b", {}))
        await asyncio.sleep(0.2)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(run())
        assert started == [pending]
    finally:
        for u in (pending, paused):
            remove_log(u)


def test_pump_ignores_updates_for_terminal_task(tmp_path):
    init_db([Task])
    u, _ = make_task(tmp_path, status="canceled")

    async def run():
        pump_task = asyncio.create_task(manager._pump_loop())
        manager._mp_q.put({"task_uuid": u, "status": "running", "progress": 50})
        await asyncio.sleep(0.4)
        pump_task.cancel()
        try:
            await pump_task
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(run())
        assert Task.get(Task.uuid == u).status == "canceled"
    finally:
        remove_log(u)
