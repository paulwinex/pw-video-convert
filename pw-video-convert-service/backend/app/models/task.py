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
from app.utils.tasklog import has_log


class Task(Model):
    id = AutoField()
    uuid = CharField(unique=True, index=True, max_length=64)
    name = CharField(max_length=255, default="task")
    status = CharField(
        max_length=16,
        default="pending",
        choices=[
            ("pending", "pending"),
            ("running", "running"),
            ("completed", "completed"),
            ("failed", "failed"),
        ],
    )
    progress = IntegerField(default=0)
    error = TextField(null=True)
    result = TextField(null=True)
    params = TextField(null=True)
    created_at = DateTimeField(default=datetime.datetime.utcnow)
    started_at = DateTimeField(null=True)
    finished_at = DateTimeField(null=True)

    class Meta:
        database = db
        table_name = "tasks"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "uuid": self.uuid,
            "name": self.name,
            "status": self.status,
            "progress": int(self.progress or 0),
            "error": self.error,
            "result": self.result,
            "params": json.loads(self.params) if self.params else {},
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "started_at": self.started_at.isoformat() + "Z" if self.started_at else None,
            "finished_at": self.finished_at.isoformat() + "Z" if self.finished_at else None,
            "has_log": has_log(self.uuid),
        }
