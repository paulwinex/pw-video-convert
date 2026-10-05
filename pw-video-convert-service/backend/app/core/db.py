from peewee import SqliteDatabase

from .config import DB_PATH

db = SqliteDatabase(
    DB_PATH,
    pragmas={
        "journal_mode": "wal",
        "foreign_keys": 1,
        "busy_timeout": 5000,
    },
)


def init_db(models: list):
    db.connect(reuse_if_open=True)
    db.create_tables(models, safe=True)
    db.close()
