"""Persist physical campaign intent; execution is a separate bench-owned service."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4, uuid5

from pydantic import Field, model_validator

from . import __version__
from .artifact_contract_v2 import ArtifactID
from .catalog import ROWS, required_nodes
from .crypto_benchmark_v2 import Request as CryptoRequest
from .experiments_v2 import ContractModel
from .radio_runs import RadioRunRequest
from .session_keys import require_public_metadata
from .storage import utc_now
from .voice_runs import VoiceRunRequest

POLICY = "physical_campaign_plan_v1"
MAX_CASES, BATCH_CASES, BATCH_SECONDS = 4096, 64, 1800


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class MemoryCase(ContractModel):
    kind: Literal["memory_probe"]
    role: Literal["A", "B"] = "A"
    iterations: int = Field(default=10, ge=1, le=10000)
    payload_bytes: int = Field(default=4096, ge=1, le=65536)


class RadioCase(ContractModel):
    kind: Literal["known_data"]
    request: RadioRunRequest = Field(default_factory=RadioRunRequest)


class VoiceCase(ContractModel):
    kind: Literal["voice"]
    request: VoiceRunRequest


class CryptoCase(ContractModel):
    kind: Literal["crypto_benchmark"]
    role: Literal["A", "B"] = "A"
    request: CryptoRequest = Field(default_factory=CryptoRequest)


class SerialCase(ContractModel):
    kind: Literal["serial_check"]
    role: Literal["A", "B"] = "A"
    cycles: int = Field(default=3, ge=1, le=10)


class AudioCase(ContractModel):
    kind: Literal["audio"]
    role: Literal["A", "B"] = "A"
    action: Literal["capture", "play", "retrieve", "codec", "decode"]
    artifact_id: ArtifactID | None = None
    sample_count: int | None = Field(default=None, ge=1, le=24000)
    wait_for_ptt: bool = False

    @model_validator(mode="after")
    def source_selection(self):
        if self.action == "capture":
            if self.artifact_id is not None:
                raise ValueError("Capture creates a fresh artifact at execution")
            if self.sample_count is None:
                self.sample_count = 24000
        elif self.artifact_id is None or self.sample_count is not None or self.wait_for_ptt:
            raise ValueError(
                "Use an existing artifact for playback/retrieval/codec; "
                "its manifest defines samples"
            )
        return self


class ProcedureCase(ContractModel):
    kind: Literal["procedure"]
    catalog_id: str
    workload: Literal["default", "local", "rf"] = "default"
    roles: list[Literal["A", "B"]] | None = Field(default=None, min_length=1, max_length=2)
    budget_s: int = Field(default=300, ge=1, le=1800)

    @model_validator(mode="after")
    def requirements(self):
        if self.catalog_id not in {row[0] for row in ROWS}:
            raise ValueError("Unknown CDR procedure")
        count = required_nodes(self.catalog_id, self.workload)
        if self.roles is None:
            self.roles = ["A"] if count == 1 else ["A", "B"]
        if len(self.roles) != count or len(set(self.roles)) != count:
            raise ValueError("Procedure roles must match its local/RF node requirement")
        return self


Case = Annotated[
    MemoryCase | RadioCase | VoiceCase | CryptoCase | SerialCase | AudioCase | ProcedureCase,
    Field(discriminator="kind"),
]


class Template(ContractModel):
    label: str = Field(min_length=1, max_length=100)
    case: Case


class CampaignSpec(ContractModel):
    name: str = Field(min_length=1, max_length=100)
    templates: list[Template] = Field(min_length=1, max_length=64)
    repetitions: int = Field(default=1, ge=1, le=100)
    directions: list[Literal["A_TO_B", "B_TO_A"]] = Field(
        default_factory=lambda: ["A_TO_B", "B_TO_A"], min_length=1, max_length=2
    )
    order: Literal["sequential", "randomized"] = "sequential"
    order_seed: int = Field(default=743, ge=0, le=2**32 - 1)
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def unique_selection(self):
        if len(set(self.directions)) != len(self.directions):
            raise ValueError("Choose distinct directions")
        labels = [template.label for template in self.templates]
        if len(set(labels)) != len(labels):
            raise ValueError("Give templates distinct labels")
        return self


def expand(spec, identifier):
    cases = []
    namespace = UUID(identifier)
    for repetition in range(1, spec.repetitions + 1):
        for template_index, template in enumerate(spec.templates):
            document = template.case.model_dump()
            directions = spec.directions if document["kind"] in ("known_data", "voice") else [None]
            for direction in directions:
                case = deepcopy(document)
                if direction:
                    request = case["request"]
                    request["direction"] = direction
                    if case["kind"] == "known_data":
                        request["source_seed"] = (request["source_seed"] + repetition - 1) % 2**32
                        bound = (request["timeout_ms"] + 999) // 1000 + 65
                        catalog_id = "IF-02"
                    else:
                        factor = 3 if request["include_comparisons"] else 1
                        bound = (request["timeout_ms"] * factor + 999) // 1000 + 360
                        catalog_id = "VOICE-02"
                    roles = ["A", "B"]
                elif case["kind"] == "procedure":
                    bound, roles, catalog_id = case["budget_s"], case["roles"], case["catalog_id"]
                else:
                    bound = 260 if case["kind"] == "audio" else 50
                    roles = [case["role"]]
                    catalog_id = {
                        "memory_probe": "MEM-01",
                        "audio": "VOICE-01",
                        "crypto_benchmark": "SEC-04",
                        "serial_check": "IF-01",
                    }[case["kind"]]
                if len(cases) >= MAX_CASES:
                    raise ValueError(
                        f"A plan is limited to {MAX_CASES} cases; "
                        "split the selected intent explicitly"
                    )
                if bound > BATCH_SECONDS:
                    raise ValueError(
                        "One atomic case exceeds the 30-minute batch budget; reduce its timeout"
                    )
                canonical_index = len(cases)
                cases.append(
                    {
                        "id": str(uuid5(namespace, f"case:{canonical_index}")),
                        "canonical_index": canonical_index,
                        "template_index": template_index,
                        "label": template.label,
                        "repetition": repetition,
                        "direction": direction,
                        "case": case,
                        "catalog_id": catalog_id,
                        "required_nodes": len(roles),
                        "roles": roles,
                        "duration_bound_s": bound,
                        "duration_basis": "operator_budget_not_measured"
                        if case["kind"] == "procedure"
                        else "host_timeout_plus_cleanup_reserve_v1",
                        "run_id": None,
                    }
                )
    if spec.order == "randomized":
        seed = spec.order_seed.to_bytes(4, "big")
        cases.sort(
            key=lambda case: hashlib.sha256(
                seed + case["canonical_index"].to_bytes(4, "big")
            ).digest()
        )
    return [{"index": index, **case} for index, case in enumerate(cases)]


def batches(cases, identifier):
    groups, active, seconds = [], [], 0
    for case in cases:
        if active and (
            len(active) == BATCH_CASES or seconds + case["duration_bound_s"] > BATCH_SECONDS
        ):
            groups.append((active, seconds))
            active, seconds = [], 0
        active.append(case)
        seconds += case["duration_bound_s"]
    if active:
        groups.append((active, seconds))
    ids = [str(uuid5(UUID(identifier), f"batch:{index}")) for index in range(len(groups))]
    result = []
    for index, (group, seconds) in enumerate(groups):
        for case in group:
            case["batch_id"] = ids[index]
        result.append(
            {
                "id": ids[index],
                "parent_plan_id": identifier,
                "index": index,
                "previous_batch_id": ids[index - 1] if index else None,
                "next_batch_id": ids[index + 1] if index + 1 < len(ids) else None,
                "case_ids": [case["id"] for case in group],
                "case_count": len(group),
                "duration_bound_s": seconds,
            }
        )
    return result


class CampaignPlans:
    def __init__(self, store, preflight):
        self.store, self.preflight = store, preflight
        store.db.execute(
            "CREATE TABLE IF NOT EXISTS physical_campaign_plans_v1 "
            "(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL)"
        )
        store.db.commit()

    def preview(self, spec):
        identifier = str(uuid4())
        cases = expand(spec, identifier)
        grouped = batches(cases, identifier)
        readiness = {}
        for case in cases:
            key = deepcopy(case["case"])
            if key["kind"] == "known_data":
                key["request"].pop("source_seed")
            key = digest(key)
            if key not in readiness:
                try:
                    observed = self.preflight(case)
                except (OSError, ValueError) as exc:
                    observed = {"ready": False, "blockers": [str(exc)]}
                readiness[key] = {
                    **observed,
                    "checked_at": utc_now(),
                    "authority": "cached_capability_snapshot_only",
                }
            case["hardware_preflight"] = deepcopy(readiness[key])
        record = {
            "id": identifier,
            "created_at": utc_now(),
            "name": spec.name,
            "policy": POLICY,
            "mode": "hardware",
            "status": "planned",
            "execution_available": False,
            "execution_blocker": "Campaign execution follows issue #87",
            "hardware_qualified": False,
            "spec": spec.model_dump(),
            "spec_sha256": digest(spec.model_dump()),
            "order_algorithm": "sha256_seed_and_canonical_index_v1",
            "cases": cases,
            "case_count": len(cases),
            "batches": grouped,
            "batch_count": len(grouped),
            "duration_bound_s": sum(case["duration_bound_s"] for case in cases),
            "duration_basis": "Declared host timeouts plus cleanup reserve; not measured duration",
            "host_version": __version__,
            "planner_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "spec_schema_sha256": digest(CampaignSpec.model_json_schema()),
            "host_sources": {
                name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in (
                    "host.py",
                    "radio_runs.py",
                    "voice_runs.py",
                    "node_audio.py",
                    "diagnostic_jobs.py",
                    "physical_adapter.py",
                    "serial_validation.py",
                )
            },
        }
        record["plan_sha256"] = digest(record)
        if len(json.dumps(record).encode()) > 16 * 1024 * 1024:
            raise ValueError("Physical plan document exceeds 16 MiB")
        require_public_metadata(record)
        return record

    def create(self, spec):
        record = self.preview(spec)
        self.store.db.execute(
            "INSERT INTO physical_campaign_plans_v1 VALUES (?,?,?)",
            (record["id"], record["created_at"], json.dumps(record)),
        )
        self.store.db.commit()
        return record

    def list(self, limit=20):
        rows = self.store.db.execute(
            "SELECT id, created_at, json_extract(document,'$.name') AS name, "
            "json_extract(document,'$.case_count') AS case_count, "
            "json_extract(document,'$.batch_count') AS batch_count, "
            "json_extract(document,'$.duration_bound_s') AS duration_bound_s, "
            "json_extract(document,'$.plan_sha256') AS plan_sha256 "
            "FROM physical_campaign_plans_v1 ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return {
            "plans": [
                {**dict(row), "mode": "hardware", "status": "planned", "execution_available": False}
                for row in rows
            ]
        }

    def get(self, identifier):
        row = self.store.db.execute(
            "SELECT document FROM physical_campaign_plans_v1 WHERE id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown physical campaign plan")
        record = json.loads(row[0])
        expected = record.pop("plan_sha256")
        if digest(record) != expected:
            raise ValueError("Saved campaign plan hash differs")
        return {**record, "plan_sha256": expected}
