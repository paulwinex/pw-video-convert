import multiprocessing as mp
import time
from typing import Any, Dict

from app.utils.tasklog import write_log


def run_job(task_uuid: str, progress_q: mp.Queue, params: Dict[str, Any]) -> None:
    """Module-level entrypoint for mp.Process (must be picklable)."""
    test_job(task_uuid=task_uuid, progress_q=progress_q, **params)


def test_job(
    task_uuid: str,
    progress_q: mp.Queue,
    duration_sec: float = 12.0,
    fail_at: int | None = None,
):
    """
    Testing func
    """
    write_log(task_uuid, f"job started: duration_sec={duration_sec} fail_at={fail_at}")
    last_progress = 0
    try:
        steps = 20
        total_sleep = max(0.01, duration_sec / steps)
        for i in range(1, steps + 1):
            p = int(i * 5)
            if p > 95:
                p = 95
            last_progress = p
            write_log(task_uuid, f"progress {p}%")
            progress_q.put(
                {
                    "task_uuid": task_uuid,
                    "status": "running",
                    "progress": p,
                    "ts": time.time(),
                }
            )
            if fail_at is not None and p >= fail_at:
                raise RuntimeError(f"Искусственная ошибка на прогрессе {p}%")
            time.sleep(total_sleep)
        write_log(task_uuid, f"job completed: result=ok:{task_uuid}")
        progress_q.put(
            {
                "task_uuid": task_uuid,
                "status": "completed",
                "progress": 100,
                "result": f"ok:{task_uuid}",
                "ts": time.time(),
            }
        )
    except Exception as e:
        write_log(task_uuid, f"job failed: {e}")
        progress_q.put(
            {
                "task_uuid": task_uuid,
                "status": "failed",
                "progress": last_progress,
                "error": str(e),
                "ts": time.time(),
            }
        )
