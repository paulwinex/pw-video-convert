import multiprocessing as mp
from pathlib import Path

import app.core.config  # noqa: F401  # installs pw-video-convert on sys.path
from app.tasks.jobs import convert_job
from app.utils.tasklog import log_path, remove_log


def test_convert_job_success(tiny_clip: Path, tmp_path: Path, drain):
    uuid = "test-convert-success"
    out = tmp_path / "result" / "tiny.mkv"
    q: mp.Queue = mp.Queue()

    try:
        convert_job(
            task_uuid=uuid,
            progress_q=q,
            input=str(tiny_clip),
            output=str(out),
            quality=10,
            container="mkv",
            software=True,
        )
        msgs = drain(q)
        log_text = log_path(uuid).read_text(encoding="utf-8")
    finally:
        remove_log(uuid)

    assert msgs, "expected at least one progress message"
    assert msgs[-1]["status"] == "completed"
    assert msgs[-1]["progress"] == 100
    assert msgs[-1]["result"] == str(out)
    assert out.is_file() and out.stat().st_size > 0

    running = [m for m in msgs if m["status"] == "running"]
    assert running, "expected intermediate progress messages"
    assert all(0 <= m["progress"] <= 99 for m in running)

    assert "Encoder:" in log_text  # plan lines went to the task log


def test_convert_job_missing_input_fails(tiny_clip: Path, tmp_path: Path, drain):
    uuid = "test-convert-missing"
    q: mp.Queue = mp.Queue()

    try:
        convert_job(
            task_uuid=uuid,
            progress_q=q,
            input=str(tmp_path / "gone.mp4"),
            output=str(tmp_path / "out.mkv"),
            quality=5,
            container="mkv",
            software=True,
        )
        msgs = drain(q)
    finally:
        remove_log(uuid)

    assert len(msgs) == 1
    assert msgs[0]["status"] == "failed"
    assert "input file not found" in msgs[0]["error"]


def test_convert_job_non_video_input_fails(tmp_path: Path, drain):
    uuid = "test-convert-nonvideo"
    bad = tmp_path / "notes.txt"
    bad.write_text("this is not a video")
    q: mp.Queue = mp.Queue()

    try:
        convert_job(
            task_uuid=uuid,
            progress_q=q,
            input=str(bad),
            output=str(tmp_path / "out.mkv"),
            quality=5,
            container="mkv",
            software=True,
        )
        msgs = drain(q)
    finally:
        remove_log(uuid)

    assert len(msgs) == 1
    assert msgs[0]["status"] == "failed"
    assert msgs[0]["error"]


def test_convert_job_reports_failure_even_if_log_write_fails(
    tmp_path, drain, monkeypatch
):
    import app.tasks.jobs as jobs_mod

    def broken_write_log(task_uuid, message):
        raise OSError("disk full")

    monkeypatch.setattr(jobs_mod, "write_log", broken_write_log)
    uuid = "test-convert-logfail"
    q: mp.Queue = mp.Queue()

    convert_job(
        task_uuid=uuid,
        progress_q=q,
        input=str(tmp_path / "gone.mp4"),
        output=str(tmp_path / "out.mkv"),
        quality=5,
        container="mkv",
        software=True,
    )
    msgs = drain(q)

    assert len(msgs) == 1
    assert msgs[0]["status"] == "failed"
    assert "input file not found" in msgs[0]["error"]
