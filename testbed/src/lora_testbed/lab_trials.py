"""Run one deliberate bench fault between two matched intact controls."""

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from . import fault_accounting
from .experiments_v2 import known_data
from .session_keys import require_public_metadata
from .storage import utc_now


class LabTrials:
    def __init__(self, host):
        self.host, self.db = host, host.store.db
        self.owner = object()
        self.current = self.task = None
        self.stop_requested = asyncio.Event()
        self.shutting_down = False
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS lab_trials_v1 "
            "(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL)"
        )
        self.db.commit()
        for (raw,) in self.db.execute("SELECT document FROM lab_trials_v1").fetchall():
            row = json.loads(raw)
            if row["status"] == "running":
                row.update(
                    status="interrupted",
                    finished_at=utc_now(),
                    outcome="inconclusive",
                    reason="Host restarted; previous cleanup is unconfirmed",
                    stage="finished",
                )
                self.save(row)

    @property
    def busy(self):
        return self.current is not None

    def save(self, trial):
        require_public_metadata(trial)
        self.db.execute(
            "INSERT INTO lab_trials_v1 VALUES (?,?,?) ON CONFLICT(id) "
            "DO UPDATE SET document=excluded.document",
            (trial["id"], trial["created_at"], json.dumps(trial)),
        )
        self.db.commit()

    def get(self, identifier):
        row = self.db.execute(
            "SELECT document FROM lab_trials_v1 WHERE id=?", (identifier,)
        ).fetchone()
        if not row:
            raise ValueError("Lab trial not found")
        return json.loads(row[0])

    def snapshot(self):
        return {
            "active_id": self.current["id"] if self.current else None,
            "trials": [
                json.loads(row[0])
                for row in self.db.execute(
                    "SELECT document FROM lab_trials_v1 ORDER BY created_at DESC LIMIT 20"
                )
            ],
        }

    async def start(self, request):
        self.host.require_available_bench()
        ready = self.host.radio.preflight(request)
        if not ready["ready"]:
            raise ValueError("; ".join(ready["blockers"]))
        record = {
            "id": str(uuid4()),
            "created_at": utc_now(),
            "finished_at": None,
            "status": "running",
            "stage": "before",
            "outcome": "inconclusive",
            "reason": None,
            "request": request.model_dump(),
            "hardware_qualified": False,
            "children": {},
            "checks": [],
            "bindings": {role: self.host.adapter.bind(role) for role in "AB"},
            "assessment_source_sha256": hashlib.sha256(
                Path(fault_accounting.__file__).read_bytes()
            ).hexdigest(),
        }
        self.save(record)
        self.current = record
        self.stop_requested.clear()
        self.task = asyncio.create_task(self.run(record, request))
        return record.copy()

    async def child(self, record, stage, request):
        if self.stop_requested.is_set():
            return None
        for binding in record["bindings"].values():
            self.host.adapter.current(binding)
        record["stage"] = stage
        result = await self.host.start_radio(request, _owner=self.owner)
        identifier = result["id"]
        child_task = self.host.radio.task
        try:
            record["children"][stage] = identifier
            self.save(record)
            stop_wait = asyncio.create_task(self.stop_requested.wait())
            try:
                await asyncio.wait((child_task, stop_wait), return_when=asyncio.FIRST_COMPLETED)
            finally:
                stop_wait.cancel()
                await asyncio.gather(stop_wait, return_exceptions=True)
        finally:
            if not child_task.done():
                await self.host.radio.stop(identifier)
            await asyncio.shield(child_task)
        result = self.host.radio.get(identifier)
        if self.stop_requested.is_set() or result["status"] in ("cancelled", "interrupted"):
            return None
        if not (result.get("cleanup") or {}).get("confirmed"):
            raise ValueError(f"{stage.title()} run cleanup is unconfirmed")
        return result

    async def run(self, record, request):
        try:
            before = await self.child(record, "before", request.control())
            if before is None:
                return
            if not fault_accounting.verified_control(before):
                record["reason"] = "Before control did not verify intact delivery"
                return
            injected = await self.child(record, "fault", request)
            if injected is None:
                return
            # A confirmed cleanup permits a fresh intact recovery run.
            after = await self.child(record, "after", request.control())
            if after is None:
                return
            result = fault_accounting.assess(
                injected, known_data(request.source_seed, 1, request.message_bytes)
            )
            controls = fault_accounting.matched_controls(before, injected, after)
            record["checks"] = [
                {
                    "code": "matched_before_and_after_controls",
                    "outcome": "pass" if controls else "inconclusive",
                    "evidence": [],
                },
                *result["checks"],
            ]
            record["outcome"] = result["outcome"] if controls else "inconclusive"
            if not controls:
                record["reason"] = "Both intact controls must match the selected trial"
            record["status"] = "completed"
        except Exception as exc:
            record.update(status="failed", reason=str(exc) or type(exc).__name__)
        finally:
            if record["status"] == "running":
                if record["reason"]:
                    record["status"] = "failed"
                else:
                    record["status"] = (
                        "interrupted"
                        if self.shutting_down or not self.stop_requested.is_set()
                        else "cancelled"
                    )
                    record["reason"] = (
                        "Trial interrupted"
                        if record["status"] == "interrupted"
                        else ("Operator stopped the trial")
                    )
            record.update(stage="finished", finished_at=utc_now())
            try:
                self.save(record)
            finally:
                self.current = self.task = None

    async def stop(self, identifier=None):
        if not self.current or (identifier and identifier != self.current["id"]):
            raise ValueError("Lab trial is not active")
        identifier = self.current["id"]
        self.stop_requested.set()
        await asyncio.shield(self.task)
        return self.get(identifier)

    async def close(self):
        self.shutting_down = True
        if self.current:
            await self.stop()
