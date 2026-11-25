"""Stable integration case plans shared by host execution and evidence views."""

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from . import content_series, rf_sweeps
from .campaign_plans import CampaignSpec, RadioCase, Template
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
}


class MatrixRequest(ContractModel):
    catalog_id: Literal[
        "IF-01", "IF-02", "IF-03", "RF-01", "RF-02", "RF-03", "RF-04", "PKT-01", "SEC-01"
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
    messages_per_case: int = Field(default=100, ge=1, le=100)
    seed: int = Field(default=743, ge=0, le=2**32 - 1)
    rf_security: Literal["none", "aes128_gcm"] = "none"
    subset_sizes: list[int] | None = Field(default=None, min_length=1, max_length=11)

    @model_validator(mode="after")
    def selections(self):
        for choices in (
            self.groups,
            self.roles,
            self.transports,
            self.directions,
            self.subset_sizes,
        ):
            if choices is not None and len(choices) != len(set(choices)):
                raise ValueError("Choose each group, role, direction or transport once")
        if self.subset_sizes is not None and (
            self.catalog_id not in content_series.GROUPS
            or any(size < 1 or size > 65537 for size in self.subset_sizes)
        ):
            raise ValueError("Size selection belongs to a valid packet or protection series")
        if self.groups is not None and not set(self.groups) <= set(GROUPS[self.catalog_id]):
            raise ValueError("Choose groups that belong to the selected procedure")
        if self.catalog_id != "IF-01" and set(self.roles) != {"A", "B"}:
            raise ValueError("The link and campaign procedures require both hardware roles")
        if self.catalog_id == "IF-03" and set(self.directions) != {"A_TO_B", "B_TO_A"}:
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
                yield _case(
                    group,
                    variant,
                    repetition,
                    "campaign_matrix",
                    role="A ↔ B",
                    messages_per_case=request.messages_per_case,
                    campaign_cases=6,
                )


def compile_matrix(request, *, message_limit=65536):
    generated = {"IF-01": serial_cases, "IF-02": link_cases, "IF-03": campaign_cases}.get(
        request.catalog_id, rf_sweeps.cases
    )
    groups = request.groups or list(GROUPS[request.catalog_id])
    candidates = (
        content_series.cases(request, groups, message_limit)
        if request.catalog_id in content_series.GROUPS
        else generated(request, groups)
    )
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
    else:
        coverage = coverage and request.messages_per_case == 100 and len(request.directions) == 2
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
