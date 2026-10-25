import io
import multiprocessing as mp
import sys
import time
from pathlib import Path
from typing import Any, Dict

import app.core.config  # noqa: F401  # installs pw-video-convert on sys.path
from pw_video_convert import cli, probe
from pw_video_convert import quality as quality_mod

from app.utils.tasklog import log_path, write_log


def run_job(task_uuid: str, progress_q: mp.Queue, params: Dict[str, Any]) -> None:
    """Module-level entrypoint for mp.Process (must be picklable)."""
    convert_job(task_uuid=task_uuid, progress_q=progress_q, **params)


def _put(progress_q: mp.Queue, task_uuid: str, **fields: Any) -> None:
    progress_q.put({"task_uuid": task_uuid, "ts": time.time(), **fields})


def _log(task_uuid: str, message: str) -> None:
    try:
        write_log(task_uuid, message)
    except Exception:
        pass


def convert_job(
    task_uuid: str,
    progress_q: mp.Queue,
    input: str,
    output: str,
    quality: int,
    container: str,
    software: bool,
    resolution: list[int] | None = None,
) -> None:
    file_input = Path(input)
    output_path = Path(output)
    last_progress = 0
    err_buf = io.StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    log_file = None

    try:
        log_file = log_path(task_uuid).open("a", encoding="utf-8", buffering=1)
        sys.stdout, sys.stderr = log_file, err_buf

        if not file_input.is_file():
            raise FileNotFoundError(f"input file not found: {file_input}")

        use_hw = (not software) and probe.will_ha_work()
        if not software and not use_hw:
            print(
                "Warning: hardware VAAPI AV1 unavailable, "
                "falling back to software SVT-AV1"
            )

        source_codec = None
        try:
            info = probe.get_media_info(str(file_input))
            source_codec = (info.get("video") or {}).get("codec_name")
        except Exception:
            source_codec = None
        crf = quality_mod.crf_for_quality(quality, source_codec)
        preset = quality_mod.preset_for_quality(quality, source_codec)
        if use_hw:
            encoder = f"hw av1_vaapi qidx={quality_mod.vaapi_quality_for_quality(quality, source_codec)}"
        else:
            encoder = f"sw svt-av1 crf={crf} preset={preset}"
        if resolution is None:
            res_txt = "source"
        else:
            res_txt = f"{resolution[0]}x{resolution[1]}"
        print("--- launch params ---")
        print(f"input: {file_input}")
        print(f"output: {output_path}")
        print(f"container: {container}")
        print(f"quality: {quality}")
        print(f"software: {str(software).lower()}")
        print(f"resolution: {res_txt}")
        print(f"encoder: {encoder}")
        print("---")

        def on_progress(fraction: float, seconds_left: int | None) -> None:
            nonlocal last_progress
            last_progress = min(99, round(fraction * 100))
            _put(progress_q, task_uuid, status="running", progress=last_progress)

        code = cli.encode_once(
            file_input,
            output_path,
            quality,
            use_hw,
            container,
            progress_fn=on_progress,
            cancel_fn=lambda: False,
            resolution=resolution,
        )

        if code == 0:
            _log(task_uuid, f"encode ok: {output_path}")
            _put(
                progress_q,
                task_uuid,
                status="completed",
                progress=100,
                result=str(output_path),
            )
        else:
            error = (
                err_buf.getvalue().replace("*** ENCODE ERROR ***\n", "").strip()
                or f"encode failed (exit code {code})"
            )
            _log(task_uuid, f"encode failed: {error}")
            _put(
                progress_q,
                task_uuid,
                status="failed",
                progress=last_progress,
                error=error,
            )
    except Exception as e:
        _log(task_uuid, f"job failed: {e}")
        _put(progress_q, task_uuid, status="failed", progress=last_progress, error=str(e))
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        if log_file is not None:
            log_file.close()
