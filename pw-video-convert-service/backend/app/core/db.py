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
    _migrate()
    db.close()


# columns added after the first release; CREATE TABLE IF NOT EXISTS won't add them
MIGRATIONS = {
    "tasks": {
        "queue_order": "ALTER TABLE tasks ADD COLUMN queue_order INTEGER",
    },
}


def _migrate():
    for table, columns in MIGRATIONS.items():
        if not db.table_exists(table):
            continue
        cursor = db.execute_sql(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cursor.fetchall()}
        for column, sql in columns.items():
            if column not in existing:
                db.execute_sql(sql)
