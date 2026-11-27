"""Bounded physical known-data message workflow; this is not full IF-02 qualification."""

import asyncio
import base64
import hashlib
import io
import json
import secrets
import zipfile
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, monotonic_ns
from typing import Literal
from uuid import UUID, uuid4, uuid5

from pydantic import Field, model_validator

from . import __version__, echo_accounting, run_protocol_v2
from .adapters import require_execution_compatible
from .artifact_contract_v2 import SHA256, ArtifactID
from .evidence_worker import SavedEvidenceWorker
from .experiments_v2 import (
    KnownDataPlan,
    KnownDataSpec,
    Link,
    Radio,
    airtime_us,
    known_data,
    ldro_enabled,
    preview,
)
from .fault_protocol_v2 import Injection
from .models import StrictModel
from .physical_adapter import PhysicalAdapter
from .radio_accounting import failed_ranges, reconcile, reconcile_sweep_loss
from .radio_security import assess as assess_security
from .session_keys import EphemeralKeySet, require_public_metadata
from .storage import utc_now

TERMINAL = ("completed", "failed", "cancelled", "interrupted")
MAX_WIRE_BYTES = 64 * 1024 * 1024
MAX_RADIO_EVENTS = 65568


class RadioRunRequest(StrictModel):
    security: Literal["none", "aes128_gcm"] = "none"
    direction: Literal["A_TO_B", "B_TO_A"] = "A_TO_B"
    message_bytes: int = Field(default=64, ge=1, le=65536)
    source_seed: int = Field(default=743, ge=0, le=2**32 - 1)
    timeout_ms: int = Field(default=10000, ge=1000, le=3600000)
    radio: Radio = Field(default_factory=lambda: Radio(tx_power_dbm=2))
    link: Link = Field(default_factory=Link)

    def plan(self):
        return KnownDataPlan(
            radio=self.radio,
            link=self.link,
            spec=KnownDataSpec(
                direction=self.direction,
                security=self.security,
                message_count=1,
                message_bytes=self.message_bytes,
                source_seed=self.source_seed,
                max_duration_ms=self.timeout_ms,
            ),
        )

    @model_validator(mode="after")
    def finite_subset(self):
        if self.link.max_retries > 2:
            raise ValueError("Physical node firmware supports at most two retries")
        timing = preview(self.plan())["timing"]
        if not timing["fits_selected_duration"]:
            raise ValueError(timing["duration_blocker"])
        return self


class SweepRadioRunRequest(RadioRunRequest):
    message_bytes: Literal[64] = 64

    @model_validator(mode="after")
    def one_unacknowledged_frame(self):
        if self.link.ack_mode != "none" or self.link.fragment_payload_bytes < self.message_bytes:
            raise ValueError("An RF sweep observation needs one unacknowledged DATA frame")
        return self


class TransmitterPowerRunRequest(SweepRadioRunRequest):
    receiver_power_dbm: int = Field(ge=2, le=20)


class PeerMismatchCheck(RadioRunRequest):
    # Internal negative control, available through the procedure runner.
    peer_radio: Radio

    @classmethod
    def from_control(cls, request):
        peer = request.radio.model_copy(update={"frequency_hz": 916000000})
        return cls(**request.model_dump(), peer_radio=peer)

    @model_validator(mode="after")
    def requires_distinct_settings(self):
        if self.peer_radio == self.radio:
            raise ValueError("A peer mismatch check needs different settings")
        return self


class PreparedCancellationCheck(RadioRunRequest):
    """An internal MEM-01 case that cancels valid work immediately after preparation."""

    message_bytes: Literal[1200] = 1200
    security: Literal["none"] = "none"


class ReceiveEvidenceGapCheck(RadioRunRequest):
    """Internal OPS-01 case with one omitted host receive observation."""

    message_bytes: Literal[64] = 64
    security: Literal["none"] = "none"

    @model_validator(mode="after")
    def one_frame(self):
        if self.link.fragment_payload_bytes < self.message_bytes or self.link.ack_mode != "none":
            raise ValueError("The receive evidence fixture requires one unacknowledged DATA frame")
        return self


class PrepareLimitCheck(RadioRunRequest):
    message_bytes: Literal[64] = 64
    attempted_bytes: int = Field(ge=2, le=65537)


class KeyMismatchRunRequest(RadioRunRequest):
    security: Literal["aes128_gcm"] = "aes128_gcm"

    @model_validator(mode="after")
    def negative_single_frame(self):
        if self.link.ack_mode != "none" or self.message_bytes > self.link.fragment_payload_bytes:
            raise ValueError("Wrong-key controls require one unacknowledged fragment")
        return self


class PeerProfileMismatchCheck(RadioRunRequest):
    peer_security: Literal["none", "aes128_gcm"]


class LabRadioRunRequest(RadioRunRequest):
    injection: Injection
    exhaust_attempts: bool = False

    @model_validator(mode="after")
    def lab_scope(self):
        target, action, link = self.injection, self.injection.action, self.link
        if target.message_id != 1 or target.attempt_index != 1:
            raise ValueError("This trial selects the first attempt or opportunity in one message")
        start = target.fragment_index * link.fragment_payload_bytes
        end = (target.fragment_index + ((target.block_size or 1) - 1)) * link.fragment_payload_bytes
        if end >= self.message_bytes:
            raise ValueError("Selected fragment or block exceeds the message")
        if action in ("xor_byte", "replay") and self.security != "aes128_gcm":
            raise ValueError("This case requires AES-GCM")
        if (
            action in ("xor_byte", "replay", "duplicate", "reverse_block")
            and link.ack_mode != "none"
        ):
            raise ValueError("This case requires ACK disabled")
        if action == "drop_ack" and (link.ack_mode != "stop_wait" or not link.max_retries):
            raise ValueError("An ACK-suppression trial needs stop-and-wait and a recovery retry")
        if self.exhaust_attempts and (action != "drop" or link.ack_mode != "stop_wait"):
            raise ValueError("All-attempt drops require a stop-and-wait DATA target")
        body = min(link.fragment_payload_bytes, self.message_bytes - start)
        if action == "xor_byte" and target.byte_offset >= 56 + body:
            raise ValueError("Mutation offset exceeds the selected frame")
        timing = preview(self.plan())["timing"]
        budget = self.lab_budget(timing["budget"])
        if (
            timing["required_max_duration_ms"] * 1000 + budget["fault_budget_us"]
            > self.timeout_ms * 1000
        ):
            raise ValueError("Additional fault airtime exceeds the selected duration")
        return self

    def lab_budget(self, ordinary):
        action = self.injection.action
        extra = 0
        if action in ("replay", "duplicate"):
            capacity = self.link.fragment_payload_bytes
            body = min(capacity, self.message_bytes - capacity * self.injection.fragment_index)
            wire = 40 + body + (16 if self.security == "aes128_gcm" else 0)
            guard = 1_500_000 if action == "replay" else max(20000, self.link.guard_us)
            extra = airtime_us(self.radio, wire) + 80000 + guard
        return {
            **ordinary,
            "fault_budget_us": extra,
            "reassembly_timeout_us": ordinary["reassembly_timeout_us"] + extra,
        }

    def injections(self):
        first = self.injection
        entries = [first]
        if self.exhaust_attempts:
            entries.extend(
                first.model_copy(
                    update={
                        "injection_id": str(uuid5(UUID(first.injection_id), str(attempt))),
                        "attempt_index": attempt,
                    }
                )
                for attempt in range(2, 2 + self.link.max_retries)
            )
        return [entry.model_dump() for entry in entries]

    def control(self):
        return RadioRunRequest.model_validate(
            self.model_dump(exclude={"injection", "exhaust_attempts"})
        )


class EchoRadioRunRequest(RadioRunRequest):
    message_bytes: int = Field(default=64, ge=1, le=215)

    def plan(self):
        return run_protocol_v2.EchoPlan(
            radio=self.radio,
            link=self.link,
            spec=run_protocol_v2.EchoSpec(
                direction=self.direction,
                security=self.security,
                message_bytes=self.message_bytes,
                source_seed=self.source_seed,
                max_duration_ms=self.timeout_ms,
            ),
        )


class TransmitterPowerEchoRunRequest(EchoRadioRunRequest):
    receiver_power_dbm: int = Field(ge=2, le=20)


class EchoMissingReplyCheck(EchoRadioRunRequest):
    """Internal TIME-01 case with a deliberately stopped responder."""

    message_bytes: Literal[64] = 64
    security: Literal["none"] = "none"


class EncodedMessagePlan(KnownDataPlan):
    spec: run_protocol_v2.EncodedSourceSpec


class EncodedRadioRunRequest(RadioRunRequest):
    security: Literal["aes128_gcm"] = "aes128_gcm"
    source_seed: None = None
    message_bytes: int = Field(ge=8, le=1200, multiple_of=8)
    source_artifact_id: ArtifactID
    sample_count: int = Field(ge=1, le=24000)
    expected_sha256: SHA256
    timeout_ms: int = Field(default=30000, ge=1000, le=3600000)

    def plan(self):
        return EncodedMessagePlan(
            radio=self.radio,
            link=self.link,
            spec=run_protocol_v2.EncodedSourceSpec(
                direction=self.direction,
                message_bytes=self.message_bytes,
                source_artifact_id=self.source_artifact_id,
                sample_count=self.sample_count,
                expected_sha256=self.expected_sha256,
                max_duration_ms=self.timeout_ms,
            ),
        )


class FixedRateMessagePlan(KnownDataPlan):
    spec: run_protocol_v2.FixedRateSourceSpec


class FixedRateRadioRunRequest(EncodedRadioRunRequest):
    message_bytes: Literal[1200] = 1200
    sample_count: Literal[24000] = 24000
    timeout_ms: Literal[90000] = 90000

    def plan(self):
        return FixedRateMessagePlan(
            radio=self.radio,
            link=self.link,
            spec=run_protocol_v2.FixedRateSourceSpec(
                direction=self.direction,
                source_artifact_id=self.source_artifact_id,
                expected_sha256=self.expected_sha256,
            ),
        )

    @model_validator(mode="after")
    def finite_subset(self):
        if self.link.max_retries > 2:
            raise ValueError("Fixed-rate trials support at most two retries")
        return self

    def budget(self):
        single = EncodedMessagePlan(
            radio=self.radio,
            link=self.link,
            spec=run_protocol_v2.EncodedSourceSpec(
                direction=self.direction,
                source_artifact_id=self.source_artifact_id,
                expected_sha256=self.expected_sha256,
                message_bytes=self.message_bytes,
                sample_count=self.sample_count,
                max_duration_ms=self.timeout_ms,
            ),
        )
        calculated = preview(single)["timing"]["budget"]
        return {**calculated, "reassembly_timeout_us": 90_000_000}


class PreparedArtifact(StrictModel):
    artifact_id: ArtifactID
    artifact_state: Literal["committed", "reserved"]
    sha256: SHA256
    length_bytes: int = Field(ge=1, le=65536)


def require_numbered_idle(record, role, status):
    if (
        status["state"] != "idle"
        or status["run_id"] is not None
        or not status["security_ready"]
        or status["config_revision"] != record["applied_settings"][role]["config_revision"]
    ):
        raise ValueError(f"Node {role} did not retain the idle numbered session")


@dataclass
class NumberedSession:
    wire_run_id: str
    session_id: str
    bindings: dict
    count: int
    lab: bool
    next_message: int = 1
    applied_settings: dict | None = None
    key_set_id: str | None = None


class RadioRuns:
    def __init__(self, store, nodes, artifacts, adapter=None, observations=None):
        self.store, self.nodes, self.artifacts = store, nodes, artifacts
        self.adapter = adapter or PhysicalAdapter(nodes)
        self.observations = observations
        self.current = self.task = None
        self.started = self.stop_requested = self.cleaning_up = False
        self.stop_lock = asyncio.Lock()
        self.shutting_down = False
        self.evidence_worker = SavedEvidenceWorker("Another echo distribution is in progress")
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
                self.recover_interrupted(record)

    def recover_interrupted(self, record):
        record.update(
            status="interrupted",
            failure_stage=record.get("failure_stage") or record["stage"],
            stage="finished",
            finished_at=utc_now(),
            reason_code="host_restart",
            error=record.get("error") or "Host restarted; no automatic radio resume",
            cleanup={
                "confirmed": False,
                "reason": "Previous ownership/stop is unconfirmed",
            },
        )
        # Fingerprint the bytes retained after the crash. Delivery and cleanup
        # still require their own evidence from the original run.
        path = self.directory / f"{record['id']}.ndjson"
        try:
            if "wire" not in record.get("saved_files", {}) and path.is_file():
                with path.open("rb") as stream:
                    size = path.stat().st_size
                    if size > MAX_WIRE_BYTES:
                        raise ValueError("Interrupted trace exceeds the radio evidence limit")
                    checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                record.setdefault("saved_files", {})["wire"] = {
                    "length_bytes": size,
                    "sha256": checksum,
                    "fingerprint_scope": "retained_after_host_restart",
                }
                record.update(wire_bytes=size, wire_sha256=checksum)
        except (OSError, ValueError):
            record.setdefault("saved_file_errors", {})["wire"] = (
                "Interrupted trace could not be fingerprinted within the evidence limit"
            )
        self.save(record)

    @property
    def busy(self):
        return self.current is not None

    def save(self, r):
        require_public_metadata(r)
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
            "security",
            "verification",
            "accounting",
            "timing",
            "host_transaction",
            "source_observation",
            "lab",
            "missing_evidence",
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
                **{
                    key: event["data"][key]
                    for key in ("rssi_dbm", "snr_db", "rx_done_us", "frame_type")
                },
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
        record = self.get(identifier)
        if kind not in ("source", "recovered", "wire"):
            raise ValueError("Unknown radio content")
        path = self.directory / f"{identifier}.{'ndjson' if kind == 'wire' else kind + '.bin'}"
        if not path.is_file():
            raise ValueError("This radio run has no requested content")
        expected = record.get("saved_files", {}).get(kind)
        if expected:
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if path.stat().st_size != expected["length_bytes"] or actual != expected["sha256"]:
                raise ValueError("Saved radio file failed integrity verification (length/hash)")
        return path

    def wire(self, r, value):
        require_public_metadata(value)
        data = (
            json.dumps(
                {"recorded_at": utc_now(), "host_monotonic_ns": monotonic_ns(), **value},
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        if r["wire_bytes"] + len(data) > MAX_WIRE_BYTES:
            raise ValueError("Radio evidence exceeds 64 MiB limit")
        with (self.directory / f"{r['id']}.ndjson").open("ab") as output:
            output.write(data)
        r["wire_bytes"] += len(data)

    def observe(self, role, event):
        r = self.current
        if not r or event.get("run_id") != r.get("wire_run_id", r["id"]):
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
            if len(r["events"]) >= MAX_RADIO_EVENTS:
                raise ValueError("Radio event count exceeds bounded message-evidence limit")
            r["events"].append({"role": role, **event})
        except (ValueError, OSError) as exc:
            r["evidence_error"] = str(exc)

    def preflight(self, request, *, numbered=None):
        blockers = []
        if (
            isinstance(request, PeerProfileMismatchCheck)
            and request.security != request.peer_security
        ):
            blockers.append("Peer security profile mismatch")
        fixed_source = isinstance(request, FixedRateRadioRunRequest)
        fixed_sender = "A" if request.direction == "A_TO_B" else "B"
        if fixed_source and self.observations is None:
            blockers.append("The source observation service is unavailable")
        ids = set()
        for role, node in self.nodes.items():
            if not node.connected or node.identity is None:
                blockers.append(f"Node {role} is disconnected")
                continue
            if node.snapshot()["connection_state"] != "connected" or node.health is None:
                blockers.append(f"Node {role} needs fresh health")
                continue
            previous = numbered is not None and numbered.next_message > 1
            if node.health.node_role != role or (
                node.rf_run_id != numbered.wire_run_id
                if previous
                else node.health.state != "idle" or node.health.run_id is not None or node.rf_run_id
            ):
                blockers.append(
                    f"Node {role} no longer owns the numbered session"
                    if previous
                    else f"Node {role} must be owned, idle and outside another RF session"
                )
            if node.identity.device_id in ids:
                blockers.append("Connect two distinct physical device identities")
            ids.add(node.identity.device_id)
            try:
                identity = node.identity.model_dump()
                available = node.health.capability_availability.model_dump()
                for name in run_protocol_v2.BASE_EXECUTION_COMMANDS:
                    require_execution_compatible(identity, name, available)
            except ValueError as exc:
                blockers.append(f"Node {role}: {exc}")
                continue
            use_lab = isinstance(request, LabRadioRunRequest) or (
                numbered is not None and numbered.lab
            )
            if use_lab or isinstance(request, KeyMismatchRunRequest):
                if not (
                    node.identity.capabilities.fault_injection
                    and node.health.capability_availability.fault_injection
                ):
                    blockers.append(f"Node {role} needs explicit lab firmware")
                elif use_lab:
                    for name in run_protocol_v2.LAB_FAULT_COMMANDS:
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
            if fixed_source:
                if role == fixed_sender and (
                    node.identity.capabilities.resource_limits.get("execution_limits", {}).get(
                        "fixed_rate_encoded"
                    )
                    is not True
                ):
                    blockers.append(f"Node {role} lacks the independent fixed-rate source worker")
                try:
                    require_execution_compatible(
                        node.identity.model_dump(),
                        "run.source",
                        node.health.capability_availability.model_dump(),
                    )
                except ValueError as exc:
                    blockers.append(f"Node {role}: {exc}")
            if isinstance(request, EncodedRadioRunRequest) and (
                limits.get("encoded_source") is not True
                or node.identity.capabilities.resource_limits.get("execution_limits", {}).get(
                    "encoded_source"
                )
                is not True
            ):
                blockers.append(f"Node {role} lacks committed encoded-source transport")
            needed = {
                "max_message_bytes": request.message_bytes,
                "max_messages_per_run": 1,
                "max_fragments_per_message": (
                    request.message_bytes + request.link.fragment_payload_bytes - 1
                )
                // request.link.fragment_payload_bytes,
                "max_duration_ms": request.timeout_ms,
            }
            if request.link.ack_mode == "stop_wait":
                needed["max_retries"] = request.link.max_retries
            features = preview(request.plan())["required_capabilities"]
            for feature in features:
                if not getattr(node.identity.capabilities, feature, False) or not getattr(
                    node.health.capability_availability, feature, False
                ):
                    blockers.append(f"Node {role} lacks current {feature} support")
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
            "scope": "one controlled laboratory fault; physical qualification separate"
            if isinstance(request, LabRadioRunRequest)
            else "one verified echo; requester-local RTT; physical qualification separate"
            if isinstance(request, EchoRadioRunRequest)
            else "60-second protected fixed-rate source with at most 30 seconds of drain"
            if fixed_source
            else "one protected encoded message; physical qualification separate"
            if isinstance(request, EncodedRadioRunRequest)
            else "one known-data message with selected security; physical bring-up only",
            "hardware_qualified": False,
        }

    def numbered_session(self, count, *, lab):
        if not 1 <= count <= 256:
            raise ValueError("Numbered session must declare 1 through 256 messages")
        bindings = {role: self.adapter.bind(role) for role in self.nodes}
        return NumberedSession(
            str(uuid4()), f"{secrets.randbits(64) or 1:016x}", bindings, count, lab
        )

    async def close_numbered(self, numbered, record):
        details, evidence = {}, []
        for role, binding in numbered.bindings.items():
            details[role] = await self.adapter.cleanup(
                binding,
                run_id=numbered.wire_run_id,
                on_record=lambda value, selected=role: evidence.append({"role": selected, **value}),
            )
        for row in evidence:
            record(row)
        return details

    async def start(self, request, *, numbered=None):
        if self.busy:
            raise RuntimeError("Another radio run owns the bench")
        if numbered:
            if not 1 <= numbered.next_message <= numbered.count or (
                request.security != "aes128_gcm" or request.plan().spec.source != "known_data"
            ):
                raise ValueError(
                    "A numbered session requires the next protected known-data message"
                )
            for binding in numbered.bindings.values():
                self.adapter.current(binding)
        ready = self.preflight(request, numbered=numbered) if numbered else self.preflight(request)
        if not ready["ready"]:
            raise ValueError("; ".join(ready["blockers"]))
        identifier = str(uuid4())
        session = numbered.session_id if numbered else f"{secrets.randbits(64) or 1:016x}"
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
            "failure_stage": None,
            "security": {
                "profile": request.security,
                "key_set_id": None,
                "provisioned": {},
                "keys_retired_on_host": True,
                "assessment": None,
            },
            "identities": {r: n.identity.model_dump() for r, n in self.nodes.items()},
            "physical_bindings": {role: self.adapter.bind(role) for role in self.nodes},
            "host_version": __version__,
            "host_transaction": {
                "start_ns": monotonic_ns(),
                "end_ns": None,
                "elapsed_ns": None,
                "scope": "host_configuration_through_readback_and_cleanup",
            },
            "host_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "host_sources": {
                name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in (
                    "radio_runs.py",
                    "radio_accounting.py",
                    "echo_accounting.py",
                    "evidence_worker.py",
                    "radio_security.py",
                    "session_keys.py",
                    "rf_events_v2.py",
                    "fault_protocol_v2.py",
                    "control_v2.py",
                    "v2.py",
                    "nodes.py",
                    "artifact_transfers.py",
                    "adapters.py",
                    "physical_adapter.py",
                    "physical_wire_v2.py",
                    "experiments_v2.py",
                    "run_protocol_v2.py",
                )
            },
            "execution_schema_sha256": run_protocol_v2.schema_digest(),
            "applied_settings": {},
            "prepared": {},
            "summaries": {},
            "rf_window_closed_at": None,
            "verification": None,
            "accounting": None,
            "missing_evidence": None,
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
        if numbered:
            record.update(
                wire_run_id=numbered.wire_run_id,
                message_id=numbered.next_message,
                numbered_count=numbered.count,
                physical_bindings=numbered.bindings,
                scope="one verified member of a protected numbered session",
            )
        if isinstance(request, KeyMismatchRunRequest):
            record["security"]["controlled_receiver_key_mismatch"] = True
        if isinstance(request, (TransmitterPowerRunRequest, TransmitterPowerEchoRunRequest)):
            record["receiver_power_dbm"] = request.receiver_power_dbm
        if isinstance(request, LabRadioRunRequest):
            injection = request.injection.model_dump()
            if numbered:
                injection["message_id"] = numbered.next_message
            record["lab"] = {
                "injection": injection,
                "role": receiver
                if injection["stage"] in ("rx_before_reassembly", "tx_before_radio")
                else source,
                "budget": request.lab_budget(preview(request.plan())["timing"]["budget"]),
                "report": None,
                "fire": None,
            }
            if request.exhaust_attempts:
                record["lab"]["exhaustion_targets"] = request.injections()
        if isinstance(request, EchoRadioRunRequest):
            record["timing"] = None
        self.current = record
        self.started = self.stop_requested = self.cleaning_up = False
        self.save(record)
        pending = (
            self.run(record, request, numbered=numbered) if numbered else self.run(record, request)
        )
        self.task = asyncio.create_task(pending)
        return record.copy()

    def same_boot(self, r, role, *, cleanup=False):
        node = self.adapter.current(r["physical_bindings"][role])
        if r["evidence_error"] and not cleanup:
            raise ValueError(r["evidence_error"])
        return node

    async def command(self, r, role, name, args=None, *, cleanup=False, key_set_id=None):
        self.same_boot(r, role, cleanup=cleanup)
        kwargs = {"timeout": 0.75, "retries": 0} if cleanup else {}
        return await self.adapter.request(
            r["physical_bindings"][role],
            name,
            args,
            run_id=r.get("wire_run_id", r["id"])
            if name.startswith(("session.", "run.", "fault."))
            else None,
            on_record=lambda value: self.trace_command(r, role, value, cleanup),
            key_set_id=key_set_id,
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
                    spec = r["plan"]["spec"]
                    expected = (
                        spec["expected_sha256"]
                        if spec["source"] in ("encoded_source", "fixed_rate_encoded")
                        else hashlib.sha256(
                            known_data(
                                spec["source_seed"], r.get("message_id", 1), spec["message_bytes"]
                            )
                        ).hexdigest()
                    )
                    if (
                        spec["source"] in ("encoded_source", "fixed_rate_encoded")
                        and role == r["sender"]
                        and value["artifact_id"] != spec["source_artifact_id"]
                    ):
                        raise ValueError("Encoded sender substituted a different source artifact")
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
                        or observed["data"].get("message_id") != r.get("message_id")
                        or (r.get("lab") and observed["data"]["budget"] != r["lab"]["budget"])
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
        spec = r["plan"]["spec"]
        archive = spec["source"] == "fixed_rate_encoded" and role == r["receiver"]
        encoded = spec["source"] in ("encoded_source", "fixed_rate_encoded") and not archive
        expected_format = "codec2_3200_v1" if encoded else "known_data"
        expected_length = 24000 if archive else spec["message_bytes"]
        if (
            manifest["artifact_id"] != prepared["artifact_id"]
            or manifest["format"] != expected_format
            or manifest["length_bytes"] != expected_length
            or (not (encoded and role == r["sender"]) and manifest["kind"] != kind)
        ):
            raise ValueError(f"Node {role} returned inconsistent RF artifact metadata")
        if encoded and (
            manifest["sha256"] != spec["expected_sha256"]
            or manifest["sample_count"] != spec["sample_count"]
            or (
                role == r["receiver"]
                and manifest["source_artifact_id"] != spec["source_artifact_id"]
            )
        ):
            raise ValueError(f"Node {role} encoded provenance differs from the selected clip")
        r["readback_manifests"][role] = manifest
        data = self.artifacts.content(transfer["id"]).read_bytes()
        (self.directory / f"{r['id']}.{kind}.bin").write_bytes(data)
        return data

    async def cleanup(self, r, numbered=None):
        retired = {}
        for role, identifier in r.get(
            "retire_echo_artifacts", r.get("retire_data_artifacts", {})
        ).items():
            try:
                await self.command(
                    r, role, "artifact.delete", {"artifact_id": identifier}, cleanup=True
                )
                retired[role] = {"artifact_id": identifier, "confirmed": True}
            except (TimeoutError, ValueError, OSError) as exc:
                retired[role] = {"artifact_id": identifier, "confirmed": False, "error": str(exc)}
        retain = (
            numbered is not None
            and r["status"] == "completed"
            and r["message_id"] < numbered.count
            and all(item["confirmed"] for item in retired.values())
        )
        idle_errors = {}
        if retain:
            for role in self.nodes:
                try:
                    status = await self.command(r, role, "status.get", cleanup=True)
                    require_numbered_idle(r, role, status)
                except (OSError, ValueError, TimeoutError) as exc:
                    idle_errors[role] = str(exc)
            if not idle_errors:
                return {
                    "confirmed": True,
                    "session_retained": True,
                    "retired_data_artifacts": retired,
                    "nodes": {role: "idle with numbered session retained" for role in self.nodes},
                }
        details = {}
        for role in self.nodes:
            details[role] = await self.adapter.cleanup(
                r["physical_bindings"][role],
                run_id=r.get("wire_run_id", r["id"]),
                on_record=lambda value, selected=role: self.trace_command(r, selected, value, True),
            )
        return {
            "confirmed": all(detail["confirmed"] for detail in details.values())
            and all(item["confirmed"] for item in retired.values())
            and not idle_errors,
            **({"retained_session_errors": idle_errors} if idle_errors else {}),
            **(
                {
                    "retired_echo_artifacts"
                    if r["plan"]["spec"]["source"] == "echo"
                    else "retired_data_artifacts": retired
                }
                if retired
                else {}
            ),
            "nodes": {
                role: "; ".join(detail["steps"])
                if detail["confirmed"]
                else f"Unconfirmed: {detail['error']}"
                for role, detail in details.items()
            },
            "details": details,
        }

    async def maybe_fire_lab_replay(self, r):
        lab = r["lab"]
        expected = hashlib.sha256(
            known_data(r["plan"]["spec"]["source_seed"], 1, r["plan"]["spec"]["message_bytes"])
        ).hexdigest()
        receiver_delivered = any(
            event["role"] == r["receiver"]
            and event["name"] == "message.result"
            and event["data"]["status"] == "delivered"
            and event["data"]["sha256"] == expected
            for event in r["events"]
        )
        source_draining = any(
            event["role"] == r["sender"]
            and event["name"] == "run.state"
            and event["data"]["state"] == "draining"
            for event in r["events"]
        )
        if not (receiver_delivered and source_draining):
            return
        report = await self.command(r, r["sender"], "fault.status", {"offset": 0, "limit": 4})
        if (
            report["session_id"] != r["session_id"]
            or report["count"] != 1
            or len(report["entries"]) != 1
            or report["entries"][0]["injection_id"] != lab["injection"]["injection_id"]
            or report["entries"][0]["state"] != "retained"
            or not report["fire_window_open"]
        ):
            raise ValueError("Retained replay is missing or outside its authorized run window")
        lab["fire"] = await self.command(
            r, r["sender"], "fault.fire", {"injection_id": lab["injection"]["injection_id"]}
        )
        self.save(r)

    async def cancel_prepared_workload(self, r, request):
        prepared = {
            event["role"]: event["event_seq"]
            for event in r["events"]
            if event["name"] == "run.prepared"
        }
        if set(prepared) != {"A", "B"}:
            raise ValueError("Controlled cancellation requires prepared evidence from both nodes")
        r["prepared_cancellation"] = {"prepared_events": prepared, "stop_replies": {}}
        for role in (r["receiver"], r["sender"]):
            result = await self.command(r, role, "run.stop", {"reason": "operator"})
            r["prepared_cancellation"]["stop_replies"][role] = result
        source = await self.retrieve(r, r["sender"], "source")
        if source != known_data(request.source_seed, 1, request.message_bytes):
            raise ValueError("Cancelled source differs from the independent recipe; retained")
        self.register_retirement(r, r["sender"])
        r["status"] = "cancelled"
        r["error"] = "Controlled cancellation of prepared work"

    async def verify_prepare_refusal(self, r, request, spec, budget):
        caps = {
            role: node.health.capability_availability.resource_limits["execution_limits"][
                "max_message_bytes"
            ]
            for role, node in self.nodes.items()
        }
        # Offer the request to a node whose own cap would be exceeded.
        role = min((r["receiver"], r["sender"]), key=caps.__getitem__)
        evidence = r["resource_refusal"] = {
            "role": role,
            "advertised_limits": caps,
            "requested_message_bytes": request.attempted_bytes,
        }
        before = evidence["status_before"] = await self.command(r, role, "status.get")
        initial = evidence["artifacts_before"] = await self.command(r, role, "artifact.list")
        reply = await self.same_boot(r, role).exercise_prepare_limit(
            {"spec": spec.model_dump(), "budget": budget},
            r["id"],
            request.attempted_bytes,
            lambda value: self.trace_command(r, role, value, False),
        )
        evidence["reply"] = reply.model_dump()
        after = evidence["status_after"] = await self.command(r, role, "status.get")
        listing = evidence["artifacts_after"] = await self.command(r, role, "artifact.list")
        unchanged = ("config_revision", "radio", "link", "reset_cause", "security_ready")
        evidence["preserved"] = {
            "idle": all(
                status["state"] == "idle" and status["operation_id"] is None
                for status in (before, after)
            ),
            "configuration_and_boot": after["uptime_us"] >= before["uptime_us"]
            and all(before[key] == after[key] for key in unchanged),
            "artifacts_and_allocations": initial == listing
            and before["memory"]["buffers"]["artifacts_reserved"]
            == after["memory"]["buffers"]["artifacts_reserved"]
            and before["memory"]["allocation_failures"] == after["memory"]["allocation_failures"],
            "no_execution_events": not r["events"],
        }
        if reply.ok or reply.error.code != "RESOURCE_LIMIT":
            raise ValueError("Node did not reply RESOURCE_LIMIT to the oversized prepare")
        if not all(evidence["preserved"].values()):
            raise ValueError("An oversized prepare changed node state, allocations or artifacts")
        r["status"] = "completed"

    async def collect_fixed_rate_evidence(self, r, request):
        sender, receiver = r["sender"], r["receiver"]
        for role, node in self.nodes.items():
            baseline = r["baseline"][role]
            summary = r["summaries"][role]
            if any(
                (
                    node.event_gaps != baseline["event_gaps"],
                    node.framing_errors != baseline["framing_errors"],
                    node.health.telemetry_drops != baseline["telemetry_drops"],
                    summary["telemetry_drops"],
                    summary["cleanup_errors"],
                )
            ):
                raise ValueError(f"Node {role} did not retain complete fixed-source telemetry")
        observed = await self.command(r, receiver, "run.source")
        recovered = await self.retrieve(r, receiver, "recovered")
        reference = await self.retrieve(r, sender, "source")
        archive_sha = hashlib.sha256(recovered).hexdigest()
        delivered = [
            event["data"]
            for event in r["events"]
            if event["role"] == receiver
            and event["name"] == "message.result"
            and event["data"]["status"] == "delivered"
        ]
        ids = observed["delivered_message_ids"]
        if (
            observed["status"] is not None
            or observed["archive_artifact_id"] != r["prepared"][receiver]["artifact_id"]
            or observed["archive_sha256"] != archive_sha
            or hashlib.sha256(reference).hexdigest() != request.expected_sha256
            or sorted(row["message_id"] for row in delivered) != ids
            or len(ids) != r["summaries"][receiver]["delivered_messages"]
            or any(row["sha256"] != request.expected_sha256 for row in delivered)
        ):
            raise ValueError("Fixed-source receiver summary, events or archive identity differ")
        snapshot = {
            "binding": r["physical_bindings"][sender],
            "baseline": r["baseline"][sender],
            "receiver_provenance": {
                "binding": r["physical_bindings"][receiver],
                "archive_manifest": r["readback_manifests"][receiver],
                "status_reply": observed,
            },
            "delivery": {
                "message_ids": ids,
                "reference_b64": base64.b64encode(reference).decode(),
                "archive_b64": base64.b64encode(recovered).decode(),
                "archive_sha256": archive_sha,
            },
        }
        record = await self.observations.collect_source(sender, r["id"], parent_radio=snapshot)
        assessment = record["assessments"]["source"]
        r["source_observation"] = {
            "id": record["id"],
            "sha256": record["evidence_sha256"],
            "accounting": assessment["accounting"]["status"],
            "capacity": assessment["capacity"],
            "delivery": assessment["delivery"],
            "export": f"/api/workload-assessments/{record['id']}/export",
        }
        verified = assessment["delivery"]["assessment"] == "verified"
        if verified:
            self.register_retirement(r, receiver)
        r["accounting"] = {
            "evidence_complete": verified and assessment["accounting"]["status"] == "consistent",
            "scope": "fixed_rate_encoded",
        }
        if not verified:
            raise ValueError("Fixed-source receiver archive bytes did not verify")

    async def open_radio_session(self, r, request, plan, key_mismatch):
        for role in "AB":
            selected = plan.radio
            if role == r["receiver"]:
                if isinstance(request, PeerMismatchCheck):
                    selected = request.peer_radio
                elif isinstance(
                    request, (TransmitterPowerRunRequest, TransmitterPowerEchoRunRequest)
                ):
                    selected = plan.radio.model_copy(
                        update={"tx_power_dbm": request.receiver_power_dbm}
                    )
            r["applied_settings"][role] = await self.command(
                r,
                role,
                "config.set",
                {"radio": selected.model_dump(), "link": plan.link.model_dump()},
            )
            applied = r["applied_settings"][role]
            expected = {
                **selected.model_dump(),
                "ldro_enabled": ldro_enabled(selected),
            }
            if applied["radio"] != expected or applied["link"] != plan.link.model_dump():
                raise ValueError(f"Node {role} applied settings differ from the request")
        if isinstance(request, PeerMismatchCheck):
            r["configuration_check"] = "peer_mismatch"
            raise ValueError("Peer settings mismatch before provisioning and arming")
        r["stage"] = "provisioning"
        key_set = EphemeralKeySet() if request.security == "aes128_gcm" else None
        alternate = None
        if key_set:
            r["security"].update(key_set_id=key_set.key_set_id, keys_retired_on_host=False)
        try:
            if key_mismatch:
                alternate = EphemeralKeySet()
                r["security"]["receiver_alternate_key_set_id"] = alternate.key_set_id
            for role, peer in [("A", "B"), ("B", "A")]:
                identity = r["identities"][peer]
                args = (
                    key_set.arguments(
                        role, r["session_id"], identity["device_id"], identity["boot_id"]
                    )
                    if key_set
                    else {
                        "session_id": r["session_id"],
                        "peer_device_id": identity["device_id"],
                        "peer_boot_id": identity["boot_id"],
                        "security": "none",
                        "tx_key_hex": None,
                        "rx_key_hex": None,
                    }
                )
                try:
                    if alternate and role == r["receiver"]:
                        replacement = alternate.arguments(
                            role,
                            r["session_id"],
                            identity["device_id"],
                            identity["boot_id"],
                        )
                        args["rx_key_hex"] = replacement["rx_key_hex"]
                        replacement.clear()
                    await self.command(
                        r,
                        role,
                        "session.open",
                        args,
                        key_set_id=key_set.key_set_id if key_set else None,
                    )
                finally:
                    args.clear()  # Drop hex-string references as soon as the request ends.
                status = await self.command(r, role, "status.get")
                if (
                    status["security_ready"] != bool(key_set)
                    or status["node_role"] != role
                    or status["state"] != "idle"
                    or status["run_id"] not in (None, r["id"])
                ):
                    raise ValueError(
                        f"Node {role} did not confirm the selected owned security state"
                    )
                r["security"]["provisioned"][role] = True
        finally:
            if alternate:
                alternate.close()
            if key_set:
                key_set.close()
            r["security"]["keys_retired_on_host"] = True

    async def run(self, r, request, *, numbered=None):
        try:
            self.started = True
            if self.stop_requested:
                raise asyncio.CancelledError
            async with asyncio.timeout(request.timeout_ms / 1000 + 45):
                plan = request.plan()
                lab = r.get("lab")
                key_mismatch = isinstance(request, KeyMismatchRunRequest)
                fixed_source = isinstance(request, FixedRateRadioRunRequest)
                budget = (
                    request.budget()
                    if fixed_source
                    else lab["budget"]
                    if lab
                    else preview(plan)["timing"]["budget"]
                )
                if plan.spec.source in ("known_data", "echo", "fixed_rate_encoded"):
                    r["initial_artifact_ids"] = {}
                    for role in "AB":
                        listing = await self.command(r, role, "artifact.list")
                        r["initial_artifact_ids"][role] = [
                            item["artifact_id"] for item in listing["artifacts"]
                        ]
                if numbered and r["message_id"] > 1:
                    r["applied_settings"] = numbered.applied_settings
                    r["security"].update(
                        key_set_id=numbered.key_set_id, provisioned={"A": True, "B": True}
                    )
                    for role in "AB":
                        require_numbered_idle(r, role, await self.command(r, role, "status.get"))
                else:
                    await self.open_radio_session(r, request, plan, key_mismatch)
                    if numbered:
                        numbered.applied_settings = r["applied_settings"]
                        numbered.key_set_id = r["security"]["key_set_id"]
                if isinstance(request, PrepareLimitCheck):
                    r["stage"] = "resource_refusal"
                    await self.verify_prepare_refusal(r, request, plan.spec, budget)
                    return
                if numbered and numbered.lab:
                    for role in "AB":
                        cleared = await self.command(
                            r, role, "fault.set", {"injections": [], "replace": True}
                        )
                        if cleared["count"]:
                            raise ValueError("Node did not clear the previous message fault")
                if lab:
                    targets = lab.get("exhaustion_targets", [lab["injection"]])
                    configured = await self.command(
                        r, lab["role"], "fault.set", {"injections": targets, "replace": True}
                    )
                    if configured["count"] != len(targets):
                        raise ValueError("Node did not confirm the selected fault targets")
                r["stage"] = "preparing"
                self.save(r)
                for role in (r["receiver"], r["sender"]):
                    preparation = run_protocol_v2.Prepare(
                        spec=plan.spec, budget=budget, message_id=r.get("message_id")
                    )
                    accepted = await self.command(r, role, "run.prepare", preparation.model_dump())
                    r["prepared"][role] = await self.prepared(r, role, accepted)
                if isinstance(request, ReceiveEvidenceGapCheck):
                    receiver = r["receiver"]
                    r["receive_evidence_gap"] = {"role": receiver, "omitted_event": None}

                    def on_omit(event):
                        r["receive_evidence_gap"]["omitted_event"] = event
                        self.trace_command(
                            r,
                            receiver,
                            {
                                "direction": "host_fixture",
                                "perturbation": "omit_one_rx_frame",
                                "record": event,
                            },
                            False,
                        )

                    self.same_boot(r, receiver).set_receive_observation_omission(r["id"], on_omit)
                if isinstance(request, PreparedCancellationCheck):
                    r["stage"] = "prepared_cancellation"
                    await self.cancel_prepared_workload(r, request)
                    return
                r["stage"] = "arming"
                self.save(r)
                missing_reply = isinstance(request, EchoMissingReplyCheck)
                if missing_reply:
                    receiver = r["receiver"]
                    stop = await self.command(r, receiver, "run.stop", {"reason": "operator"})
                    idle = await self.command(r, receiver, "status.get")
                    if idle["state"] != "idle" or idle["run_id"] is not None:
                        raise ValueError("The controlled echo responder did not stop")
                    r["echo_timeout_control"] = {"responder_stop": stop, "responder_idle": idle}

                armed = monotonic()  # Include responder arm when the case requests a reply.
                if not missing_reply:
                    ready = await self.command(
                        r,
                        r["receiver"],
                        "run.arm",
                        {
                            "config_revision": r["applied_settings"][r["receiver"]][
                                "config_revision"
                            ]
                        },
                    )
                    if ready["receiver_ready"] is not True or ready["role"] != "receiver":
                        raise ValueError("Receiver did not confirm readiness")
                    if (monotonic() - armed) * 1_000_000 >= run_protocol_v2.ARM_WINDOW_US:
                        raise ValueError("Receiver arm window expired before sender arm")
                sender_ready = await self.command(
                    r,
                    r["sender"],
                    "run.arm",
                    {"config_revision": r["applied_settings"][r["sender"]]["config_revision"]},
                )
                if sender_ready["receiver_ready"] or sender_ready["role"] != "sender":
                    raise ValueError("Sender did not confirm its prepared arm")
                if (monotonic() - armed) * 1_000_000 >= run_protocol_v2.ARM_WINDOW_US:
                    raise ValueError("Receiver arm window expired before sender start")
                r["stage"] = "transmitting"
                started = await self.command(
                    r,
                    r["sender"],
                    "run.start",
                    {"config_revision": r["applied_settings"][r["sender"]]["config_revision"]},
                )
                if missing_reply:
                    r["echo_timeout_control"]["requester_start"] = started
                    r["echo_timeout_control"]["drain_us"] = budget["drain_us"]
                r["arm_to_start_reply_ms"] = (monotonic() - armed) * 1000
                if r["arm_to_start_reply_ms"] >= run_protocol_v2.ARM_WINDOW_US / 1000:
                    raise ValueError("Sender start reply exceeded the receiver arm window")
                self.save(r)
                async with asyncio.timeout(
                    request.timeout_ms / 1000 + run_protocol_v2.ARM_WINDOW_US / 1_000_000 + 3
                ):
                    while True:
                        for role in "AB":
                            self.same_boot(r, role)
                        for event in r["events"]:
                            if event["name"] == "run.summary":
                                r["summaries"][event["role"]] = event["data"]
                        if len(r["summaries"]) == 2:
                            break
                        if lab and lab["injection"]["action"] == "replay" and lab["fire"] is None:
                            await self.maybe_fire_lab_replay(r)
                        await asyncio.sleep(0.01)
                r["rf_window_closed_at"] = utc_now()
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
                    allowed_stops = (
                        ("completed", "timeout")
                        if lab
                        or key_mismatch
                        or isinstance(request, EchoRadioRunRequest)
                        or (isinstance(request, SweepRadioRunRequest) and role == r["receiver"])
                        else ("completed",)
                    )
                    if missing_reply:
                        allowed_stops = ("timeout",) if role == r["sender"] else ("operator",)
                    if summary.get("message_id") != r.get("message_id"):
                        raise ValueError(f"Node {role} summary belongs to another message")
                    if r["summaries"][role]["stop_reason"] not in allowed_stops:
                        raise ValueError(
                            f"Node {role} stopped with {r['summaries'][role]['stop_reason']}"
                        )
                    await self.command(r, role, "status.get")
                if lab:
                    lab["report"] = await self.command(
                        r, lab["role"], "fault.status", {"offset": 0, "limit": 4}
                    )
                if fixed_source:
                    await self.collect_fixed_rate_evidence(r, request)
                    r["status"] = "completed"
                    return
                delivered = r["summaries"][r["receiver"]]["delivered_messages"]
                sweep_loss = isinstance(request, SweepRadioRunRequest) and not delivered
                negative_delivery = (lab or key_mismatch or sweep_loss) and not delivered
                if negative_delivery:
                    expected = known_data(
                        request.source_seed, r.get("message_id", 1), request.message_bytes
                    )
                    source = await self.retrieve(r, r["sender"], "source")
                    if source != expected:
                        raise ValueError("Source readback differs from the independent recipe")
                    self.register_retirement(r, r["sender"])
                elif isinstance(request, EchoRadioRunRequest):
                    expected = await self.verify_echo(r, request)
                else:
                    source = await self.retrieve(r, r["sender"], "source")
                    recovered = await self.retrieve(r, r["receiver"], "recovered")
                    encoded = isinstance(request, EncodedRadioRunRequest)
                    expected = (
                        source
                        if encoded
                        else known_data(
                            request.source_seed, r.get("message_id", 1), request.message_bytes
                        )
                    )
                    if encoded and (
                        len(source) != request.message_bytes
                        or hashlib.sha256(source).hexdigest() != request.expected_sha256
                    ):
                        raise ValueError(
                            "Encoded source readback differs from the declared committed clip"
                        )
                    if source != expected or recovered != source:
                        raise ValueError(
                            "Actual source/recovered bytes differ from the "
                            "independent source recipe"
                        )
                    r["verification"] = {
                        "bytes_equal": True,
                        "length_bytes": len(recovered),
                        "sha256": hashlib.sha256(recovered).hexdigest(),
                        "sample_hex": recovered[:32].hex(),
                        "method": "declared committed source hash plus exact "
                        "source/recovered readback"
                        if encoded
                        else "independent source recipe plus exact source/recovered readback",
                    }
                if plan.spec.source == "known_data" and not negative_delivery:
                    self.register_retirement(r, "AB")
                if sweep_loss:
                    r["accounting"] = await asyncio.to_thread(reconcile_sweep_loss, r, expected)
                elif not negative_delivery:
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
                r["status"] = "completed"
        except asyncio.CancelledError:
            r["failure_stage"] = r["stage"]
            r["status"] = "interrupted" if self.shutting_down else "cancelled"
            r["error"] = "Host shutdown" if self.shutting_down else "Operator stopped the radio run"
        except Exception as exc:
            r["failure_stage"] = r["stage"]
            interrupted = any(
                not node.connected
                or node.connection_id != r["physical_bindings"][role]["connection_id"]
                or node.identity is None
                or (node.identity.device_id, node.identity.boot_id)
                != (r["identities"][role]["device_id"], r["identities"][role]["boot_id"])
                for role, node in self.nodes.items()
            )
            r["status"] = "interrupted" if interrupted else "failed"
            r["error"] = str(exc) or type(exc).__name__
            if interrupted:
                r["connection_failures"] = {
                    role: node.connection_failure
                    for role, node in self.nodes.items()
                    if node.connection_failure
                    and node.connection_failure["connection_id"]
                    == r["physical_bindings"][role]["connection_id"]
                }
        finally:
            if fixture := r.get("receive_evidence_gap"):
                self.nodes[fixture["role"]].clear_receive_observation_omission(r["id"])
                fixture["deltas"] = {
                    role: {
                        "event_gaps": node.event_gaps - r["baseline"][role]["event_gaps"],
                        "framing_errors": node.framing_errors
                        - r["baseline"][role]["framing_errors"],
                        "telemetry_drops": (
                            node.health.telemetry_drops - r["baseline"][role]["telemetry_drops"]
                            if node.health
                            else None
                        ),
                    }
                    for role, node in self.nodes.items()
                }
            self.cleaning_up = True
            r["stage"] = "stopping"
            # Persistence must not prevent the physical sessions from being closed.
            try:
                for transfer in r["transfers"].values():
                    if self.artifacts.busy:
                        await self.artifacts.cancel(transfer)
                r["cleanup"] = await (self.cleanup(r, numbered) if numbered else self.cleanup(r))
                if r.get("connection_failures"):
                    r["cleanup_completed_monotonic_ns"] = monotonic_ns()
                if r["status"] == "completed" and r["evidence_error"]:
                    r["status"] = "failed"
                    r["error"] = "Cleanup evidence incomplete; verified artifacts retained"
                if not r["cleanup"]["confirmed"] and r["status"] == "completed":
                    r["status"] = "failed"
                    r["error"] = (
                        "Radio cleanup could not retire every verified run artifact"
                        if any(
                            not item["confirmed"]
                            for item in r["cleanup"]
                            .get(
                                "retired_echo_artifacts",
                                r["cleanup"].get("retired_data_artifacts", {}),
                            )
                            .values()
                        )
                        else "Radio cleanup did not confirm both nodes idle"
                    )
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
                if not isinstance(request, EchoRadioRunRequest):
                    r["security"]["assessment"] = assess_security(r)
                r["missing_evidence"] = failed_ranges(r)
                r["finished_at"] = utc_now()
                r["stage"] = "finished"
                r["saved_files"] = {}
                for kind in ("source", "recovered", "wire"):
                    path = (
                        self.directory
                        / f"{r['id']}.{'ndjson' if kind == 'wire' else kind + '.bin'}"
                    )
                    try:
                        if path.is_file():
                            with path.open("rb") as stream:
                                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                            r["saved_files"][kind] = {
                                "length_bytes": path.stat().st_size,
                                "sha256": checksum,
                            }
                    except OSError as exc:
                        r.setdefault("saved_file_errors", {})[kind] = str(exc)
                        r["evidence_error"] = (
                            r.get("evidence_error") or "Saved file fingerprint unavailable"
                        )
                        r["error"] = r.get("error") or r["evidence_error"]
                        if r["status"] == "completed":
                            r["status"] = "failed"
                r["wire_sha256"] = r["saved_files"].get("wire", {}).get("sha256")
                transaction = r["host_transaction"]
                transaction["end_ns"] = monotonic_ns()
                transaction["elapsed_ns"] = transaction["end_ns"] - transaction["start_ns"]
                if isinstance(request, EchoRadioRunRequest):
                    r["timing"] = echo_accounting.assess(r)
                    if (
                        r["status"] == "completed"
                        and not r["timing"]["n"]
                        and not all(
                            exclusion["reason"] == "timeout"
                            for exclusion in r["timing"]["exclusions"]
                        )
                    ):
                        r["status"] = "failed"
                        r["error"] = (
                            "Echo correlation excluded the measurement: "
                            + r["timing"]["exclusions"][0]["reason"]
                        )
                    r["accounting"] = {
                        "evidence_complete": bool(r["timing"]["n"]),
                        "scope": "echo",
                        "reasons": r["timing"]["exclusions"],
                    }
                    r["security"]["assessment"] = {
                        "profile": request.security,
                        "classification": "verified_echo"
                        if r["timing"]["n"]
                        else "no_successful_echo",
                        "scope": "echo bytes and node-reported protection; "
                        "full security qualification separate",
                    }
                self.save(r)
                if numbered and r["status"] == "completed" and r["cleanup"].get("session_retained"):
                    numbered.next_message += 1
            finally:
                self.current = None

    async def collect_echo_distribution(self, identifiers):
        return await self.evidence_worker.run(self.echo_distribution, identifiers)

    def echo_distribution(self, identifiers):
        if not 1 <= len(identifiers) <= 1000 or len(identifiers) != len(set(identifiers)):
            raise ValueError("Select 1–1000 distinct echo run IDs")

        def records():
            verified_bytes = 0
            for identifier in identifiers:
                record = self.get(identifier)
                if record["plan"]["spec"]["source"] != "echo":
                    raise ValueError("Selected record is not an echo run")
                if record["status"] == "completed":
                    kinds = ["source", "wire"] + (
                        ["recovered"]
                        if (record.get("verification") or {}).get("bytes_equal")
                        else []
                    )
                    try:
                        for kind in kinds:
                            if not record.get("saved_files", {}).get(kind):
                                raise ValueError("Finalized echo file fingerprint is unavailable")
                            verified_bytes += record["saved_files"][kind]["length_bytes"]
                            if verified_bytes > 64 * 1024 * 1024:
                                raise ValueError(
                                    "Selected echo evidence exceeds 64 MiB; choose fewer runs"
                                )
                            self.content(identifier, kind)
                    except (ValueError, OSError) as exc:
                        if verified_bytes > 64 * 1024 * 1024:
                            raise
                        record["saved_integrity_error"] = str(exc)
                yield record

        return echo_accounting.distributions(records())

    async def verify_echo(self, r, request):
        expected = known_data(request.source_seed, 1, request.message_bytes)
        source = await self.retrieve(r, r["sender"], "source")
        result = r["summaries"][r["sender"]].get("echo")
        if source != expected or result is None:
            raise ValueError("Echo source bytes or requester result are unavailable")
        r["verification"] = {
            "bytes_equal": None,
            "length_bytes": len(source),
            "sha256": hashlib.sha256(source).hexdigest(),
            "method": "independent source recipe and actual returned echo bytes",
        }
        recovered = None
        if r["summaries"][r["receiver"]]["delivered_messages"]:
            recovered = await self.retrieve(r, r["receiver"], "recovered")
            if recovered != expected:
                raise ValueError(
                    "Echo recovered request differs from the independent source recipe"
                )
        if result["valid"]:
            if recovered != expected or bytes.fromhex(result.get("reply_hex") or "") != expected:
                raise ValueError("Echo returned bytes differ from the independent source recipe")
            r["verification"]["bytes_equal"] = True
        verified = [r["sender"]] + ([r["receiver"]] if recovered is not None else [])
        self.register_retirement(r, verified)
        return expected

    def register_retirement(self, r, roles):
        retirement = {}
        for role in roles:
            identifier = r["prepared"][role]["artifact_id"]
            if identifier in r["initial_artifact_ids"][role]:
                raise ValueError("Run prepared an existing artifact ID; preserving it")
            retirement[role] = identifier
        key = (
            "retire_echo_artifacts"
            if r["plan"]["spec"]["source"] == "echo"
            else "retire_data_artifacts"
        )
        r[key] = retirement

    async def required_evidence(self, r, expected):
        if r["plan"]["spec"]["source"] == "echo":
            # Final correlation follows cleanup; here preserve a required result event.
            if not any(
                e["role"] == r["sender"] and e["name"] == "echo.result" for e in r["events"]
            ):
                raise ValueError("Requester echo result event is unavailable")
            return
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
                    reason = (
                        "Required radio observations are missing; "
                        "RF delivery and telemetry loss differ"
                    )
                    r["accounting"] = {
                        "evidence_complete": False,
                        "reason_code": "telemetry_gap",
                        "reason": reason,
                    }
                    raise ValueError(reason)
        try:
            r["accounting"] = reconcile(r, expected)
        except ValueError as exc:
            r["accounting"] = {"evidence_complete": False, "reason": str(exc)}
            raise

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
        self.evidence_worker.closing = True
        if self.busy:
            await self.stop()
        await self.evidence_worker.close()

    def export(self, identifier):
        record = self.get(identifier)
        require_public_metadata(record)
        members = {"run.json": json.dumps(record, indent=2).encode()}
        if link := record.get("source_observation"):
            assessment = self.observations.get(link["id"])
            if assessment["evidence_sha256"] != link["sha256"]:
                raise ValueError("Fixed-source assessment evidence differs from the saved link")
            members["fixed-source-assessment.json"] = json.dumps(assessment).encode()
        for kind in ("source", "recovered", "wire"):
            if kind in record["available_content"] or kind in record.get("saved_files", {}):
                path = self.content(identifier, kind)
                members[path.name] = path.read_bytes()
        for role, transfer_id in record["transfers"].items():
            members[f"transfers/{role}.json"] = json.dumps(
                self.artifacts.get(transfer_id), indent=2
            ).encode()
            trace = self.artifacts.directory / f"{transfer_id}.ndjson"
            if trace.is_file():
                members[f"transfers/{role}.ndjson"] = trace.read_bytes()
        for name, data in members.items():
            if name.endswith((".json", ".ndjson")):
                for line in (
                    data.decode().splitlines() if name.endswith(".ndjson") else [data.decode()]
                ):
                    try:
                        require_public_metadata(json.loads(line))
                    except (ValueError, UnicodeError):
                        raise ValueError(
                            "Unsafe or malformed metadata cannot be exported"
                        ) from None
        if sum(len(data) for data in members.values()) > 128 * 1024 * 1024:
            raise ValueError(
                "Radio export exceeds 128 MiB; retrieve linked file-transfer evidence separately"
            )
        members["sha256.json"] = json.dumps(
            {name: hashlib.sha256(data).hexdigest() for name, data in members.items()}, indent=2
        ).encode()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in members.items():
                archive.writestr(name, data)
        return output.getvalue()
