import asyncio
import datetime
import json
import multiprocessing as mp
import uuid as uuid_mod
from dataclasses import dataclass
from typing import Any, Dict, Optional

from peewee import DoesNotExist

from app.core.db import db
from app.core.log import get_logger
from app.models.task import Task
from app.utils.tasklog import remove_log, write_log

from .jobs import run_job

logger = get_logger("task_manager")


@dataclass
class JobSpec:
    uuid: str
    name: str
    params: Dict[str, Any]


class TaskManager:
    def __init__(self) -> None:
        self._submit_q: asyncio.Queue[JobSpec] = asyncio.Queue()
        self._mp_q: mp.Queue = mp.Queue()
        self._proc: Optional[mp.Process] = None
        self._running_uuid: Optional[str] = None
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

    async def submit_test(
        self,
        duration_sec: float = 10.0,
        fail_at: int | None = None,
        name: str = "test_job",
    ) -> str:
        job_uuid = uuid_mod.uuid4().hex
        params = {
            "duration_sec": float(duration_sec),
            "fail_at": fail_at if fail_at is None else int(fail_at),
        }
        spec = JobSpec(uuid=job_uuid, name=name, params=params)

        with db.atomic():
            Task.create(
                uuid=job_uuid,
                name=name,
                status="pending",
                progress=0,
                params=json.dumps(params),
                created_at=datetime.datetime.utcnow(),
            )

        await self._submit_q.put(spec)
        write_log(job_uuid, f"queued: name={name} params={params}")
        logger.info("submitted %s", job_uuid)
        return job_uuid

    async def list_tasks(self):
        q = Task.select().order_by(Task.id.desc())
        return [t.to_dict() for t in q]

    async def delete_task(self, task_uuid: str) -> bool:
        try:
            t = Task.get(Task.uuid == task_uuid)
        except DoesNotExist:
            return False

        if t.status == "running":
            return False

        t.delete_instance()
        remove_log(task_uuid)
        return True

    async def _dispatcher_loop(self):
        logger.info("dispatcher_loop started")
        while True:
            try:
                spec = await self._submit_q.get()
                # check is not deleted
                if not Task.select().where(Task.uuid == spec.uuid).exists():
                    logger.info("Task %s deleted before start, skipping", spec.uuid)
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
                t.status = "pending"
                t.progress = 0
                t.error = None
                t.result = None
                t.started_at = None
                t.finished_at = None
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
                with db.atomic():
                    try:
                        t = Task.get(Task.uuid == task_uuid)
                        t.status = status
                        t.progress = min(max(progress, 0), 100)
                        if error:
                            t.error = error
                        if result:
                            t.result = result
                        if status in ("completed", "failed"):
                            t.finished_at = datetime.datetime.utcnow()
                        t.save()
                    except DoesNotExist:
                        pass

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
