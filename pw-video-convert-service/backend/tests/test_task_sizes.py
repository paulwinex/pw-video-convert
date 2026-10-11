import json
from pathlib import Path

from app.models.task import Task
from app.utils.disk import file_size


def make_task(tmp_path: Path, *, result: str | None, data: str | None = None) -> Task:
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x" * 1000)
    out = tmp_path / "out.mkv"
    out.write_bytes(b"x" * 400)
    params = {"input": str(src), "output": str(out)}
    return Task(
        uuid="task-sizes",
        name="in.mp4",
        status="completed",
        progress=100,
        params=json.dumps(params),
        result=result,
        data=data,
    )


def test_to_dict_reports_size_before_and_after(tmp_path):
    t = make_task(tmp_path, result=str(tmp_path / "out.mkv"))

    d = t.to_dict()

    assert d["size_before"] == 1000
    assert d["size_after"] == 400


def test_to_dict_size_after_is_none_without_result(tmp_path):
    t = make_task(tmp_path, result=None)

    d = t.to_dict()

    assert d["size_before"] == 1000
    assert d["size_after"] is None


def test_to_dict_size_before_is_none_when_input_missing(tmp_path):
    t = make_task(tmp_path, result=str(tmp_path / "out.mkv"))
    Path(json.loads(t.params)["input"]).unlink()

    d = t.to_dict()

    assert d["size_before"] is None


def test_to_dict_reads_sizes_from_data_when_files_deleted(tmp_path):
    t = make_task(
        tmp_path,
        result=str(tmp_path / "out.mkv"),
        data=json.dumps({"source_size": 5000, "output_size": 2000}),
    )
    Path(json.loads(t.params)["input"]).unlink()
    Path(json.loads(t.params)["output"]).unlink()

    d = t.to_dict()

    assert d["size_before"] == 5000
    assert d["size_after"] == 2000


def test_to_dict_without_output_size_returns_none_for_missing_result(tmp_path):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x" * 1000)
    out = tmp_path / "out.mkv"
    params = {"input": str(src), "output": str(out)}
    t = Task(
        uuid="task-sizes",
        name="in.mp4",
        status="completed",
        progress=100,
        params=json.dumps(params),
        result=str(out),
        data=json.dumps({"source_size": 1000}),
    )

    d = t.to_dict()

    assert d["size_before"] == 1000
    assert d["size_after"] is None


def test_file_size_missing_file_is_none(tmp_path):
    assert file_size(str(tmp_path / "nope.bin")) is None
