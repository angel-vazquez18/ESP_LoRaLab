"""Local run/event persistence. Only the backend owns this connection."""

import fcntl
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .analysis import Metrics
from .models import NodeEvent


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.lock_file = (root / "host.lock").open("a+")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock_file.close()
            raise RuntimeError("Another backend already owns this data directory") from exc
        self.db = sqlite3.connect(root / "testbed.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                received_at TEXT NOT NULL, document TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_run ON events(run_id, id);
            CREATE TABLE IF NOT EXISTS references_audio (
                id TEXT PRIMARY KEY, document TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS node_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL,
                received_at TEXT NOT NULL, document TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL
            );
        """)
        for run in self.runs():
            if run["status"] in ("preparing", "running", "stopping"):
                metrics = Metrics()
                for row in self.events(run["id"]):
                    metrics.accept(NodeEvent.model_validate(row["document"]))
                run["metrics"] = metrics.snapshot()
                run.update(status="interrupted", finished_at=utc_now(), reason="Host restarted")
                self.save_run(run)
        for campaign in self.campaigns():
            if campaign["status"] in ("running", "paused", "stopping"):
                campaign.update(
                    status="interrupted", finished_at=utc_now(), reason="Host restarted"
                )
                for case in campaign["cases"]:
                    if case["status"] in ("pending", "running"):
                        run = self.run(case["run_id"]) if case["run_id"] else None
                        case["status"] = run["status"] if run else "interrupted"
                self.save_campaign(campaign)

    def save_campaign(self, campaign: dict):
        self.db.execute(
            "INSERT INTO campaigns VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET document=excluded.document",
            (campaign["id"], campaign["created_at"], json.dumps(campaign)),
        )
        self.db.commit()

    def campaigns(self) -> list[dict]:
        return [
            json.loads(row[0])
            for row in self.db.execute("SELECT document FROM campaigns ORDER BY created_at DESC")
        ]

    def campaign(self, campaign_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT document FROM campaigns WHERE id=?", (campaign_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def save_run(self, run: dict):
        self.db.execute(
            "INSERT INTO runs VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET document=excluded.document",
            (run["id"], run["created_at"], json.dumps(run)),
        )
        self.db.commit()

    def append_node_event(self, role: str, event: dict):
        self.db.execute(
            "INSERT INTO node_observations(role,received_at,document) VALUES (?,?,?)",
            (role, utc_now(), json.dumps(event)),
        )
        self.db.commit()

    def runs(self) -> list[dict]:
        return [
            json.loads(row[0])
            for row in self.db.execute("SELECT document FROM runs ORDER BY created_at DESC")
        ]

    def run(self, run_id: str) -> dict | None:
        row = self.db.execute("SELECT document FROM runs WHERE id=?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def append_event(self, run_id: str, event: dict):
        self.db.execute(
            "INSERT INTO events(run_id, received_at, document) VALUES (?, ?, ?)",
            (run_id, utc_now(), json.dumps(event)),
        )
        self.db.commit()

    def events(self, run_id: str) -> list[dict]:
        return [
            dict(row) | {"document": json.loads(row["document"])}
            for row in self.db.execute(
                "SELECT id, received_at, document FROM events WHERE run_id=? ORDER BY id", (run_id,)
            )
        ]

    def save_reference(self, reference: dict):
        self.db.execute(
            "INSERT INTO references_audio VALUES (?, ?)", (reference["id"], json.dumps(reference))
        )
        self.db.commit()

    def references(self) -> list[dict]:
        return [
            json.loads(row[0])
            for row in self.db.execute("SELECT document FROM references_audio ORDER BY rowid DESC")
        ]

    def close(self):
        self.db.close()
        self.lock_file.close()
