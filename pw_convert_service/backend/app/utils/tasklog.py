import datetime
from pathlib import Path

from app.core.config import LOGS_DIR


def log_path(task_uuid: str) -> Path:
    return LOGS_DIR / f"{task_uuid}.log"


def has_log(task_uuid: str) -> bool:
    return log_path(task_uuid).is_file()


def write_log(task_uuid: str, message: str) -> None:
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    path = log_path(task_uuid)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{ts} {message}\n")


def remove_log(task_uuid: str) -> None:
    path = log_path(task_uuid)
    if path.is_file():
        path.unlink()
