import asyncio
import datetime
import json
import multiprocessing as mp
import uuid as uuid_mod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from peewee import DoesNotExist, fn

from app.api.schemas import TaskCreate
from app.core.db import db
from app.core.log import get_logger
from app.models.task import Task, drop_task_data, set_task_data
from app.utils.disk import file_size
from app.utils.tasklog import remove_log, write_log

from .jobs import run_job

logger = get_logger("task_manager")

RESUMABLE_STATUSES = ("pending", "running")
RESTARTABLE_STATUSES = ("paused", "canceled")
TERMINAL_STATUSES = ("completed", "failed", "canceled")

# null queue_order sorts after every positioned task
QUEUE_ORDER_BIG = 1 << 40

# rows in these statuses are pinned to their place in the list; only
# pending/paused/canceled rows can still be dragged around
FROZEN_STATUSES = ("running", "completed", "failed")


def _display_sorted(tasks: list) -> list:
    """Table order: queue position descending, list top first.

    queue_order is a row's stable position in the table. New tasks get a
    position above everything else; a task keeps its position when it starts,
    finishes or fails. The bottom-most pending row runs next (FIFO: new
    tasks stack on top, execution drains from the bottom).
    """

    def key(t: Task):
        qo = t.queue_order if t.queue_order is not None else -QUEUE_ORDER_BIG
        return (-qo, -t.id)

    return sorted(tasks, key=key)


def _legacy_display_sort_key(t: Task) -> tuple:
    """Pre-position display order, used only by the data migration:
    running first, pending by execution order, finished newest first."""
    if t.status == "running":
        return (0, 0, -t.id)
    if t.status == "pending":
        order = t.queue_order if t.queue_order is not None else QUEUE_ORDER_BIG
        return (1, order, t.id)
    return (2, 0, -t.id)


@dataclass
class JobSpec:
    uuid: str
    name: str
    params: Dict[str, Any]


def _load_params(task: Task) -> Optional[Dict[str, Any]]:
    if not task.params:
        return None
    try:
        params = json.loads(task.params)
    except (ValueError, TypeError):
        return None
    if not isinstance(params, dict):
        return None
    if not isinstance(params.get("input"), str) or not isinstance(params.get("output"), str):
        return None
    return params


def _remove_file(path: Optional[str]) -> None:
    if not path:
        return
    try:
        target = Path(path)
        if target.is_file():
            target.unlink()
    except OSError:
        logger.exception("failed to remove file %s", path)


def unfinished_specs() -> list:
    """Job specs for tasks that were not finished and must run again.

    Tasks with unusable stored params can never resume, so they are marked
    failed instead of being queued again on every restart.
    """
    specs: list = []
    rows = (
        Task.select()
        .where(Task.status.in_(RESUMABLE_STATUSES))
        .order_by(
            fn.COALESCE(Task.queue_order, QUEUE_ORDER_BIG).asc(),
            Task.id.asc(),
        )
    )
    for t in rows:
        params = _load_params(t)
        if params is None:
            with db.atomic():
                t.status = "failed"
                t.error = "cannot resume: invalid task parameters"
                t.finished_at = datetime.datetime.utcnow()
                t.save()
            logger.warning("task %s is not resumable (bad params)", t.uuid)
            continue
        specs.append(JobSpec(uuid=t.uuid, name=t.name, params=params))
    return specs


def migrate_queue_order() -> int:
    """One-time data migration: give every task a stable list position.

    Preserves the previous display order (running first, pending by execution
    order, finished newest first). Runs only while some task still has no
    position, so calling it on every startup is safe.
    """
    if not Task.select().where(Task.queue_order.is_null()).exists():
        return 0
    rows = sorted(Task.select(), key=_legacy_display_sort_key)
    n = len(rows)
    with db.atomic():
        for i, t in enumerate(rows):
            qo = n - 1 - i
            if t.queue_order != qo:
                t.queue_order = qo
                t.save()
    logger.info("assigned list positions to %d task(s)", n)
    return n


class TaskManager:
    def __init__(self) -> None:
        self._submit_q: asyncio.Queue[JobSpec] = asyncio.Queue()
        self._mp_q: mp.Queue = mp.Queue()
        self._proc: Optional[mp.Process] = None
        self._running_uuid: Optional[str] = None
        self._queued: set = set()
        self._dispatcher_task: Optional[asyncio.Task] = None
        self._pump_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def start(self):
        async with self._lock:
            if self._dispatcher_task is None or self._dispatcher_task.done():
                self._dispatcher_task = asyncio.create_task(
                    self._dispatcher_loop(), name="tm-dispatcher"
                )
            if self._pump_task is None or self._pump_task.done():
                self._pump_task = asyncio.create_task(self._pump_loop(), name="tm-pump")

    async def stop(self):
        async with self._lock:
            if self._dispatcher_task:
                self._dispatcher_task.cancel()
                self._dispatcher_task = None
            if self._pump_task:
                self._pump_task.cancel()
                self._pump_task = None
            if self._proc and self._proc.is_alive():
                self._proc.terminate()
                self._proc.join(timeout=2)
                self._proc = None
            self._running_uuid = None

    async def submit_convert(
        self,
        body: TaskCreate,
        input_path: Path,
        output_path: Path,
        audio_add: list[dict] | None = None,
    ) -> str:
        job_uuid = uuid_mod.uuid4().hex
        output_path = Path(output_path)
        params = {
            "input": str(input_path),
            "output": str(output_path),
            "quality": body.quality,
            "container": body.container,
            "software": body.software,
            "resolution": body.resolution,
            "audio": body.audio,
            "audio_add": audio_add or [],
        }
        name = input_path.name
        spec = JobSpec(uuid=job_uuid, name=name, params=params)
        source_size = file_size(str(input_path))
        data = json.dumps({"source_size": source_size}) if source_size is not None else None

        status = "paused" if body.paused else "pending"
        with db.atomic():
            Task.create(
                uuid=job_uuid,
                name=name,
                status=status,
                progress=0,
                params=json.dumps(params),
                data=data,
                queue_order=self._next_queue_order(),
                created_at=datetime.datetime.utcnow(),
            )

        if body.paused:
            write_log(job_uuid, f"created paused: name={name} params={params}")
            logger.info("submitted %s (paused)", job_uuid)
        else:
            await self._enqueue(spec)
            write_log(job_uuid, f"queued: name={name} params={params}")
            logger.info("submitted %s", job_uuid)
        return job_uuid

    async def _enqueue(self, spec: JobSpec) -> None:
        if spec.uuid in self._queued:
            return
        self._queued.add(spec.uuid)
        await self._submit_q.put(spec)

    @staticmethod
    def _next_queue_order() -> int:
        """Position for a new task: above everything else."""
        max_order = Task.select(fn.MAX(Task.queue_order)).scalar()
        return (max_order or -1) + 1

    async def reorder(self, task_uuids: list) -> int:
        """Persist a new table order coming from the UI.

        `task_uuids` is the full list top-to-bottom. Only pending/paused/
        canceled rows may change their relative position; running and
        finished rows must keep theirs (they merely shift when a movable row
        is inserted between them). Raises ValueError otherwise.
        """
        rows = list(Task.select())
        by_uuid = {t.uuid: t for t in rows}
        seen: set = set()
        new_order: list = []
        for u in task_uuids:
            t = by_uuid.get(u)
            if t is None or u in seen:
                continue
            seen.add(u)
            new_order.append(t)
        # tasks the client does not know about yet keep their relative
        # order after the listed ones
        new_order.extend(t for t in _display_sorted(rows) if t.uuid not in seen)

        frozen_new = [t.uuid for t in new_order if t.status in FROZEN_STATUSES]
        frozen_old = [
            t.uuid for t in _display_sorted(rows) if t.status in FROZEN_STATUSES
        ]
        if frozen_new != frozen_old:
            raise ValueError("cannot change the position of a running or finished task")

        with db.atomic():
            n = len(new_order)
            for i, t in enumerate(new_order):
                qo = n - 1 - i
                if t.queue_order != qo:
                    t.queue_order = qo
                    t.save()

        self._rebuild_queue()
        logger.info("reordered task list (%d task(s))", n)
        return n

    def _rebuild_queue(self) -> None:
        """Requeue in-memory specs so execution follows queue positions:
        the bottom-most pending row (lowest queue_order) runs first.

        Draining and refilling without awaits makes the swap atomic for the
        dispatcher loop, which may be waiting on the queue at the same time.
        """
        order = {
            t.uuid: t.queue_order if t.queue_order is not None else QUEUE_ORDER_BIG
            for t in Task.select(Task.uuid, Task.queue_order)
        }
        specs: list = []
        while True:
            try:
                specs.append(self._submit_q.get_nowait())
            except asyncio.QueueEmpty:
                break
        specs.sort(key=lambda s: (order.get(s.uuid, QUEUE_ORDER_BIG), s.uuid))
        self._queued = {s.uuid for s in specs}
        for s in specs:
            self._submit_q.put_nowait(s)

    async def resume(self) -> None:
        """Re-queue unfinished tasks (pending/running) after a restart."""
        specs = unfinished_specs()
        if not specs:
            logger.info("nothing to resume")
            return
        uuids = [s.uuid for s in specs]
        with db.atomic():
            (
                Task.update(
                    status="pending",
                    progress=0,
                    error=None,
                    result=None,
                    started_at=None,
                    finished_at=None,
                )
                .where(Task.uuid.in_(uuids))
                .execute()
            )
            for t in Task.select().where(Task.uuid.in_(uuids)):
                drop_task_data(t, "output_size")
        for spec in specs:
            await self._enqueue(spec)
            write_log(spec.uuid, "resuming after restart")
        logger.info("resumed %d task(s)", len(specs))

    async def pause_task(self, task_uuid: str) -> bool:
        try:
            t = Task.get(Task.uuid == task_uuid)
        except DoesNotExist:
            return False
        if t.status != "pending":
            return False
        with db.atomic():
            t.status = "paused"
            t.save()
        write_log(task_uuid, "paused by user")
        logger.info("paused %s", task_uuid)
        return True

    async def start_task(self, task_uuid: str) -> bool:
        try:
            t = Task.get(Task.uuid == task_uuid)
        except DoesNotExist:
            return False
        if t.status not in RESTARTABLE_STATUSES:
            return False
        params = _load_params(t)
        if params is None:
            return False
        with db.atomic():
            t.status = "pending"
            t.progress = 0
            t.error = None
            t.result = None
            t.started_at = None
            t.finished_at = None
            drop_task_data(t, "output_size")
            t.save()
        await self._enqueue(JobSpec(uuid=t.uuid, name=t.name, params=params))
        # the restarted task keeps its list position, which may not be the
        # end of the in-memory queue
        self._rebuild_queue()
        write_log(task_uuid, "restarted by user")
        logger.info("restarted %s", task_uuid)
        return True

    async def stop_task(self, task_uuid: str) -> bool:
        async with self._lock:
            if self._running_uuid != task_uuid:
                return False
            try:
                t = Task.get(Task.uuid == task_uuid)
            except DoesNotExist:
                self._running_uuid = None
                return False

            params = _load_params(t) or {}
            output = params.get("output")

            with db.atomic():
                t.status = "canceled"
                t.result = None
                t.error = None
                t.finished_at = datetime.datetime.utcnow()
                t.save()

            _remove_file(output)

            proc = self._proc
            if proc is not None:
                if proc.is_alive():
                    proc.terminate()
                    await asyncio.to_thread(proc.join, 2)
                    if proc.is_alive():
                        proc.kill()
                self._proc = None
            self._running_uuid = None

        write_log(task_uuid, "stopped by user; partial output removed")
        logger.info("stopped %s", task_uuid)
        return True

    async def list_tasks(self):
        return [t.to_dict() for t in _display_sorted(list(Task.select()))]

    async def delete_task(self, task_uuid: str, with_result: bool = False) -> bool:
        try:
            t = Task.get(Task.uuid == task_uuid)
        except DoesNotExist:
            return False

        if t.status == "running":
            return False

        if with_result and t.result:
            result_file = Path(t.result)
            try:
                if result_file.is_file():
                    result_file.unlink()
            except OSError:
                logger.exception("failed to remove result file %s", result_file)

        t.delete_instance()
        remove_log(task_uuid)
        return True

    async def pause_pending(self) -> int:
        """Move every pending task to paused (remove from the queue)."""
        uuids = [
            t.uuid for t in Task.select(Task.uuid).where(Task.status == "pending")
        ]
        if not uuids:
            return 0
        with db.atomic():
            Task.update(status="paused").where(Task.uuid.in_(uuids)).execute()
        for u in uuids:
            write_log(u, "paused by user (bulk)")
        logger.info("paused %d pending task(s)", len(uuids))
        return len(uuids)

    async def start_paused(self) -> int:
        """Re-queue every restartable (paused/canceled) task."""
        uuids = [
            t.uuid
            for t in Task.select(Task.uuid)
            .where(Task.status.in_(RESTARTABLE_STATUSES))
            .order_by(Task.id.asc())
        ]
        started = 0
        for u in uuids:
            if await self.start_task(u):
                started += 1
        if started:
            logger.info("restarted %d stopped task(s)", started)
        return started

    async def delete_by_status(
        self, statuses: tuple, with_result: bool = False
    ) -> int:
        """Delete finished tasks by status; a running task is never removed."""
        statuses = tuple(s for s in statuses if s != "running")
        if not statuses:
            return 0
        rows = list(Task.select().where(Task.status.in_(statuses)))
        for t in rows:
            if with_result and t.result:
                _remove_file(t.result)
            t.delete_instance()
            remove_log(t.uuid)
        if rows:
            logger.info("deleted %d task(s) with status in %s", len(rows), statuses)
        return len(rows)

    async def _dispatcher_loop(self):
        logger.info("dispatcher_loop started")
        while True:
            try:
                spec = await self._submit_q.get()
                self._queued.discard(spec.uuid)
                try:
                    t = Task.get(Task.uuid == spec.uuid)
                except DoesNotExist:
                    logger.info("Task %s deleted before start, skipping", spec.uuid)
                    continue
                if t.status != "pending":
                    logger.info(
                        "Task %s not pending (status=%s), skipping",
                        spec.uuid,
                        t.status,
                    )
                    continue
                while self._proc is not None and self._proc.is_alive():
                    await asyncio.sleep(0.2)
                await self._start_process(spec)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("dispatcher_loop error")

    async def _start_process(self, spec: JobSpec):
        async with self._lock:
            if self._proc is not None:
                if self._proc.is_alive():
                    return
                self._proc.join(timeout=1)
                self._proc = None

            with db.atomic():
                try:
                    t = Task.get(Task.uuid == spec.uuid)
                except DoesNotExist:
                    return
                if t.status != "pending":
                    logger.info(
                        "Task %s no longer pending, not starting", spec.uuid
                    )
                    return
                t.status = "pending"
                t.progress = 0
                t.error = None
                t.result = None
                t.started_at = None
                t.finished_at = None
                drop_task_data(t, "output_size")
                t.save()

            self._running_uuid = spec.uuid
            self._proc = mp.Process(
                target=run_job,
                args=(spec.uuid, self._mp_q, spec.params),
                daemon=True,
            )
            self._proc.start()

            with db.atomic():
                try:
                    t = Task.get(Task.uuid == spec.uuid)
                    t.status = "running"
                    t.started_at = datetime.datetime.utcnow()
                    t.progress = 0
                    t.save()
                except DoesNotExist:
                    pass

            write_log(spec.uuid, "Worker process started")
            logger.info("Started process for %s", spec.uuid)

    async def _pump_loop(self):
        logger.info("pump_loop started")
        while True:
            try:
                msg = self._mp_q.get_nowait()
            except Exception:
                await asyncio.sleep(0.1)
                continue

            task_uuid = msg.get("task_uuid")
            status = msg.get("status")
            progress = int(msg.get("progress") or 0)
            error = msg.get("error")
            result = msg.get("result")

            try:
                task = Task.get_or_none(Task.uuid == task_uuid)
                if task is None:
                    continue
                if task.status in TERMINAL_STATUSES:
                    # late message from a process we already finished/canceled
                    continue

                with db.atomic():
                    task.status = status
                    task.progress = min(max(progress, 0), 100)
                    if error:
                        task.error = error
                    if result:
                        task.result = result
                    if status == "completed" and result:
                        set_task_data(task, output_size=file_size(result))
                    if status in ("completed", "failed"):
                        task.finished_at = datetime.datetime.utcnow()
                    task.save()

                if status in ("completed", "failed"):
                    async with self._lock:
                        if self._running_uuid == task_uuid:
                            self._running_uuid = None
                        if self._proc and not self._proc.is_alive():
                            self._proc.join(timeout=1)
                            self._proc = None
                    write_log(task_uuid, f"Finished: status={status} progress={progress}")
                    logger.info("Finished %s -> %s", task_uuid, status)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("pump_loop error on message %s", msg)
                await asyncio.sleep(0.1)


manager = TaskManager()
