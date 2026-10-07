import asyncio
import json
import os
import time
from pathlib import Path
from pprint import pprint
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.core.config import DEFAULT_OUTPUT_DIR, REMAP_PATH
from app.tasks.manager import TaskManager
from app.utils.disk import get_disk_usage
from app.utils.tasklog import log_path
from pw_video_convert.cli import resolve_output

from .deps import get_manager
from .schemas import TaskCreate

router = APIRouter()


@router.get("/system/disk")
async def disk_info():
    return await get_disk_usage("/")


@router.get("/tasks")
async def list_tasks(mgr: TaskManager = Depends(get_manager)):
    return await mgr.list_tasks()


@router.post("/tasks")
async def create_task(
    payload: TaskCreate,
    mgr: TaskManager = Depends(get_manager),
):
    try:
        input_path = Path(payload.input).expanduser().resolve()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid input path: {exc}")
    if payload.remap_path:
        input_path = Path(str(input_path).replace(str(payload.remap_path), str(REMAP_PATH)))
    if not input_path.is_file():
        raise HTTPException(
            status_code=400, detail=f"input file not found: {input_path}"
        )
    if payload.output is None:
        output_arg = str(DEFAULT_OUTPUT_DIR)
    else:
        try:
            cand = Path(payload.output).expanduser()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid output path: {exc}")
        if cand.is_absolute():
            raise HTTPException(
                status_code=400,
                detail=(
                    "output must be a relative path "
                    "(resolved under the server output directory)"
                ),
            )
        root = DEFAULT_OUTPUT_DIR.resolve()
        try:
            joined = (root / cand).resolve()
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid output path: {exc}"
            )
        if not joined.is_relative_to(root):
            raise HTTPException(
                status_code=400, detail="output path escapes the output directory"
            )
        output_arg = str(joined) + (os.sep if payload.output.endswith(os.sep) else "")

    output_path = resolve_output(input_path, output_arg, payload.quality, payload.container)
    if output_path == input_path:
        raise HTTPException(
            status_code=400, detail="output path resolves to the input file"
        )

    uuid = await mgr.submit_convert(payload, input_path, output_path)
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
