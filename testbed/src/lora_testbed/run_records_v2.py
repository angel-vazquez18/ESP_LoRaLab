"""Versioned execution records sharing the backend's existing SQLite connection."""

import json
from time import monotonic_ns
from uuid import uuid4

from .analysis_v2 import RunMetrics
from .experiments_v2 import KnownDataPlan
from .storage import utc_now


class RunRecords:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS execution_runs_v2 (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS execution_events_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                received_at TEXT NOT NULL, received_monotonic_ns INTEGER NOT NULL,
                document TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS execution_events_v2_run ON execution_events_v2(run_id,id);
            CREATE TABLE IF NOT EXISTS execution_campaigns_v2 (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS device_enrollments_v2 (
                device_id TEXT PRIMARY KEY, enrollment_id TEXT NOT NULL);
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(execution_events_v2)")}
        if "device_enrollment_id" not in columns:
            self.db.execute("ALTER TABLE execution_events_v2 ADD COLUMN device_enrollment_id TEXT")
            self.db.commit()
        for run in self.runs(limit=10000):
            if run["status"] not in ("completed", "failed", "blocked", "cancelled", "interrupted"):
                metrics = RunMetrics(KnownDataPlan.model_validate(run["plan"]), run["identities"])
                metrics.baseline_drops.update(run.get("baseline_telemetry_drops", {}))
                metrics.session_id = run.get("session_id")
                metrics.revisions = {
                    role: data["config_revision"] for role, data in run["applied_settings"].items()
                }
                for row in self.events(run["id"]):
                    try:
                        metrics.accept(row["document"])
                    except ValueError:
                        metrics.invalidate("Identity changed before host restart")
                run.update(
                    status="interrupted",
                    reason="Host restarted",
                    stage="finished",
                    finished_at=utc_now(),
                )
                run["assessment"], run["assertions"] = metrics.assess("interrupted")
                run["metrics"] = metrics.snapshot()
                self.save_run(run)
        for campaign in self.campaigns():
            if campaign["status"] in ("running", "paused", "stopping"):
                campaign.update(
                    status="interrupted", reason="Host restarted", finished_at=utc_now()
                )
                for case in campaign["cases"]:
                    if case["status"] in ("pending", "running"):
                        case.update(status="interrupted", reason="Host restarted")
                self.save_campaign(campaign)

    def _save(self, table, record):
        self.db.execute(
            f"INSERT INTO {table} VALUES (?,?,?) ON CONFLICT(id) "
            "DO UPDATE SET document=excluded.document",
            (record["id"], record["created_at"], json.dumps(record)),
        )
        self.db.commit()

    def _get(self, table, identity):
        row = self.db.execute(f"SELECT document FROM {table} WHERE id=?", (identity,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_run(self, record):
        self._save("execution_runs_v2", record)

    def run(self, identity):
        return self._get("execution_runs_v2", identity)

    def runs(self, limit=20):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT document FROM execution_runs_v2 ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        ]

    def save_campaign(self, record):
        self._save("execution_campaigns_v2", record)

    def campaign(self, identity):
        return self._get("execution_campaigns_v2", identity)

    def campaigns(self):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT document FROM execution_campaigns_v2 ORDER BY created_at DESC LIMIT 100"
            )
        ]

    def enrollment(self, device_id):
        row = self.db.execute(
            "SELECT enrollment_id FROM device_enrollments_v2 WHERE device_id=?", (device_id,)
        ).fetchone()
        if row:
            return row[0]
        identity = str(uuid4())
        self.db.execute("INSERT INTO device_enrollments_v2 VALUES (?,?)", (device_id, identity))
        self.db.commit()
        return identity

    def append(self, run_id, event, enrollment_id=None):
        cursor = self.db.execute(
            "INSERT INTO execution_events_v2 "
            "(run_id,received_at,received_monotonic_ns,document,device_enrollment_id) "
            "VALUES (?,?,?,?,?)",
            (run_id, utc_now(), monotonic_ns(), json.dumps(event), enrollment_id),
        )
        self.db.commit()
        return cursor.lastrowid

    def events(self, identity, after=0, limit=None):
        sql = "SELECT * FROM execution_events_v2 WHERE run_id=? AND id>? ORDER BY id"
        args = [identity, after]
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        return [
            dict(row) | {"document": json.loads(row["document"])}
            for row in self.db.execute(sql, args)
        ]
