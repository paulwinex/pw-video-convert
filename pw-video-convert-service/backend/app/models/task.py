import datetime
import json

from peewee import (
    AutoField,
    CharField,
    DateTimeField,
    IntegerField,
    Model,
    TextField,
)

from app.core.db import db
from app.utils.disk import file_size
from app.utils.tasklog import has_log


class Task(Model):
    id = AutoField()
    uuid = CharField(unique=True, index=True, max_length=64)
    name = CharField(max_length=255, default="task")
    # Position among pending tasks (0 = next to run); null for legacy rows
    # and for everything that already left the queue.
    queue_order = IntegerField(null=True)
    status = CharField(
        max_length=16,
        default="pending",
        choices=[
            ("pending", "pending"),
            ("running", "running"),
            ("paused", "paused"),
            ("completed", "completed"),
            ("failed", "failed"),
            ("canceled", "canceled"),
        ],
    )
    progress = IntegerField(default=0)
    error = TextField(null=True)
    result = TextField(null=True)
    params = TextField(null=True)
    data = TextField(null=True)
    created_at = DateTimeField(default=datetime.datetime.utcnow)
    started_at = DateTimeField(null=True)
    finished_at = DateTimeField(null=True)

    class Meta:
        database = db
        table_name = "tasks"

    def to_dict(self) -> dict:
        params = json.loads(self.params) if self.params else {}
        data = json.loads(self.data) if self.data else {}
        input_path = params.get("input")
        source_size = data.get("source_size")
        if source_size is None:
            source_size = file_size(input_path) if input_path else None
        output_size = data.get("output_size")
        if output_size is None:
            output_size = file_size(self.result) if self.result else None
        return {
            "id": self.id,
            "uuid": self.uuid,
            "name": self.name,
            "status": self.status,
            "queue_order": self.queue_order,
            "progress": int(self.progress or 0),
            "error": self.error,
            "result": self.result,
            "params": params,
            "data": data,
            "size_before": source_size,
            "size_after": output_size,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "started_at": self.started_at.isoformat() + "Z" if self.started_at else None,
            "finished_at": self.finished_at.isoformat() + "Z" if self.finished_at else None,
            "has_log": has_log(self.uuid),
        }


def task_data(task: Task) -> dict:
    return json.loads(task.data) if task.data else {}


def set_task_data(task: Task, **fields) -> None:
    data = task_data(task)
    data.update({k: v for k, v in fields.items() if v is not None})
    task.data = json.dumps(data) if data else None
    task.save()


def drop_task_data(task: Task, *keys) -> None:
    data = task_data(task)
    for key in keys:
        data.pop(key, None)
    task.data = json.dumps(data) if data else None
    task.save()
