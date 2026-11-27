"""Stable integration case plans shared by host execution and evidence views."""

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from . import (
    content_series,
    fault_matrices,
    local_voice,
    memory_matrix,
    model_series,
    ops_matrix,
    rf_sweeps,
    sustained_voice,
    timed_series,
    voice_matrix,
)
from .campaign_plans import CampaignSpec, RadioCase, Template
from .control_v2 import UUID
from .experiments_v2 import ContractModel
from .radio_runs import RadioRunRequest

REVISION = "physical_integration_matrix_v1"
SERIAL_GROUPS = {
    "C1": ("valid_control_cycles",),
    "C2": ("invalid_argument", "unknown_command", "known_unavailable", "configuration_unchanged"),
    "C3": (
        "oversized_record",
        "split_every_boundary",
        "representative_board_splits",
        "concatenated_records",
        "crlf_record",
        "maximum_size_record",
        "duplicate_key",
        "invalid_utf8",
        "malformed_json",
    ),
    "C4": ("wire_version", "contract_version", "schema_digest"),
    "C5": (
        "lost_reply",
        "delayed_reply",
        "retry_same_identity",
        "conflicting_identity",
        "stale_boot",
    ),
    "C6": ("competing_claim", "lease_recovery", "health_silence"),
}
LINK_GROUPS = {
    "C1": (("baseline", 64),),
    "C2": tuple((f"bytes_{size}", size) for size in (1, 159, 160)),
    "C3": (("peer_configuration_mismatch", 64),),
}
CAMPAIGN_GROUPS = {
    "C1": ("baseline",),
    "C2": ("pause_resume",),
    "C3": ("cancel_queued",),
    "C4": ("failed_configuration",),
    "C5": ("refresh_navigation",),
    "C6": ("restart_active", "restart_paused"),
    "C7": ("selected_rerun",),
    "C8": ("hashes_and_concurrent_start",),
}
GROUPS = {
    "IF-01": SERIAL_GROUPS,
    "IF-02": LINK_GROUPS,
    "IF-03": CAMPAIGN_GROUPS,
    **rf_sweeps.GROUPS,
    **content_series.GROUPS,
    **timed_series.GROUPS,
    **memory_matrix.GROUPS,
    **model_series.GROUPS,
    **fault_matrices.GROUPS,
    **voice_matrix.GROUPS,
    **sustained_voice.GROUPS,
    **ops_matrix.GROUPS,
    **local_voice.GROUPS,
}


def matrix_options():
    kinds = {
        "IF-01": "serial",
        "IF-03": "campaign",
        "SEC-04": "local",
        "MEM-01": "memory",
        "VOICE-02": "voice",
        "VOICE-03": "voice",
        "VOICE-01": "voice_local",
        "OPS-01": "campaign",
    }
    return {
        identifier: {
            "groups": list(groups),
            "kind": kinds.get(identifier, "link"),
            "choose_security": identifier in rf_sweeps.GROUPS or identifier == "PKT-01",
        }
        for identifier, groups in GROUPS.items()
    }


class CampaignRestartEvidenceReference(ContractModel):
    variant: Literal["restart_active", "restart_paused"]
    repetition: int = Field(ge=1, le=3)
    interrupted: UUID
    recovery: UUID


class RestartEvidenceReference(CampaignRestartEvidenceReference):
    direction: Literal["A_TO_B", "B_TO_A"]


class USBEvidenceReference(ContractModel):
    target_role: Literal["A", "B"]
    direction: Literal["A_TO_B", "B_TO_A"]
    repetition: int = Field(ge=1, le=3)
    interrupted: UUID
    recovery: UUID


class ResetEvidenceReference(USBEvidenceReference):
    stale_boot_procedure: UUID


class LocalVoiceEvidenceReference(ContractModel):
    group: Literal["C1", "C2"]
    role: Literal["A", "B"]
    utterance: int = Field(ge=1, le=3)
    repetition: int = Field(ge=1, le=3)
    capture: UUID
    playback: UUID
    codec: UUID | None = None


class MatrixRequest(ContractModel):
    catalog_id: Literal[
        "IF-01",
        "IF-02",
        "IF-03",
        "RF-01",
        "RF-02",
        "RF-03",
        "RF-04",
        "PKT-01",
        "SEC-01",
        "SEC-02",
        "SEC-03",
        "PKT-02",
        "PKT-03",
        "TIME-01",
        "SEC-04",
        "MEM-01",
        "MODEL-01",
        "VOICE-02",
        "VOICE-03",
        "VOICE-01",
        "OPS-01",
    ]
    groups: list[str] | None = Field(default=None, min_length=1, max_length=8)
    roles: list[Literal["A", "B"]] = Field(
        default_factory=lambda: ["A", "B"], min_length=1, max_length=2
    )
    transports: list[Literal["native_usb", "uart"]] = Field(
        default_factory=lambda: ["native_usb"], min_length=1, max_length=2
    )
    directions: list[Literal["A_TO_B", "B_TO_A"]] = Field(
        default_factory=lambda: ["A_TO_B", "B_TO_A"], min_length=1, max_length=2
    )
    repetitions: int = Field(default=3, ge=1, le=3)
    valid_cycles: int = Field(default=10, ge=1, le=10)
    diagnostic_iterations: int = Field(default=1000, ge=1, le=1000)
    memory_window_ms: int = Field(default=30000, ge=1000, le=30000)
    ops_observation_s: int = Field(default=ops_matrix.STABILITY_SECONDS, ge=5, le=3600)
    ops_restart_evidence: list[RestartEvidenceReference] | None = Field(
        default=None, min_length=1, max_length=12
    )
    ops_usb_evidence: list[USBEvidenceReference] | None = Field(
        default=None, min_length=1, max_length=12
    )
    ops_reset_evidence: list[ResetEvidenceReference] | None = Field(
        default=None, min_length=1, max_length=12
    )
    campaign_restart_evidence: list[CampaignRestartEvidenceReference] | None = Field(
        default=None, min_length=1, max_length=6
    )
    messages_per_case: int = Field(default=100, ge=1, le=100)
    seed: int = Field(default=743, ge=0, le=2**32 - 1)
    rf_security: Literal["none", "aes128_gcm"] = "none"
    rf_echoes_per_case: int | None = Field(default=None, ge=0, le=100)
    subset_sizes: list[int] | None = Field(default=None, min_length=1, max_length=11)
    voice_reference_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=3)
    local_voice_evidence: list[LocalVoiceEvidenceReference] | None = Field(
        default=None, min_length=1, max_length=36
    )

    @model_validator(mode="after")
    def selections(self):
        for choices in (
            self.groups,
            self.roles,
            self.transports,
            self.directions,
            self.subset_sizes,
            self.voice_reference_ids,
        ):
            if choices is not None and len(choices) != len(set(choices)):
                raise ValueError("Choose each group, role, direction or transport once")
        if self.subset_sizes is not None and (
            self.catalog_id not in (*content_series.GROUPS, "MEM-01", "MODEL-01")
            or any(size < 1 or size > 65537 for size in self.subset_sizes)
        ):
            raise ValueError("Size selection belongs to a compatible procedure series")
        if self.groups is not None and not set(self.groups) <= set(GROUPS[self.catalog_id]):
            raise ValueError("Choose groups that belong to the selected procedure")
        if self.catalog_id != "SEC-04" and self.diagnostic_iterations != 1000:
            raise ValueError("Diagnostic iterations belong to the local crypto procedure")
        if self.voice_reference_ids is not None and self.catalog_id not in (
            "VOICE-01",
            "VOICE-02",
            "VOICE-03",
        ):
            raise ValueError("Voice references belong to a voice procedure")
        if self.catalog_id == "VOICE-03" and len(self.voice_reference_ids or ()) > 1:
            raise ValueError("Use the same single reference for all fixed-rate profiles")
        if self.local_voice_evidence:
            if self.catalog_id != "VOICE-01":
                raise ValueError("Local microphone evidence belongs to VOICE-01")
            keys, captures, outputs = set(), set(), set()
            for row in self.local_voice_evidence:
                if (
                    row.role not in self.roles
                    or row.repetition > self.repetitions
                    or self.groups is not None
                    and row.group not in self.groups
                    or (row.codec is not None) != (row.group == "C2")
                ):
                    raise ValueError(
                        "Match each microphone recording to the selected case and stages"
                    )
                keys.add((row.group, row.role, row.utterance, row.repetition))
                captures.add((row.group, row.capture))
                outputs.add(row.playback)
                if row.codec:
                    outputs.add(row.codec)
            expected = len(self.local_voice_evidence)
            if (
                len(keys) != expected
                or len(captures) != expected
                or len(outputs)
                != expected + sum(row.codec is not None for row in self.local_voice_evidence)
                or outputs.intersection(row.capture for row in self.local_voice_evidence)
            ):
                raise ValueError("Use distinct local audio cases and stage records")
        if self.rf_echoes_per_case is not None and self.catalog_id not in rf_sweeps.GROUPS:
            raise ValueError("Matched echo count belongs to RF sweep procedures")
        if self.catalog_id != "OPS-01" and self.ops_observation_s != ops_matrix.STABILITY_SECONDS:
            raise ValueError("The stability observation window belongs to OPS-01")
        for catalog, group, entries, field in (
            ("OPS-01", "C1", self.ops_usb_evidence, "target_role"),
            ("OPS-01", "C2", self.ops_reset_evidence, "target_role"),
            ("OPS-01", "C3", self.ops_restart_evidence, "variant"),
            ("IF-03", "C6", self.campaign_restart_evidence, "variant"),
        ):
            if not entries:
                continue
            if self.catalog_id != catalog or self.groups is not None and group not in self.groups:
                raise ValueError(f"The submitted evidence belongs to {catalog} {group}")
            keys = {
                (getattr(row, field), getattr(row, "direction", None), row.repetition)
                for row in entries
            }
            records = {value for row in entries for value in (row.interrupted, row.recovery)}
            if len(keys) != len(entries) or len(records) != 2 * len(entries):
                raise ValueError("Use distinct cases and evidence records")
            if any(
                repetition > self.repetitions
                or direction is not None
                and direction not in self.directions
                for _, direction, repetition in keys
            ):
                raise ValueError("Each attached observation must belong to a selected case")
        if self.catalog_id != "MEM-01" and self.memory_window_ms != 30000:
            raise ValueError("Memory window belongs to the memory procedure")
        local = self.catalog_id in ("IF-01", "SEC-04", "VOICE-01") or (
            self.catalog_id == "MEM-01" and bool(self.groups) and set(self.groups) <= {"C1", "C3"}
        )
        if not local and set(self.roles) != {"A", "B"}:
            raise ValueError("The link and campaign procedures require both hardware roles")
        one_stability_direction = self.catalog_id == "OPS-01" and self.groups == ["C6"]
        if (
            self.catalog_id in ("IF-03", "OPS-01")
            and not one_stability_direction
            and set(self.directions) != {"A_TO_B", "B_TO_A"}
        ):
            raise ValueError("Campaign procedures require both directions")
        return self


def _case(group, variant, repetition, driver, **fields):
    return {
        "group": group,
        "variant": variant,
        "repetition": repetition,
        "driver": driver,
        **fields,
    }


def serial_cases(request, groups):
    for role in request.roles:
        for transport in request.transports:
            for group in groups:
                for variant in SERIAL_GROUPS[group]:
                    for repetition in range(1, 2 if group == "C1" else request.repetitions + 1):
                        yield _case(
                            group,
                            variant,
                            repetition,
                            "serial_matrix",
                            role=role,
                            transport=transport,
                            cycles=request.valid_cycles if group == "C1" else 1,
                        )


def link_cases(request, groups):
    for group in groups:
        for variant, size in LINK_GROUPS[group]:
            for direction in request.directions:
                for repetition in range(1, request.repetitions + 1):
                    yield _case(
                        group,
                        variant,
                        repetition,
                        "known_data_batch" if group != "C3" else "peer_mismatch",
                        role=direction,
                        direction=direction,
                        message_bytes=size,
                        message_count=request.messages_per_case if group != "C3" else 1,
                    )


def campaign_cases(request, groups):
    for group in groups:
        for variant in CAMPAIGN_GROUPS[group]:
            for repetition in range(1, 2 if group == "C1" else request.repetitions + 1):
                case = _case(
                    group,
                    variant,
                    repetition,
                    "campaign_restart_review" if group == "C6" else "campaign_matrix",
                    role="A ↔ B",
                    messages_per_case=request.messages_per_case,
                    campaign_cases=6,
                )
                if group == "C6":
                    case["campaign_request"] = campaign_intent(request, case).model_dump()
                yield case


def compile_matrix(request, *, message_limit=65536):
    generated = {
        "IF-01": serial_cases,
        "IF-02": link_cases,
        "IF-03": campaign_cases,
        "MODEL-01": model_series.cases,
        **{catalog: fault_matrices.cases for catalog in fault_matrices.GROUPS},
        "TIME-01": timed_series.cases,
        "VOICE-02": voice_matrix.cases,
        "VOICE-03": sustained_voice.cases,
        "VOICE-01": local_voice.cases,
        "OPS-01": ops_matrix.cases,
        "SEC-04": timed_series.cases,
    }.get(request.catalog_id, rf_sweeps.cases)
    groups = request.groups or list(GROUPS[request.catalog_id])
    if request.catalog_id == "MEM-01":
        candidates = memory_matrix.cases(request, groups, message_limit)
    elif request.catalog_id in content_series.GROUPS:
        candidates = content_series.cases(request, groups, message_limit)
    else:
        candidates = generated(request, groups)
    cases = [
        {
            "id": f"{request.catalog_id}-{index + 1:03d}-{case['group']}-{case['variant']}",
            "index": index,
            **case,
        }
        for index, case in enumerate(candidates)
    ]
    coverage = (
        set(groups) == set(GROUPS[request.catalog_id])
        and request.repetitions == 3
        and request.subset_sizes is None
    )
    if request.catalog_id == "IF-01":
        coverage = coverage and request.valid_cycles == 10 and set(request.roles) == {"A", "B"}
    elif request.catalog_id == "SEC-04":
        coverage = coverage and request.diagnostic_iterations == 1000 and len(request.roles) == 2
    elif request.catalog_id == "MEM-01":
        coverage = coverage and request.memory_window_ms == 30000 and len(request.directions) == 2
    elif request.catalog_id == "VOICE-01":
        coverage = (
            coverage and len(request.voice_reference_ids or ()) == 3 and len(request.roles) == 2
        )
    elif request.catalog_id == "VOICE-02":
        coverage = (
            coverage
            and len(request.voice_reference_ids or ()) == 3
            and len(request.directions) == 2
        )
    elif request.catalog_id == "VOICE-03":
        coverage = coverage and bool(request.voice_reference_ids) and len(request.directions) == 2
    elif request.catalog_id in fault_matrices.GROUPS:
        coverage = (
            coverage
            and len(request.directions) == 2
            and (request.catalog_id.startswith("SEC") or request.messages_per_case >= 10)
        )
    elif request.catalog_id in ("MODEL-01", "OPS-01"):
        coverage = coverage and request.messages_per_case >= 10 and len(request.directions) == 2
    else:
        coverage = coverage and request.messages_per_case == 100 and len(request.directions) == 2
    if request.catalog_id == "OPS-01":
        coverage = coverage and request.ops_observation_s == ops_matrix.STABILITY_SECONDS
    if request.catalog_id in rf_sweeps.DEFAULT_ECHO_SERIES:
        coverage = coverage and rf_sweeps.echo_count(request) == 100
    plan = {
        "procedure_revision": REVISION,
        "catalog_id": request.catalog_id,
        "request": request.model_dump(),
        "cases": cases,
        "case_count": len(cases),
        "full_plan": coverage,
    }
    plan["sha256"] = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return plan


def link_request(matrix, case, ordinal):
    if case.get("driver") == "rf_sweep":
        return rf_sweeps.sweep_request(matrix, case, ordinal)
    if case.get("driver") == "content_series":
        return content_series.run_request(matrix, case, ordinal)
    # Match seeds across directions and sizes within the same repetition.
    seed = (matrix.seed + (case["repetition"] - 1) * 100 + ordinal) % 2**32
    return RadioRunRequest(
        direction=case["direction"],
        message_bytes=case["message_bytes"],
        source_seed=seed,
    )


def campaign_intent(matrix, case):
    return CampaignSpec(
        name=f"IF-03 {case['group']} {case['variant']} {case['repetition']}",
        repetitions=matrix.messages_per_case,
        templates=[
            Template(
                label=f"Repetition {repetition + 1}",
                case=RadioCase(
                    kind="known_data",
                    request=RadioRunRequest(
                        source_seed=(matrix.seed + repetition * 100) % 2**32,
                    ),
                ),
            )
            for repetition in range(3)
        ],
    )
