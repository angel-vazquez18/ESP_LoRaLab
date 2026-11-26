"""Local run/event persistence. Only the backend owns this connection."""

import fcntl
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .analysis import Metrics
from .models import NodeEvent
from .session_keys import require_public_metadata


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
            CREATE TABLE IF NOT EXISTS audio_operations (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifact_transfers (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL
            );
        """)
        for audio in self.audio_operations():
            if audio["status"] == "running":
                audio.update(
                    status="interrupted",
                    finished_at=utc_now(),
                    error="Host restarted",
                    cleanup="unconfirmed; operation stops on ownership loss",
                )
                self.save_audio(audio)
        for transfer in self.transfers():
            if transfer["status"] == "running":
                transfer.update(
                    status="interrupted",
                    finished_at=utc_now(),
                    error="Host restarted",
                    cleanup="unconfirmed; unfinished node files clear on ownership loss",
                )
                self.save_transfer(transfer)
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
        require_public_metadata(campaign)
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
        require_public_metadata(run)
        self.db.execute(
            "INSERT INTO runs VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET document=excluded.document",
            (run["id"], run["created_at"], json.dumps(run)),
        )
        self.db.commit()

    def append_node_event(self, role: str, event: dict):
        require_public_metadata(event)
        self.db.execute(
            "INSERT INTO node_observations(role,received_at,document) VALUES (?,?,?)",
            (role, utc_now(), json.dumps(event)),
        )
        self.db.commit()

    def node_observation_cursor(self):
        return self.db.execute("SELECT coalesce(max(id), 0) FROM node_observations").fetchone()[0]

    def node_health_after(self, cursor):
        rows = self.db.execute(
            "SELECT id, role, received_at, document FROM node_observations WHERE id>? "
            "AND json_extract(document,'$.name')='health' ORDER BY id LIMIT 128",
            (cursor,),
        )
        return [dict(row) | {"document": json.loads(row["document"])} for row in rows]

    def memory_observation_records(self, role, observation_id):
        rows = self.db.execute(
            "SELECT document FROM node_observations WHERE role=? "
            "AND json_extract(document,'$.name')='memory.sample' "
            "AND json_extract(document,'$.data.observation_id')=? ORDER BY id LIMIT 12001",
            (role, observation_id),
        ).fetchall()
        if len(rows) > 12000:
            raise ValueError("Memory evidence exceeds the bounded observation record limit")
        return [json.loads(row[0]) for row in rows]

    def node_operation_records(self, role: str, operation_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT document FROM node_observations WHERE role=? "
            "AND json_extract(document, '$.kind')='event' "
            "AND json_extract(document, '$.data.operation_id')=? ORDER BY id LIMIT 40501",
            (role, operation_id),
        ).fetchall()
        if len(rows) > 40500:
            raise ValueError("Node operation evidence exceeds the bounded benchmark record limit")
        return [json.loads(row[0]) for row in rows]

    def runs(self) -> list[dict]:
        return [
            json.loads(row[0])
            for row in self.db.execute("SELECT document FROM runs ORDER BY created_at DESC")
        ]

    def run(self, run_id: str) -> dict | None:
        row = self.db.execute("SELECT document FROM runs WHERE id=?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def append_event(self, run_id: str, event: dict):
        require_public_metadata(event)
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
        require_public_metadata(reference)
        self.db.execute(
            "INSERT INTO references_audio VALUES (?, ?)", (reference["id"], json.dumps(reference))
        )
        self.db.commit()

    def references(self) -> list[dict]:
        return [
            json.loads(row[0])
            for row in self.db.execute("SELECT document FROM references_audio ORDER BY rowid DESC")
        ]

    def save_audio(self, record):
        require_public_metadata(record)
        self.db.execute(
            "INSERT INTO audio_operations VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET document=excluded.document",
            (record["id"], record["created_at"], json.dumps(record)),
        )
        self.db.commit()

    def audio_operations(self):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT document FROM audio_operations ORDER BY created_at DESC LIMIT 50"
            )
        ]

    def audio_operation(self, identifier):
        row = self.db.execute(
            "SELECT document FROM audio_operations WHERE id=?", (identifier,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def save_transfer(self, transfer):
        require_public_metadata(transfer)
        self.db.execute(
            "INSERT INTO artifact_transfers VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET document=excluded.document",
            (transfer["id"], transfer["created_at"], json.dumps(transfer)),
        )
        self.db.commit()

    def transfers(self):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT document FROM artifact_transfers ORDER BY created_at DESC LIMIT 50"
            )
        ]

    def transfer(self, transfer_id):
        row = self.db.execute(
            "SELECT document FROM artifact_transfers WHERE id=?", (transfer_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def close(self):
        self.db.close()
        self.lock_file.close()
