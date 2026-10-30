import asyncio
import fnmatch
import json
import mimetypes
import os
import time
from datetime import datetime
from pathlib import Path
from pprint import pprint
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import FileResponse, StreamingResponse

from app.core.config import DEFAULT_OUTPUT_DIR, REMAP_PATH
from app.tasks.manager import TaskManager
from app.utils.disk import get_disk_usage
from app.utils.tasklog import log_path
from pw_video_convert import probe
from pw_video_convert.cli import resolve_output
from app.tasks import filesystem

from .deps import get_manager
from .schemas import (
    TaskCreate,
    TaskReorder,
    ListResponse,
    FileEntry,
    AudioTrack,
    ProbeResponse,
)

router = APIRouter()


def _resolve_input(raw_input: str, remap_path: str | None) -> Path:
    """Resolve a user-supplied input path the same way for every endpoint.

    The client-side prefix (`remap_path`) is replaced with the service-side
    root BEFORE resolving, so symlinked client prefixes cannot break the
    substitution.
    """
    candidate = Path(raw_input).expanduser()
    if remap_path:
        candidate = Path(str(candidate).replace(str(remap_path), str(REMAP_PATH)))
    if candidate.is_absolute():
        return candidate.resolve()
    return (filesystem.get_user_root() / candidate).resolve()


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
        input_path = _resolve_input(payload.input, payload.remap_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid input path: {exc}")
    if not input_path.is_file():
        raise HTTPException(
            status_code=400, detail=f"input file not found: {input_path}"
        )
    output_val = (payload.output or "").strip()
    if not output_val:
        output_arg = str(DEFAULT_OUTPUT_DIR)
    else:
        try:
            cand = Path(output_val).expanduser()
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
        output_arg = str(joined) + os.sep

    output_path = resolve_output(input_path, output_arg, payload.container)
    if output_path == input_path:
        raise HTTPException(
            status_code=400, detail="output path resolves to the input file"
        )

    uuid = await mgr.submit_convert(payload, input_path, output_path)
    return {"uuid": uuid, "status": "pending"}


@router.get("/probe", response_model=ProbeResponse)
def probe_file(
    path: str = Query(..., description="Input file path (absolute or user-relative)"),
    remap_path: str | None = Query(
        default=None, description="Client path prefix to replace with the server root"
    ),
) -> ProbeResponse:
    try:
        input_path = _resolve_input(path, remap_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid input path: {exc}")
    if not input_path.is_file():
        raise HTTPException(status_code=404, detail=f"input file not found: {input_path}")
    try:
        tracks = probe.get_audio_tracks(str(input_path))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"could not probe file: {exc}")
    return ProbeResponse(
        path=str(input_path),
        audio=[AudioTrack(**t) for t in tracks],
    )


@router.post("/tasks/reorder")
async def reorder_tasks(
    payload: TaskReorder,
    mgr: TaskManager = Depends(get_manager),
):
    try:
        count = await mgr.reorder(payload.uuids)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"count": count}


@router.post("/tasks/pause-unstarted")
async def pause_unstarted(mgr: TaskManager = Depends(get_manager)):
    count = await mgr.pause_pending()
    return {"count": count}


@router.post("/tasks/start-stopped")
async def start_stopped(mgr: TaskManager = Depends(get_manager)):
    count = await mgr.start_paused()
    return {"count": count}


@router.delete("/tasks/completed")
async def delete_completed(
    with_result: bool = False,
    mgr: TaskManager = Depends(get_manager),
):
    count = await mgr.delete_by_status(("completed",), with_result=with_result)
    return {"count": count}


@router.delete("/tasks/failed")
async def delete_failed(
    with_result: bool = False,
    mgr: TaskManager = Depends(get_manager),
):
    count = await mgr.delete_by_status(("failed",), with_result=with_result)
    return {"count": count}


@router.delete("/tasks/{task_uuid}")
async def delete_task(
    task_uuid: str,
    with_result: bool = False,
    mgr: TaskManager = Depends(get_manager),
):
    ok = await mgr.delete_task(task_uuid, with_result=with_result)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="cannot delete: not found or currently running",
        )
    return {"ok": True}


@router.post("/tasks/{task_uuid}/pause")
async def pause_task(
    task_uuid: str,
    mgr: TaskManager = Depends(get_manager),
):
    ok = await mgr.pause_task(task_uuid)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="cannot pause: not found or not pending",
        )
    return {"ok": True}


@router.post("/tasks/{task_uuid}/start")
async def start_task(
    task_uuid: str,
    mgr: TaskManager = Depends(get_manager),
):
    ok = await mgr.start_task(task_uuid)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="cannot start: not found or not paused/canceled",
        )
    return {"ok": True}


@router.post("/tasks/{task_uuid}/stop")
async def stop_task(
    task_uuid: str,
    mgr: TaskManager = Depends(get_manager),
):
    ok = await mgr.stop_task(task_uuid)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="cannot stop: not found or not running",
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
    known_order: list[str] | None = None

    while True:
        if await request.is_disconnected():
            break
        items = await mgr.list_tasks()
        current = {i["uuid"]: (i["status"], i["progress"]) for i in items}
        order = [i["uuid"] for i in items]

        if known is None:
            payload = {"type": "snapshot", "items": items, "ts": time.time()}
            yield f"event: tasks\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            known = current
            known_order = order
        else:
            changed = [
                i for i in items if i["uuid"] not in known or known[i["uuid"]] != current[i["uuid"]]
            ]
            removed = [u for u in known if u not in current]
            if order != known_order:
                # the whole list order changed (e.g. queue reorder) — push all
                changed = items
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
            known_order = order
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


def _mime_matches(name: str, patterns: list[str]) -> bool:
    guessed = mimetypes.guess_type(name)[0]
    if guessed is None:
        return False
    return any(fnmatch.fnmatchcase(guessed, pattern) for pattern in patterns)


@router.get("/fs", response_model=ListResponse)
def list_dir(
    path: str = Query("", description="Relative path"),
    mime: list[str] = Query(
        default=[],
        description="MIME patterns (wildcards allowed), e.g. video/*",
    ),
    root: Path = Depends(filesystem.get_user_root),
) -> ListResponse:
    target = filesystem.safe_resolve(root, path)

    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    entries: list[FileEntry] = []

    try:
        with os.scandir(target) as it:
            for entry in it:
                if entry.name.startswith("."):
                    continue
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue

                is_dir = entry.is_dir(follow_symlinks=False)
                if not is_dir and mime and not _mime_matches(entry.name, mime):
                    continue

                rel = os.path.relpath(entry.path, root).replace(os.sep, "/")

                entries.append(FileEntry(
                    name=entry.name,
                    path=rel,
                    is_dir=is_dir,
                    size=None if is_dir else st.st_size,
                    created=datetime.fromtimestamp(st.st_ctime),
                    modified=datetime.fromtimestamp(st.st_mtime),
                ))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))

    return ListResponse(path=path.lstrip("/"), entries=entries)
