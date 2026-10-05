import asyncio
import json
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.tasks.manager import TaskManager
from app.utils.disk import get_disk_usage
from app.utils.tasklog import log_path

from .deps import get_manager

router = APIRouter()


@router.get("/system/disk")
async def disk_info():
    return await get_disk_usage("/")


@router.get("/tasks")
async def list_tasks(mgr: TaskManager = Depends(get_manager)):
    return await mgr.list_tasks()


@router.post("/tasks")
async def create_task(
    duration_sec: float = 10.0,
    fail_at: int | None = None,
    name: str = "test_job",
    mgr: TaskManager = Depends(get_manager),
):
    if duration_sec <= 0:
        raise HTTPException(status_code=400, detail="duration_sec > 0")
    if fail_at is not None and (fail_at < 5 or fail_at > 95):
        raise HTTPException(status_code=400, detail="fail_at must be between 5 and 95")
    uuid = await mgr.submit_test(duration_sec=duration_sec, fail_at=fail_at, name=name)
    return {"uuid": uuid, "status": "pending"}


@router.delete("/tasks/{task_uuid}")
async def delete_task(task_uuid: str, mgr: TaskManager = Depends(get_manager)):
    ok = await mgr.delete_task(task_uuid)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="cannot delete: not found or currently running",
        )
    return {"ok": True}


@router.get("/tasks/{task_uuid}/log")
async def task_log(task_uuid: str):
    path = log_path(task_uuid)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="log file not found")
    return FileResponse(path, media_type="text/plain; charset=utf-8")


async def _sse_event_stream(
    request: Request, mgr: TaskManager
) -> AsyncGenerator[bytes, None]:
    known: dict[str, tuple[str, int]] | None = None

    while True:
        if await request.is_disconnected():
            break
        items = await mgr.list_tasks()
        current = {i["uuid"]: (i["status"], i["progress"]) for i in items}

        if known is None:
            payload = {"type": "snapshot", "items": items, "ts": time.time()}
            yield f"event: tasks\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            known = current
        else:
            changed = [
                i for i in items if i["uuid"] not in known or known[i["uuid"]] != current[i["uuid"]]
            ]
            removed = [u for u in known if u not in current]
            if changed or removed:
                payload = {
                    "type": "update",
                    "items": changed,
                    "removed": removed,
                    "ts": time.time(),
                }
                yield f"event: tasks\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            else:
                yield ": ping\n\n"
            known = current
        await asyncio.sleep(0.5)


@router.get("/tasks/stream")
async def tasks_stream(request: Request, mgr: TaskManager = Depends(get_manager)):
    return StreamingResponse(
        _sse_event_stream(request, mgr),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
