"""Physical diagnostic checks and durable procedure evidence, including old records."""

import asyncio
import csv
import hashlib
import io
import json
import zipfile
from copy import deepcopy
from uuid import uuid4

from . import control_v2, v2
from .adapters import require_control_compatible
from .paths import REPOSITORY_ROOT
from .serial_validation import serial_plan
from .storage import utc_now

TERMINAL = {"completed", "failed", "blocked", "cancelled", "interrupted"}


class ProcedureService:
    def __init__(self, store, nodes):
        self.store, self.db, self.nodes = store, store.db, nodes
        self.task, self.current = None, None
        sources = (
            "docs/test_procedures.md",
            "docs/testbed_contract_v2.md",
            "testbed/src/lora_testbed/procedure_runs.py",
            "testbed/src/lora_testbed/nodes.py",
            "testbed/src/lora_testbed/serial_validation.py",
            "testbed/src/lora_testbed/host.py",
            "testbed/src/lora_testbed/catalog.py",
            "testbed/src/lora_testbed/v2.py",
            "testbed/src/lora_testbed/control_v2.py",
            "testbed/src/lora_testbed/adapters.py",
            "testbed/uv.lock",
        )
        self.source_sha256 = {
            s: hashlib.sha256((REPOSITORY_ROOT / s).read_bytes()).hexdigest() for s in sources
        }
        self.profile_sha256 = hashlib.sha256(
            json.dumps(
                {
                    "sources": self.source_sha256,
                    "schema": v2.schema_digest(),
                    "control_schema": control_v2.schema_digest(),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS procedure_runs_v2 (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS procedure_evidence_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                case_id TEXT NOT NULL, received_at TEXT NOT NULL, document TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS procedure_evidence_v2_run
                ON procedure_evidence_v2(run_id,id);
        """)
        for run in self.runs(10000):
            if run["status"] not in TERMINAL:
                for case in run["cases"]:
                    if case["status"] in ("running", "pending"):
                        case.update(
                            status="interrupted", assessment="inconclusive", reason="Host restarted"
                        )
                run.update(
                    status="interrupted",
                    assessment="inconclusive",
                    reason="Host restarted",
                    finished_at=utc_now(),
                    full_procedure_passed=False,
                    active_case=None,
                )
                self.save(run)

    @property
    def busy(self):
        return self.task is not None and not self.task.done()

    def get(self, identity):
        row = self.db.execute(
            "SELECT document FROM procedure_runs_v2 WHERE id=?", (identity,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def runs(self, limit=20):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT document FROM procedure_runs_v2 ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        ]

    def save(self, run):
        run["completed_cases"] = sum(c["status"] in TERMINAL for c in run["cases"])
        self.db.execute(
            "INSERT INTO procedure_runs_v2 VALUES (?,?,?) ON CONFLICT(id) "
            "DO UPDATE SET document=excluded.document",
            (run["id"], run["created_at"], json.dumps(run)),
        )
        self.db.commit()

    def snapshot(self):
        return {
            "active_run": deepcopy(self.current) if self.busy else None,
            "runs": [
                {
                    k: r.get(k)
                    for k in (
                        "id",
                        "catalog_id",
                        "mode",
                        "status",
                        "assessment",
                        "created_at",
                        "finished_at",
                        "scope",
                        "full_procedure_passed",
                    )
                }
                for r in self.runs()
            ],
        }

    def append(self, run_id, case_id, document):
        self.db.execute(
            "INSERT INTO procedure_evidence_v2 (run_id,case_id,received_at,document) "
            "VALUES (?,?,?,?)",
            (run_id, case_id, utc_now(), json.dumps(document)),
        )
        self.db.commit()

    def evidence(self, identity, after=0, limit=500, case_id=None):
        sql = "SELECT * FROM procedure_evidence_v2 WHERE run_id=? AND id>?"
        args = [identity, after]
        if case_id:
            sql += " AND case_id=?"
            args.append(case_id)
        return [
            dict(r) | {"document": json.loads(r["document"])}
            for r in self.db.execute(sql + " ORDER BY id LIMIT ?", (*args, limit))
        ]

    def all_evidence(self, identity):
        after = 0
        while rows := self.evidence(identity, after):
            yield from rows
            after = rows[-1]["id"]

    async def start_serial(self, spec, roles):
        if self.busy:
            raise RuntimeError("A check already owns the bench")
        run = {
            **serial_plan(spec),
            "roles": roles,
            "id": str(uuid4()),
            "created_at": utc_now(),
            "finished_at": None,
            "status": "running",
            "assessment": "not_assessed",
            "reason": None,
            "active_case": None,
            "source_sha256": self.source_sha256,
            "profile_sha256": self.profile_sha256,
            "schema_sha256": v2.schema_digest(),
            "control_schema_sha256": control_v2.schema_digest(),
            "transport": "physical USB serial",
            "timing_basis": "device-local uptime; host timestamps record receipt only",
            "identities": {r: self.nodes[r].identity.model_dump() for r in roles},
            "cases": [
                {
                    "id": str(uuid4()),
                    "role": r,
                    "status": "pending",
                    "assessment": "not_assessed",
                    "assertions": [],
                }
                for r in roles
            ],
            "case_count": len(roles),
        }
        self.current = run
        self.save(run)
        self.task = asyncio.create_task(self.execute(run, spec))
        await asyncio.sleep(0)  # Ensure immediate cancellation reaches the finalizer.
        return deepcopy(run)

    async def execute(self, run, spec):
        try:
            for case in run["cases"]:
                node = self.nodes[case["role"]]
                run["active_case"] = case["id"]
                case["status"] = "running"
                self.save(run)
                before = node.snapshot()
                self.append(run["id"], case["id"], {"snapshot_before": before})
                try:
                    async with asyncio.timeout(30):

                        def record(document, case_id=case["id"]):
                            self.append(run["id"], case_id, document)

                        hello = v2.Hello.model_validate(
                            await node.request("hello", on_record=record)
                        )
                        require_control_compatible(hello.model_dump())
                        expected = run["identities"][case["role"]]
                        if hello.schema_sha256 != expected["schema_sha256"]:
                            raise ValueError("Node control schema changed during check")
                        if (hello.device_id, hello.boot_id) != (
                            expected["device_id"],
                            expected["boot_id"],
                        ):
                            raise ValueError("Device identity or boot changed")
                        previous = before["health"]["uptime_us"]
                        for _ in range(spec.cycles):
                            await node.request("control.keepalive", on_record=record)
                            health = v2.Health.model_validate(
                                await node.request("status.get", on_record=record)
                            )
                            if (
                                health.node_role != case["role"]
                                or health.state != "idle"
                                or health.run_id is not None
                            ):
                                raise ValueError("Node lost ownership or is not idle")
                            if previous is not None and health.uptime_us <= previous:
                                raise ValueError("Device uptime did not advance")
                            if health.telemetry_drops != before["health"]["telemetry_drops"]:
                                raise ValueError("Node telemetry dropped during check")
                            previous = health.uptime_us
                            await asyncio.sleep(0.1)
                        after = node.snapshot()
                        if not node.connected or after["connection_state"] != "connected":
                            raise ValueError("Node disconnected or health became stale")
                        if (
                            after["event_gaps"] != before["event_gaps"]
                            or after["framing_errors"] != before["framing_errors"]
                        ):
                            raise ValueError("Event gap or malformed serial input during check")
                        if node.health.telemetry_drops != before["health"]["telemetry_drops"]:
                            raise ValueError("Node telemetry dropped during check")
                        self.append(run["id"], case["id"], {"snapshot_after": after})
                        case.update(
                            status="completed",
                            assessment="pass",
                            assertions=[
                                "Hardware identity and boot unchanged",
                                "Ownership retained; node idle",
                                "Status commands completed; uptime advanced",
                                "No new framing faults, event gaps or telemetry drops",
                            ],
                        )
                except Exception as exc:
                    case.update(
                        status="failed",
                        assessment="inconclusive",
                        reason=str(exc) or type(exc).__name__,
                    )
                    self.append(
                        run["id"],
                        case["id"],
                        {"error": case["reason"], "snapshot": node.snapshot()},
                    )
                    run.update(status="failed", assessment="inconclusive", reason=case["reason"])
                    break
                finally:
                    self.save(run)
            else:
                run.update(
                    status="completed",
                    assessment="pass",
                    reason="Diagnostic check completed; full IF-01 qualification remains open",
                )
        except asyncio.CancelledError:
            run.update(
                status="interrupted" if run["reason"] == "Host shutdown" else "cancelled",
                assessment="inconclusive",
            )
        except Exception as exc:
            run.update(status="failed", assessment="inconclusive", reason=str(exc))
        finally:
            for case in run["cases"]:
                if case["status"] in ("pending", "running"):
                    case.update(
                        status="skipped" if case["status"] == "pending" else run["status"],
                        assessment="inconclusive",
                        reason=run["reason"],
                    )
            # Diagnostic checks never arm or transmit. Connections and their leases stay
            # with the bench; disconnect/shutdown performs the normal control release.
            run.update(active_case=None, finished_at=utc_now(), full_procedure_passed=False)
            self.save(run)

    async def stop(self, shutdown=False):
        if self.busy:
            self.current["reason"] = "Host shutdown" if shutdown else "Stopped by operator"
            self.task.cancel()
            await self.task
        return deepcopy(self.current)

    def csv(self, run):
        output = io.StringIO(newline="")
        fields = [
            "run_id",
            "case_id",
            "role",
            "group",
            "variant",
            "repetition",
            "status",
            "assessment",
            "cleanup_verified",
            "reason",
            "assertions_json",
            "direction",
            "message_bytes",
            "host_duration_s",
            "run_ids_json",
            "campaign_ids_json",
            "measurements_json",
            "files_json",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for case in run["cases"]:
            writer.writerow(
                {
                    "run_id": run["id"],
                    "case_id": case["id"],
                    **{k: case.get(k) for k in fields[2:]},
                    "assertions_json": json.dumps(case.get("assertions", [])),
                    **{
                        f"{key}_json": json.dumps(case.get(key, []))
                        for key in ("run_ids", "campaign_ids", "measurements", "files")
                    },
                }
            )
        return output.getvalue()

    def bundle(self, run):
        output, hashes = io.BytesIO(), {}
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:

            def save(name, content):
                archive.writestr(name, content)
                hashes[name] = hashlib.sha256(content).hexdigest()

            save("procedure.json", json.dumps(run, indent=2).encode())
            save("cases.csv", self.csv(run).encode())
            save(
                "provenance.json",
                json.dumps(
                    {
                        "mode": run["mode"],
                        "hardware_validated": False,
                        "transport": run["transport"],
                        "timing_basis": run["timing_basis"],
                        "note": run.get("note", "Historical procedure evidence"),
                    }
                ).encode(),
            )
            digest = hashlib.sha256()
            with archive.open("evidence.jsonl", "w") as stream:
                for row in self.all_evidence(run["id"]):
                    content = (json.dumps(row) + "\n").encode()
                    digest.update(content)
                    stream.write(content)
            hashes["evidence.jsonl"] = digest.hexdigest()
            for case in run["cases"]:
                for item in case.get("files", []):
                    content = (self.store.root / item["relative_path"]).read_bytes()
                    if hashlib.sha256(content).hexdigest() != item["sha256"]:
                        raise ValueError("Procedure artifact failed its saved SHA-256 check")
                    save(f"case-evidence/{case['id']}/{item['name']}", content)
            archive.writestr(
                "manifest.json", json.dumps({"record_version": 1, "sha256": hashes}, indent=2)
            )
        return output.getvalue()
