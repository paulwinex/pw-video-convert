import asyncio
import json
import uuid as uuid_mod
from pathlib import Path

import pytest

from app.api.schemas import TaskCreate
from app.core.db import init_db
from app.models import Task
from app.tasks.manager import (
    JobSpec,
    manager,
    migrate_queue_order,
)
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


def make_task(tmp_path: Path, *, status="pending", queue_order=None, name=None):
    src = tmp_path / f"in-{uuid_mod.uuid4().hex}.mp4"
    src.write_bytes(b"x")
    u = uuid_mod.uuid4().hex
    Task.create(
        uuid=u,
        name=name or src.name,
        status=status,
        progress=0,
        queue_order=queue_order,
        params=json.dumps(
            {
                "input": str(src),
                "output": str(tmp_path / "out.mkv"),
                "quality": 5,
                "container": "mkv",
                "software": True,
                "resolution": None,
            }
        ),
    )
    _created.append(u)
    return u


def enqueue(*uuids):
    for u in uuids:
        manager._submit_q.put_nowait(JobSpec(u, "t", {}))
        manager._queued.add(u)


def names_by_position():
    return [i["name"] for i in asyncio.run(manager.list_tasks())]


# --- display order -----------------------------------------------------------

def test_list_order_is_queue_position_desc(tmp_path):
    init_db([Task])
    top = make_task(tmp_path, queue_order=5, name="top")
    running = make_task(tmp_path, status="running", queue_order=4, name="running")
    done = make_task(tmp_path, status="completed", queue_order=3, name="done")
    bottom = make_task(tmp_path, queue_order=2, name="bottom")

    # one stable list: status does not group rows anymore
    assert names_by_position() == ["top", "running", "done", "bottom"]
    assert {top, running, done, bottom}


def test_status_change_keeps_row_position(tmp_path):
    init_db([Task])
    a = make_task(tmp_path, queue_order=2, name="a")
    b = make_task(tmp_path, queue_order=1, name="b")
    c = make_task(tmp_path, queue_order=0, name="c")

    Task.update(status="completed", progress=100).where(Task.uuid == b).execute()

    assert names_by_position() == ["a", "b", "c"]


# --- submission / FIFO execution ---------------------------------------------

def test_new_task_lands_on_top_of_the_list(tmp_path):
    init_db([Task])
    old = make_task(tmp_path, queue_order=0, name="old")
    src = tmp_path / "new.mp4"
    src.write_bytes(b"x" * 10)
    body = TaskCreate(input=str(src))

    asyncio.run(manager.submit_convert(body, src, tmp_path / "new.mkv"))

    items = asyncio.run(manager.list_tasks())
    assert [i["name"] for i in items][:2] == ["new.mp4", "old"]
    assert Task.get(Task.uuid == old).queue_order == 0


def test_execution_takes_the_bottom_pending_task_first(tmp_path):
    init_db([Task])
    top = make_task(tmp_path, queue_order=5, name="top")
    mid = make_task(tmp_path, queue_order=4, name="mid")
    done = make_task(tmp_path, status="completed", queue_order=3, name="done")
    bottom = make_task(tmp_path, queue_order=2, name="bottom")

    asyncio.run(manager.resume())

    # FIFO: the bottom-most pending row runs first, finished rows keep places
    assert [s.uuid for s in _drain_submit_q()] == [bottom, mid, top]


# --- reorder ------------------------------------------------------------------

def test_reorder_moves_pending_row_and_rebuilds_queue(tmp_path):
    init_db([Task])
    a = make_task(tmp_path, queue_order=2, name="a")
    b = make_task(tmp_path, queue_order=1, name="b")
    c = make_task(tmp_path, queue_order=0, name="c")
    enqueue(c, b, a)  # current execution order

    asyncio.run(manager.reorder([a, b, c]))

    assert names_by_position() == ["a", "b", "c"]
    assert [s.uuid for s in _drain_submit_q()] == [c, b, a]
    assert Task.get(Task.uuid == a).queue_order == 2
    assert Task.get(Task.uuid == c).queue_order == 0


def test_reorder_allows_moving_paused_and_canceled(tmp_path):
    init_db([Task])
    paused = make_task(tmp_path, status="paused", queue_order=2, name="paused")
    canceled = make_task(tmp_path, status="canceled", queue_order=1, name="canceled")
    done = make_task(tmp_path, status="completed", queue_order=0, name="done")

    asyncio.run(manager.reorder([done, canceled, paused]))

    assert names_by_position() == ["done", "canceled", "paused"]


def test_reorder_rejects_changing_finished_order(tmp_path):
    init_db([Task])
    a = make_task(tmp_path, queue_order=3, name="a")
    done1 = make_task(tmp_path, status="completed", queue_order=2, name="done1")
    done2 = make_task(tmp_path, status="completed", queue_order=1, name="done2")
    b = make_task(tmp_path, queue_order=0, name="b")

    # done2 moved above done1 — frozen rows changed relative order
    with pytest.raises(ValueError):
        asyncio.run(manager.reorder([a, done2, done1, b]))

    assert names_by_position() == ["a", "done1", "done2", "b"]


def test_reorder_allows_inserting_between_frozen_rows(tmp_path):
    init_db([Task])
    done1 = make_task(tmp_path, status="completed", queue_order=2, name="done1")
    done2 = make_task(tmp_path, status="completed", queue_order=1, name="done2")
    pend = make_task(tmp_path, queue_order=0, name="pend")

    # moving a pending row between the finished ones is fine
    asyncio.run(manager.reorder([done1, pend, done2]))

    assert names_by_position() == ["done1", "pend", "done2"]
    assert Task.get(Task.uuid == done1).queue_order == 2
    assert Task.get(Task.uuid == pend).queue_order == 1
    assert Task.get(Task.uuid == done2).queue_order == 0


def test_reorder_skips_unknown_and_appends_unlisted(tmp_path):
    init_db([Task])
    a = make_task(tmp_path, queue_order=1, name="a")
    b = make_task(tmp_path, queue_order=0, name="b")

    asyncio.run(manager.reorder([a, "nope"]))

    # b was not listed: keeps relative order after the listed ones
    assert names_by_position() == ["a", "b"]
    assert Task.get(Task.uuid == a).queue_order == 1
    assert Task.get(Task.uuid == b).queue_order == 0


# --- restart of a paused task --------------------------------------------------

def test_start_task_keeps_position_and_queue_priority(tmp_path):
    init_db([Task])
    a = make_task(tmp_path, queue_order=2, name="a")
    paused = make_task(tmp_path, status="paused", queue_order=1, name="paused")
    c = make_task(tmp_path, queue_order=0, name="c")
    enqueue(c, a)

    assert asyncio.run(manager.start_task(paused)) is True

    assert names_by_position() == ["a", "paused", "c"]
    # paused keeps its position: it must run before a even though it was
    # enqueued last
    assert [s.uuid for s in _drain_submit_q()] == [c, paused, a]


# --- data migration -------------------------------------------------------------

def test_migration_assigns_positions_in_legacy_order(tmp_path):
    init_db([Task])
    running = make_task(tmp_path, status="running", name="running")
    pend_hi = make_task(tmp_path, queue_order=0, name="pend-hi")
    pend_lo = make_task(tmp_path, queue_order=1, name="pend-lo")
    done_older = make_task(tmp_path, status="completed", name="done-older")
    done_newer = make_task(tmp_path, status="completed", name="done-newer")

    # legacy display order: running, pending by execution order, finished
    # newest first (done-newer was created last)
    moved = migrate_queue_order()

    assert moved == 5
    expected = ["running", "pend-hi", "pend-lo", "done-newer", "done-older"]
    assert names_by_position() == expected
    qo = {t.name: t.queue_order for t in Task.select()}
    assert qo["running"] == 4
    assert qo["pend-hi"] == 3
    assert qo["pend-lo"] == 2
    assert qo["done-newer"] == 1
    assert qo["done-older"] == 0
    assert migrate_queue_order() == 0  # idempotent
