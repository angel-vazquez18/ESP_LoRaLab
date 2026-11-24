"""Durable finite local diagnostic jobs using the common physical adapter."""

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from . import __version__
from .session_keys import require_public_metadata
from .storage import utc_now

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
WAIT_SECONDS = 35


class DiagnosticJobs:
    def __init__(self, store, nodes, adapter):
        self.store, self.nodes, self.adapter = store, nodes, adapter
        self.current = self.task = None
        self.starting_task = None
        self.directory = store.root / "diagnostic_runs"
        self.directory.mkdir(exist_ok=True)
        self.shutting_down = False
        self.started = self.stop_requested = self.cleaning_up = False
        self.stop_lock = asyncio.Lock()
        store.db.execute(
            "CREATE TABLE IF NOT EXISTS diagnostic_jobs_v1 "
            "(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL)"
        )
        store.db.commit()
        for row in store.db.execute("SELECT document FROM diagnostic_jobs_v1").fetchall():
            record = json.loads(row[0])
            if record["status"] not in TERMINAL:
                record.update(
                    status="interrupted",
                    finished_at=utc_now(),
                    error=record.get("error") or "Host restarted; no automatic resume",
                    cleanup={
                        "confirmed": False,
                        "error": "Previous stop is unconfirmed",
                        "errors": [],
                        "steps": [],
                    },
                )
                self.save(record)

    @property
    def busy(self):
        return self.current is not None

    def save(self, record):
        require_public_metadata(record)
        record["updated_at"] = utc_now()
        self.store.db.execute(
            "INSERT INTO diagnostic_jobs_v1 VALUES (?,?,?) ON CONFLICT(id) "
            "DO UPDATE SET document=excluded.document",
            (record["id"], record["created_at"], json.dumps(record)),
        )
        self.store.db.commit()

    def get(self, identifier):
        row = self.store.db.execute(
            "SELECT document FROM diagnostic_jobs_v1 WHERE id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown diagnostic job")
        return json.loads(row[0])

    def snapshot(self):
        return {
            "active_id": self.current["id"] if self.current else None,
            "runs": [
                json.loads(row[0])
                for row in self.store.db.execute(
                    "SELECT document FROM diagnostic_jobs_v1 ORDER BY created_at DESC LIMIT 20"
                )
            ],
        }

    def trace(self, record, value):
        require_public_metadata(value)
        wire = (
            json.dumps({"recorded_at": utc_now(), **value}, separators=(",", ":")) + "\n"
        ).encode()
        if record["wire_bytes"] + len(wire) > 65536:
            raise ValueError("Diagnostic command evidence exceeds 64 KiB")
        self.store.append_node_event(record["role"], value)
        with (self.directory / f"{record['id']}.ndjson").open("ab") as output:
            output.write(wire)
        record["wire_bytes"] += len(wire)

    def evidence(self, identifier, include_records=False):
        record = self.get(identifier)
        path = self.directory / f"{record['id']}.ndjson"
        wire = path.read_bytes() if path.exists() else b""
        if record.get("wire_sha256") and hashlib.sha256(wire).hexdigest() != record["wire_sha256"]:
            raise ValueError("Diagnostic command evidence hash differs")
        return {
            "job": record,
            "wire": [json.loads(line) for line in wire.splitlines()],
            "operation_events": self.store.node_operation_records(
                record["role"], record["operation_id"]
            )
            if include_records and record["operation_id"]
            else None,
        }

    async def start(self, role, binding, args):
        if self.busy:
            raise RuntimeError("Another diagnostic job owns the bench")
        record = {
            "id": str(uuid4()),
            "created_at": utc_now(),
            "finished_at": None,
            "role": role,
            "physical_binding": binding,
            "arguments": args,
            "identity": self.adapter.current(binding).identity.model_dump(),
            "status": "preparing",
            "operation_id": None,
            "node_result": None,
            "wire_bytes": 0,
            "error": None,
            "cleanup": None,
            "hardware_qualified": False,
            "host_version": __version__,
            "host_sources": {
                name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in ("diagnostic_jobs.py", "physical_adapter.py", "nodes.py")
            },
        }
        self.save(record)  # Reserve durable ownership before the command can have effects.
        self.current = record
        self.starting_task = asyncio.current_task()
        self.started = self.stop_requested = self.cleaning_up = False
        try:
            accepted = await self.adapter.request(
                binding, "diag.run", args, on_record=lambda value: self.trace(record, value)
            )
            record.update(
                status="running", operation_id=accepted["operation_id"], accepted=accepted
            )
            self.save(record)
        except BaseException as exc:
            record.update(
                status="interrupted" if isinstance(exc, asyncio.CancelledError) else "failed",
                error=(
                    "Host shutdown during diagnostic acceptance"
                    if self.shutting_down
                    else "Diagnostic acceptance interrupted"
                )
                if isinstance(exc, asyncio.CancelledError)
                else str(exc) or type(exc).__name__,
            )
            await self.finish(record)
            raise
        self.starting_task = None
        self.task = asyncio.create_task(self.run(record))
        return {**accepted, "host_run_id": record["id"]}

    async def run(self, record):
        self.started = True
        try:
            if self.stop_requested:
                raise asyncio.CancelledError
            async with asyncio.timeout(WAIT_SECONDS):
                while True:
                    node = self.adapter.current(record["physical_binding"])
                    result = next(
                        (
                            value
                            for value in node.operation_results
                            if value["operation_id"] == record["operation_id"]
                        ),
                        None,
                    )
                    if result:
                        record["node_result"] = result
                        record["status"] = result["status"]
                        if result["status"] != "completed":
                            record["error"] = (
                                f"Node diagnostic {result['status']}: {result.get('error')}"
                            )
                        break
                    await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            record.update(
                status="interrupted" if self.shutting_down else "cancelled",
                error="Host shutdown" if self.shutting_down else "Operator stopped diagnostic",
            )
        except Exception as exc:
            node = self.nodes[record["role"]]
            interrupted = (
                not node.connected
                or node.connection_id != record["physical_binding"]["connection_id"]
            )
            record.update(
                status="interrupted" if interrupted else "failed",
                error=str(exc) or type(exc).__name__,
            )
        finally:
            await self.finish(record)

    async def finish(self, record):
        self.cleaning_up = True
        try:
            record["cleanup"] = await self.adapter.cleanup(
                record["physical_binding"],
                operation_id=record["operation_id"],
                local_work=True,
                on_record=lambda value: self.trace(record, value),
            )
            if record["status"] == "completed" and any(
                error["command"] == "evidence" for error in record["cleanup"]["errors"]
            ):
                record.update(status="failed", error="Diagnostic cleanup evidence incomplete")
            if record["status"] == "completed" and not record["cleanup"]["confirmed"]:
                record.update(status="failed", error="Diagnostic cleanup did not confirm idle")
            path = self.directory / f"{record['id']}.ndjson"
            record["wire_sha256"] = hashlib.sha256(
                path.read_bytes() if path.exists() else b""
            ).hexdigest()
            record["finished_at"] = utc_now()
            self.save(record)
        finally:
            self.current = self.task = None
            self.starting_task = None

    async def stop(self, operation_id=None):
        async with self.stop_lock:
            record, task = self.current, self.task
            if not record or (operation_id and record["operation_id"] != operation_id):
                raise ValueError("No matching active diagnostic job")
            self.stop_requested = True
            if task:
                if self.started and not self.cleaning_up:
                    task.cancel()
                await asyncio.shield(task)
            return {
                "operation_id": record["operation_id"],
                "state": "idle" if record["cleanup"]["confirmed"] else "unknown",
                "cleanup": record["cleanup"],
            }

    async def close(self):
        self.shutting_down = True
        if self.current and self.task:
            await self.stop()
        elif self.starting_task and self.starting_task is not asyncio.current_task():
            task = self.starting_task
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
