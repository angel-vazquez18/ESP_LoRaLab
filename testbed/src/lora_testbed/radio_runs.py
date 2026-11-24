"""Bounded physical single-fragment bring-up; this is not full IF-02 qualification."""

import asyncio
import hashlib
import io
import json
import secrets
import zipfile
from pathlib import Path
from time import monotonic, monotonic_ns
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from . import __version__, run_protocol_v2
from .adapters import require_execution_compatible
from .artifact_contract_v2 import SHA256, ArtifactID
from .experiments_v2 import KnownDataPlan, KnownDataSpec, Link, Radio, known_data, preview
from .models import StrictModel
from .storage import utc_now

TERMINAL = ("completed", "failed", "cancelled", "interrupted")
MAX_WIRE_BYTES = 1048576


class RadioRunRequest(StrictModel):
    direction: Literal["A_TO_B", "B_TO_A"] = "A_TO_B"
    message_bytes: int = Field(default=64, ge=1, le=215)
    source_seed: int = Field(default=743, ge=0, le=2**32 - 1)
    timeout_ms: int = Field(default=10000, ge=1000, le=30000)
    radio: Radio = Field(default_factory=lambda: Radio(tx_power_dbm=2))
    link: Link = Field(default_factory=Link)

    def plan(self):
        return KnownDataPlan(
            radio=self.radio,
            link=self.link,
            spec=KnownDataSpec(
                direction=self.direction,
                message_count=1,
                message_bytes=self.message_bytes,
                source_seed=self.source_seed,
                max_duration_ms=self.timeout_ms,
            ),
        )

    @model_validator(mode="after")
    def finite_subset(self):
        if self.link.ack_mode != "none" or self.link.max_retries:
            raise ValueError(
                "Initial physical bring-up requires unprotected data without ACK/retries"
            )
        if self.message_bytes > self.link.fragment_payload_bytes:
            raise ValueError("Choose one message no larger than the configured fragment capacity")
        timing = preview(self.plan())["timing"]
        if not timing["fits_selected_duration"]:
            raise ValueError(timing["duration_blocker"])
        return self


class PreparedArtifact(StrictModel):
    artifact_id: ArtifactID
    artifact_state: Literal["committed", "reserved"]
    sha256: SHA256
    length_bytes: int = Field(ge=1, le=215)


class RadioRuns:
    def __init__(self, store, nodes, artifacts):
        self.store, self.nodes, self.artifacts = store, nodes, artifacts
        self.current = self.task = None
        self.started = self.stop_requested = self.cleaning_up = False
        self.stop_lock = asyncio.Lock()
        self.shutting_down = False
        self.directory = store.root / "radio_runs"
        self.directory.mkdir(exist_ok=True)
        store.db.execute(
            "CREATE TABLE IF NOT EXISTS radio_runs_v1 "
            "(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL)"
        )
        store.db.commit()
        for row in store.db.execute("SELECT document FROM radio_runs_v1").fetchall():
            record = json.loads(row[0])
            if record["status"] not in TERMINAL:
                record.update(
                    status="interrupted",
                    stage="finished",
                    finished_at=utc_now(),
                    error="Host restarted; no automatic radio resume",
                    cleanup={
                        "confirmed": False,
                        "reason": "Previous ownership/stop is unconfirmed",
                    },
                )
                self.save(record)

    @property
    def busy(self):
        return self.current is not None

    def save(self, r):
        r["updated_at"] = utc_now()
        self.store.db.execute(
            "INSERT INTO radio_runs_v1 VALUES (?,?,?) ON CONFLICT(id) "
            "DO UPDATE SET document=excluded.document",
            (r["id"], r["created_at"], json.dumps(r)),
        )
        self.store.db.commit()

    def get(self, identifier):
        row = self.store.db.execute(
            "SELECT document FROM radio_runs_v1 WHERE id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise ValueError("Radio run not found")
        record = json.loads(row[0])
        record["available_content"] = [
            kind
            for kind in ("source", "recovered", "wire")
            if (
                self.directory / f"{identifier}.{'ndjson' if kind == 'wire' else kind + '.bin'}"
            ).is_file()
        ]
        return record

    @staticmethod
    def brief(record):
        fields = (
            "id",
            "created_at",
            "finished_at",
            "status",
            "stage",
            "scope",
            "sender",
            "receiver",
            "plan",
            "session_id",
            "verification",
            "error",
            "cleanup",
            "hardware_qualified",
        )
        value = {key: record.get(key) for key in fields}
        value["identities"] = {
            role: {key: identity[key] for key in ("device_id", "boot_id")}
            for role, identity in record["identities"].items()
        }
        value["signal"] = [
            {
                "role": event["role"],
                **{key: event["data"][key] for key in ("rssi_dbm", "snr_db", "rx_done_us")},
            }
            for event in record["events"]
            if event["name"] == "rx.frame"
        ][-5:]
        return value

    def snapshot(self):
        rows = self.store.db.execute(
            "SELECT document FROM radio_runs_v1 ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        return {
            "active_id": self.current["id"] if self.current else None,
            "active": self.brief(self.current) if self.current else None,
            "runs": [self.brief(json.loads(row[0])) for row in rows],
        }

    def content(self, identifier, kind):
        self.get(identifier)
        if kind not in ("source", "recovered", "wire"):
            raise ValueError("Unknown radio content")
        path = self.directory / f"{identifier}.{'ndjson' if kind == 'wire' else kind + '.bin'}"
        if not path.is_file():
            raise ValueError("This radio run has no requested content")
        return path

    def wire(self, r, value):
        data = (
            json.dumps(
                {"recorded_at": utc_now(), "host_monotonic_ns": monotonic_ns(), **value},
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        if r["wire_bytes"] + len(data) > MAX_WIRE_BYTES:
            raise ValueError("Radio evidence exceeds 1 MiB limit")
        with (self.directory / f"{r['id']}.ndjson").open("ab") as output:
            output.write(data)
        r["wire_bytes"] += len(data)

    def observe(self, role, event):
        r = self.current
        if not r or event.get("run_id") != r["id"]:
            return
        expected = r["identities"][role]
        if (event.get("device_id"), event.get("boot_id")) != (
            expected["device_id"],
            expected["boot_id"],
        ):
            r["evidence_error"] = "Radio event identity or boot changed"
            return
        try:
            self.wire(r, {"direction": "node_event", "role": role, "record": event})
            if len(r["events"]) >= 128:
                raise ValueError("Radio event count exceeds single-message limit")
            r["events"].append({"role": role, **event})
        except (ValueError, OSError) as exc:
            r["evidence_error"] = str(exc)

    def preflight(self, request):
        blockers = []
        ids = set()
        for role, node in self.nodes.items():
            if not node.connected or node.identity is None:
                blockers.append(f"Node {role} is disconnected")
                continue
            if node.snapshot()["connection_state"] != "connected" or node.health is None:
                blockers.append(f"Node {role} needs fresh health")
                continue
            if (
                node.health.state != "idle"
                or node.health.node_role != role
                or node.health.run_id is not None
                or node.rf_run_id
            ):
                blockers.append(f"Node {role} must be owned, idle and outside another RF session")
            if node.identity.device_id in ids:
                blockers.append("Connect two distinct physical device identities")
            ids.add(node.identity.device_id)
            for name in run_protocol_v2.EXECUTION_COMMANDS:
                try:
                    require_execution_compatible(
                        node.identity.model_dump(),
                        name,
                        node.health.capability_availability.model_dump(),
                    )
                except ValueError as exc:
                    blockers.append(f"Node {role}: {exc}")
                    break
            limits = node.health.capability_availability.resource_limits.get("execution_limits", {})
            needed = {
                "max_message_bytes": request.message_bytes,
                "max_messages_per_run": 1,
                "max_fragments_per_message": 1,
                "max_duration_ms": request.timeout_ms,
            }
            for key, value in needed.items():
                limit = limits.get(key)
                if type(limit) is not int or limit < value:
                    blockers.append(f"Node {role} lacks the required {key} limit")
            support = node.artifact_availability()
            if not {"artifact.list", "artifact.get"} <= set(support["commands"]):
                blockers.append(f"Node {role} needs compatible artifact readback")
        return {
            "ready": not blockers,
            "blockers": list(dict.fromkeys(blockers)),
            "required_nodes": 2,
            "scope": "one unprotected known-data message; physical bring-up only",
            "hardware_qualified": False,
        }

    async def start(self, request):
        if self.busy:
            raise RuntimeError("Another radio run owns the bench")
        ready = self.preflight(request)
        if not ready["ready"]:
            raise ValueError("; ".join(ready["blockers"]))
        identifier = str(uuid4())
        session = f"{secrets.randbits(64) or 1:016x}"
        source, receiver = ("A", "B") if request.direction == "A_TO_B" else ("B", "A")
        record = {
            "id": identifier,
            "created_at": utc_now(),
            "finished_at": None,
            "status": "running",
            "stage": "configuring",
            "scope": ready["scope"],
            "provenance": "hardware",
            "hardware_qualified": False,
            "sender": source,
            "receiver": receiver,
            "plan": request.plan().model_dump(),
            "session_id": session,
            "identities": {r: n.identity.model_dump() for r, n in self.nodes.items()},
            "host_version": __version__,
            "host_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "host_sources": {
                name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in (
                    "radio_runs.py",
                    "nodes.py",
                    "artifact_transfers.py",
                    "adapters.py",
                    "physical_wire_v2.py",
                    "experiments_v2.py",
                    "run_protocol_v2.py",
                )
            },
            "execution_schema_sha256": run_protocol_v2.schema_digest(),
            "applied_settings": {},
            "prepared": {},
            "summaries": {},
            "verification": None,
            "events": [],
            "transfers": {},
            "readback_manifests": {},
            "cleanup": None,
            "error": None,
            "evidence_error": None,
            "wire_bytes": 0,
            "baseline": {
                r: {
                    "event_gaps": n.event_gaps,
                    "framing_errors": n.framing_errors,
                    "telemetry_drops": n.health.telemetry_drops,
                }
                for r, n in self.nodes.items()
            },
        }
        self.current = record
        self.started = self.stop_requested = self.cleaning_up = False
        self.save(record)
        self.task = asyncio.create_task(self.run(record, request))
        return record.copy()

    def same_boot(self, r, role, *, cleanup=False):
        node = self.nodes[role]
        expected = r["identities"][role]
        if (
            not node.connected
            or node.identity is None
            or (node.identity.device_id, node.identity.boot_id)
            != (expected["device_id"], expected["boot_id"])
        ):
            raise ValueError(f"Node {role} disconnected or boot changed; radio work is not resumed")
        if r["evidence_error"] and not cleanup:
            raise ValueError(r["evidence_error"])
        return node

    async def command(self, r, role, name, args=None, *, cleanup=False):
        node = self.same_boot(r, role, cleanup=cleanup)
        kwargs = {"timeout": 0.75, "retries": 0} if cleanup else {}
        return await node.request(
            name,
            args,
            run_id=r["id"] if name.startswith(("session.", "run.")) else None,
            on_record=lambda value: self.trace_command(r, role, value, cleanup),
            **kwargs,
        )

    def trace_command(self, r, role, value, cleanup):
        try:
            self.wire(r, {"role": role, **value})
        except (ValueError, OSError) as exc:
            r["evidence_error"] = str(exc)
            if not cleanup:
                raise

    async def prepared(self, r, role, accepted):
        async with asyncio.timeout(5):
            while True:
                node = self.same_boot(r, role)
                event = next(
                    (
                        x
                        for x in node.operation_results
                        if x["operation_id"] == accepted["operation_id"]
                    ),
                    None,
                )
                if event:
                    if event["status"] != "completed":
                        raise ValueError(f"Node {role} preparation failed: {event}")
                    value = PreparedArtifact.model_validate(event["result"]).model_dump()
                    expected = hashlib.sha256(
                        known_data(
                            r["plan"]["spec"]["source_seed"], 1, r["plan"]["spec"]["message_bytes"]
                        )
                    ).hexdigest()
                    state = "committed" if role == r["sender"] else "reserved"
                    if (
                        value["artifact_state"] != state
                        or value["sha256"] != expected
                        or value["length_bytes"] != r["plan"]["spec"]["message_bytes"]
                    ):
                        raise ValueError(f"Node {role} prepared source metadata is inconsistent")
                    observed = next(
                        (
                            e
                            for e in r["events"]
                            if e["role"] == role and e["name"] == "run.prepared"
                        ),
                        None,
                    )
                    if (
                        observed is None
                        or observed["data"]["config_revision"]
                        != r["applied_settings"][role]["config_revision"]
                        or observed["data"]["source_sha256"] != expected
                    ):
                        raise ValueError(
                            f"Node {role} preparation evidence is missing or inconsistent"
                        )
                    return value
                await asyncio.sleep(0.01)

    async def retrieve(self, r, role, kind):
        self.same_boot(r, role)
        prepared = r["prepared"][role]
        transfer = await self.artifacts.start_download(role, prepared["artifact_id"])
        r["transfers"][role] = transfer["id"]
        self.save(r)
        while self.artifacts.busy:
            self.same_boot(r, role)
            await asyncio.sleep(0.01)
        saved = self.artifacts.get(transfer["id"])
        if saved["status"] != "completed":
            raise ValueError(f"Node {role} readback failed: {saved.get('error')}")
        manifest = saved["manifest"]
        if (
            manifest["artifact_id"],
            manifest["format"],
            manifest["kind"],
            manifest["length_bytes"],
        ) != (prepared["artifact_id"], "known_data", kind, r["plan"]["spec"]["message_bytes"]):
            raise ValueError(f"Node {role} returned inconsistent RF artifact metadata")
        r["readback_manifests"][role] = manifest
        data = self.artifacts.content(transfer["id"]).read_bytes()
        (self.directory / f"{r['id']}.{kind}.bin").write_bytes(data)
        return data

    async def cleanup(self, r):
        confirmed = True
        notes = {}
        for role, node in self.nodes.items():
            if node.rf_run_id != r["id"]:
                continue
            try:
                await self.command(
                    r,
                    role,
                    "run.stop",
                    {"reason": "host_shutdown" if self.shutting_down else "operator"},
                    cleanup=True,
                )
                await self.command(r, role, "session.close", cleanup=True)
                status = await self.command(r, role, "status.get", cleanup=True)
                if status["state"] != "idle" or status["run_id"] is not None:
                    raise ValueError("Node did not confirm idle")
                notes[role] = "session closed and idle confirmed"
            except (OSError, ValueError, TimeoutError) as exc:
                confirmed = False
                notes[role] = f"Unconfirmed: {exc}; ownership disconnected"
                await node.close(release=False)
        return {"confirmed": confirmed, "nodes": notes}

    async def run(self, r, request):
        try:
            self.started = True
            if self.stop_requested:
                raise asyncio.CancelledError
            async with asyncio.timeout(request.timeout_ms / 1000 + 45):
                plan = request.plan()
                budget = preview(plan)["timing"]["budget"]
                for role in "AB":
                    r["applied_settings"][role] = await self.command(
                        r,
                        role,
                        "config.set",
                        {"radio": plan.radio.model_dump(), "link": plan.link.model_dump()},
                    )
                    applied = r["applied_settings"][role]
                    expected = {
                        **plan.radio.model_dump(),
                        "ldro_enabled": preview(plan)["timing"]["predicted_ldro_enabled"],
                    }
                    if applied["radio"] != expected or applied["link"] != plan.link.model_dump():
                        raise ValueError(f"Node {role} applied settings differ from the request")
                for role, peer in [("A", "B"), ("B", "A")]:
                    identity = r["identities"][peer]
                    await self.command(
                        r,
                        role,
                        "session.open",
                        {
                            "session_id": r["session_id"],
                            "peer_device_id": identity["device_id"],
                            "peer_boot_id": identity["boot_id"],
                            "security": "none",
                            "tx_key_hex": None,
                            "rx_key_hex": None,
                        },
                    )
                r["stage"] = "preparing"
                self.save(r)
                for role in (r["receiver"], r["sender"]):
                    accepted = await self.command(
                        r, role, "run.prepare", {"spec": plan.spec.model_dump(), "budget": budget}
                    )
                    r["prepared"][role] = await self.prepared(r, role, accepted)
                r["stage"] = "arming"
                self.save(r)
                ready = await self.command(
                    r,
                    r["receiver"],
                    "run.arm",
                    {"config_revision": r["applied_settings"][r["receiver"]]["config_revision"]},
                )
                if ready["receiver_ready"] is not True:
                    raise ValueError("Receiver did not confirm readiness")
                armed = monotonic()
                r["stage"] = "transmitting"
                await self.command(
                    r,
                    r["sender"],
                    "run.start",
                    {"config_revision": r["applied_settings"][r["sender"]]["config_revision"]},
                )
                r["arm_to_start_reply_ms"] = (monotonic() - armed) * 1000
                if r["arm_to_start_reply_ms"] > 1000:
                    raise ValueError("Sender did not start within one second of receiver readiness")
                self.save(r)
                async with asyncio.timeout(request.timeout_ms / 1000 + 3):
                    while True:
                        for role in "AB":
                            self.same_boot(r, role)
                        for event in r["events"]:
                            if event["name"] == "run.summary":
                                r["summaries"][event["role"]] = event["data"]
                        if len(r["summaries"]) == 2:
                            break
                        await asyncio.sleep(0.01)
                r["stage"] = "retrieving"
                self.save(r)
                # Confirm terminal summaries independently of event arrival/order.
                for role in "AB":
                    r["summaries"][role] = await self.command(r, role, "run.summary")
                    summary = r["summaries"][role]
                    if (summary["session_id"], summary["config_revision"], summary["role"]) != (
                        r["session_id"],
                        r["applied_settings"][role]["config_revision"],
                        "sender" if role == r["sender"] else "receiver",
                    ):
                        raise ValueError(
                            f"Node {role} summary belongs to another session/settings/role"
                        )
                    if r["summaries"][role]["stop_reason"] != "completed":
                        raise ValueError(
                            f"Node {role} stopped with {r['summaries'][role]['stop_reason']}"
                        )
                    await self.command(r, role, "status.get")
                source = await self.retrieve(r, r["sender"], "source")
                recovered = await self.retrieve(r, r["receiver"], "recovered")
                expected = known_data(request.source_seed, 1, request.message_bytes)
                if source != expected or recovered != source:
                    raise ValueError(
                        "Actual source/recovered bytes differ from the independent source recipe"
                    )
                r["verification"] = {
                    "bytes_equal": True,
                    "length_bytes": len(recovered),
                    "sha256": hashlib.sha256(recovered).hexdigest(),
                    "sample_hex": recovered[:32].hex(),
                    "method": "independent source recipe plus exact source/recovered readback",
                }
                await self.required_evidence(r, expected)
                for role, node in self.nodes.items():
                    baseline = r["baseline"][role]
                    if (
                        node.event_gaps != baseline["event_gaps"]
                        or node.framing_errors != baseline["framing_errors"]
                        or node.health.telemetry_drops != baseline["telemetry_drops"]
                        or r["summaries"][role]["telemetry_drops"]
                    ):
                        raise ValueError(
                            f"Node {role} telemetry is incomplete; "
                            "do not interpret missing evidence as RF loss"
                        )
                tx = r["summaries"][r["sender"]]
                rx = r["summaries"][r["receiver"]]
                if (
                    tx["original_packets"] != 1
                    or tx["tx_attempts"] != 1
                    or rx["delivered_messages"] != 1
                    or rx["useful_delivered_bytes"] != len(expected)
                ):
                    raise ValueError("Node counters do not reconcile with one verified message")
                r["status"] = "completed"
        except asyncio.CancelledError:
            r["status"] = "interrupted" if self.shutting_down else "cancelled"
            r["error"] = "Host shutdown" if self.shutting_down else "Operator stopped the radio run"
        except Exception as exc:
            r["status"] = "failed"
            r["error"] = str(exc) or type(exc).__name__
        finally:
            self.cleaning_up = True
            r["stage"] = "stopping"
            self.save(r)
            for transfer in r["transfers"].values():
                if self.artifacts.busy:
                    await self.artifacts.cancel(transfer)
            r["cleanup"] = await self.cleanup(r)
            if not r["cleanup"]["confirmed"] and r["status"] == "completed":
                r["status"] = "failed"
                r["error"] = "Radio cleanup did not confirm both nodes idle"
            if r["status"] == "completed" and any(
                n.event_gaps != r["baseline"][role]["event_gaps"]
                or n.framing_errors != r["baseline"][role]["framing_errors"]
                or n.health is None
                or n.health.telemetry_drops != r["baseline"][role]["telemetry_drops"]
                for role, n in self.nodes.items()
            ):
                r["status"] = "failed"
                r["error"] = (
                    "Telemetry became incomplete during cleanup; verified bytes are retained"
                )
            r["finished_at"] = utc_now()
            r["stage"] = "finished"
            self.save(r)
            self.current = None

    async def required_evidence(self, r, expected):
        # Byte verification remains visible even when a required observation is absent.
        async with asyncio.timeout(1.5):
            while True:
                needed = [(role, name) for role in "AB" for name in ("run.prepared", "run.summary")]
                needed += [
                    (r["sender"], "tx.attempt"),
                    (r["receiver"], "rx.frame"),
                    (r["receiver"], "rx.accepted"),
                    (r["receiver"], "message.result"),
                ]
                missing = [
                    (role, name)
                    for role, name in needed
                    if not any(e["role"] == role and e["name"] == name for e in r["events"])
                ]
                if not missing:
                    break
                for role in "AB":
                    self.same_boot(r, role)
                try:
                    await asyncio.sleep(0.02)
                except asyncio.CancelledError:
                    raise
                if any(
                    self.nodes[role].event_gaps != r["baseline"][role]["event_gaps"]
                    for role in "AB"
                ):
                    raise ValueError(
                        "Required radio observations are missing; "
                        "RF delivery and telemetry loss differ"
                    )
        attempts = [
            e["data"] for e in r["events"] if e["role"] == r["sender"] and e["name"] == "tx.attempt"
        ]
        delivered = [
            e["data"]
            for e in r["events"]
            if e["role"] == r["receiver"] and e["name"] == "message.result"
        ]
        if (
            len(attempts) != 1
            or attempts[0]["status"] != "completed"
            or attempts[0]["session_id"] != r["session_id"]
            or attempts[0]["attempt_index"] != 1
            or attempts[0]["frame_bytes"] != 40 + len(expected)
        ):
            raise ValueError("Transmit observations do not identify one completed original attempt")
        if (
            len(delivered) != 1
            or delivered[0]["status"] != "delivered"
            or delivered[0]["sha256"] != hashlib.sha256(expected).hexdigest()
            or delivered[0]["message_bytes"] != len(expected)
        ):
            raise ValueError("Message observations do not reconcile with verified recovered bytes")

    async def stop(self, identifier=None):
        async with self.stop_lock:
            if not self.busy:
                return self.get(identifier) if identifier else None
            if identifier is not None and identifier != self.current["id"]:
                raise ValueError("This radio run is not active")
            identifier = self.current["id"]
            self.stop_requested = True
            if self.started and not self.cleaning_up:
                self.task.cancel()
            await asyncio.shield(self.task)
            return self.get(identifier)

    async def close(self):
        self.shutting_down = True
        if self.busy:
            await self.stop()

    def export(self, identifier):
        record = self.get(identifier)
        members = {"run.json": json.dumps(record, indent=2).encode()}
        for kind in ("source", "recovered", "wire"):
            try:
                path = self.content(identifier, kind)
            except ValueError:
                continue
            members[path.name] = path.read_bytes()
        for role, transfer_id in record["transfers"].items():
            members[f"transfers/{role}.json"] = json.dumps(
                self.artifacts.get(transfer_id), indent=2
            ).encode()
            trace = self.artifacts.directory / f"{transfer_id}.ndjson"
            if trace.is_file():
                members[f"transfers/{role}.ndjson"] = trace.read_bytes()
        if sum(len(data) for data in members.values()) > 2 * 1024 * 1024:
            raise ValueError(
                "Radio export exceeds 2 MiB; retrieve the linked file-transfer evidence separately"
            )
        members["sha256.json"] = json.dumps(
            {name: hashlib.sha256(data).hexdigest() for name, data in members.items()}, indent=2
        ).encode()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in members.items():
                archive.writestr(name, data)
        return output.getvalue()
