"""Persistent receipts and resource state for the synthetic demo services."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def identifier(prefix):
    return f"{prefix}_{uuid4().hex[:12]}"


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    mode TEXT NOT NULL, intent TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS resources (
                    run_id TEXT NOT NULL REFERENCES runs(id), kind TEXT NOT NULL,
                    data TEXT NOT NULL, versions TEXT NOT NULL,
                    PRIMARY KEY (run_id, kind)
                );
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    owner TEXT NOT NULL, kind TEXT NOT NULL, label TEXT NOT NULL,
                    changes TEXT NOT NULL, created_at TEXT NOT NULL,
                    recovery TEXT NOT NULL DEFAULT 'pending',
                    UNIQUE (run_id, kind)
                );
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    digest TEXT NOT NULL, body TEXT NOT NULL,
                    status TEXT NOT NULL, approved_by TEXT, approved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id), actor TEXT NOT NULL,
                    type TEXT NOT NULL, title TEXT NOT NULL,
                    detail TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS human_edits (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id), field TEXT NOT NULL,
                    receipt TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
        self.path.chmod(0o600)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def resource(db, run_id, kind):
        row = db.execute(
            "SELECT data, versions FROM resources WHERE run_id=? AND kind=?",
            (run_id, kind),
        ).fetchone()
        if row is None:
            raise ValueError("Resource not found")
        return json.loads(row["data"]), json.loads(row["versions"])

    @classmethod
    def change(cls, db, run_id, kind, updates):
        data, versions = cls.resource(db, run_id, kind)
        receipt = {}
        for field, value in updates.items():
            receipt[field] = {
                "before": data[field], "after": value,
                "version": versions[field] + 1,
            }
            data[field] = value
            versions[field] += 1
        db.execute(
            "UPDATE resources SET data=?, versions=? WHERE run_id=? AND kind=?",
            (encode(data), encode(versions), run_id, kind),
        )
        return receipt

    @staticmethod
    def event(db, run_id, actor, event_type, title, detail):
        db.execute(
            "INSERT INTO events(run_id,actor,type,title,detail,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (run_id, actor, event_type, title, detail, now()),
        )
