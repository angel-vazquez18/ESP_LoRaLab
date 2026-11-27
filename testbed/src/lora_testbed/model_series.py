"""Check the airtime model and retain source-local residual observations."""

import csv
import io
from fractions import Fraction
from itertools import product
from math import ceil
from statistics import median
from uuid import uuid4

from . import fault_accounting
from .experiments_v2 import (
    MODEL_VERSION,
    KnownDataPlan,
    Link,
    Radio,
    airtime_us,
    known_data,
    ldro_enabled,
    preview,
)
from .fault_protocol_v2 import Injection
from .radio_runs import LabRadioRunRequest, RadioRunRequest

GROUPS = {
    "MODEL-01": {
        "C1": "independent_numerical_vectors",
        "C2": "isolated_frame_comparison",
        "C3": "delivery_duration_comparison",
    }
}
REFERENCE = (
    "https://github.com/Lora-net/LoRaMac-node/blob/"
    "cf779a46f52f9b22395a207c6853f3efb47f0e5b/src/radio/sx126x/radio.c#L917-L1010"
)
SPREADING = (7, 9, 12)
BANDWIDTH = (125000, 250000, 500000)
CODING = (5, 8)
FRAME_PROFILES = (
    (64, "none"),
    (64, "aes128_gcm"),
    (160, "none"),
    (160, "aes128_gcm"),
    (199, "aes128_gcm"),
)
WORKSHEET_US = {
    (7, 125000, 5, 120): 199936,
    (7, 125000, 5, 216): 343296,
    (12, 125000, 5, 216): 7872512,
}


def cases(request, groups):
    count = min(request.messages_per_case, 10)
    for group in groups:
        if group == "C3":
            for size, policy, direction, repetition in product(
                (64, 160, 1200),
                ("none", "ack", "controlled_retry"),
                request.directions,
                range(1, request.repetitions + 1),
            ):
                if request.subset_sizes is not None and size not in request.subset_sizes:
                    continue
                yield {
                    "group": group,
                    "variant": f"bytes_{size}_{policy}",
                    "repetition": repetition,
                    "driver": "model_message",
                    "role": direction,
                    "direction": direction,
                    "message_bytes": size,
                    "message_count": count,
                    "policy": policy,
                }
            continue
        roles = ("reference",) if group == "C1" else request.directions
        for sf, bandwidth, coding, (size, security), role in product(
            SPREADING, BANDWIDTH, CODING, FRAME_PROFILES, roles
        ):
            if request.subset_sizes is not None and size not in request.subset_sizes:
                continue
            frame_bytes = 40 + size + (16 if security == "aes128_gcm" else 0)
            yield {
                "group": group,
                "variant": f"sf{sf}_{bandwidth // 1000}khz_cr{coding}_{frame_bytes}",
                "driver": "model_reference" if group == "C1" else "model_frame",
                "repetition": 1,
                "role": role,
                "direction": role if group != "C1" else None,
                "radio": Radio(
                    spreading_factor=sf,
                    bandwidth_hz=bandwidth,
                    coding_rate_denominator=coding,
                    tx_power_dbm=2,
                ).model_dump(),
                "message_bytes": size,
                "message_count": 1 if group == "C1" else count,
                "security": security,
                "expected_frame_bytes": frame_bytes,
            }


def reference_result(case):
    settings = Radio.model_validate(case["radio"])
    length = case["expected_frame_bytes"]
    sf, bandwidth, coding = (
        settings.spreading_factor,
        settings.bandwidth_hz,
        settings.coding_rate_denominator,
    )
    # The pinned reference uses an explicit modem/bandwidth table for this domain.
    reference_ldro = (sf in (11, 12) and bandwidth == 125000) or (sf == 12 and bandwidth == 250000)
    header_and_crc_bits = 20 + 16
    encoded_octets = length * 8
    interleaver_blocks = ceil(
        Fraction(
            max(0, encoded_octets + header_and_crc_bits + 8 - 4 * sf), 4 * (sf - 2 * reference_ldro)
        )
    )
    total_symbols = settings.preamble_symbols + 12 + Fraction(1, 4) + coding * interleaver_blocks
    microseconds_per_symbol = Fraction(2**sf * 10**6, bandwidth)
    expected = ceil(total_symbols * microseconds_per_symbol)
    actual = airtime_us(settings, length)
    golden = WORKSHEET_US.get((sf, bandwidth, coding, length))
    return {
        "model_version": MODEL_VERSION,
        "reference": REFERENCE,
        "reference_airtime_us": expected,
        "calculated_airtime_us": actual,
        "worksheet_airtime_us": golden,
        "reference_ldro": reference_ldro,
        "calculated_ldro": ldro_enabled(settings),
        "passed": expected == actual
        and (golden is None or golden == actual)
        and reference_ldro == ldro_enabled(settings),
    }


def link_request(spec, case, ordinal):
    radio = Radio.model_validate(case["radio"])
    return RadioRunRequest(
        direction=case["direction"],
        radio=radio,
        security=case["security"],
        link=Link(fragment_payload_bytes=max(160, case["message_bytes"])),
        message_bytes=case["message_bytes"],
        source_seed=(spec.seed + ordinal) % 2**32,
        timeout_ms=30000,
    )


def observed_comparison(run, ledger_rows):
    cases = {case["id"]: case for case in run["cases"]}
    points = []
    for evidence in ledger_rows:
        doc = evidence["document"]
        case = cases.get(evidence["case_id"])
        if case is None:
            continue
        if "frame_observation" in doc and case["group"] == "C2":
            observed = doc["frame_observation"]
            basis = "isolated_frame"
            identifier = observed["child_run_id"]
            predicted = observed["predicted_airtime_us"]
            measured = observed["tx_command_to_done_us"]
            expanded = None
        elif "message_observation" in doc and case["group"] == "C3":
            observed = doc["message_observation"]
            basis = "sender_completion"
            identifier = observed["child_run_id"]
            predicted = observed["modeled_nominal_sender_us"]
            measured = observed["observed_sender_completion_us"]
            expanded = observed["modeled_worst_case_run_us"]
        else:
            continue
        points.append(
            {
                "basis": basis,
                "direction": case["direction"],
                "configuration": case["variant"],
                "repetition": case["repetition"],
                "case_id": case["id"],
                "child_run_id": identifier,
                "message_bytes": case["message_bytes"],
                "frame_bytes": observed.get("frame_bytes"),
                "security": case["security"] if basis == "isolated_frame" else observed["security"],
                "predicted_us": predicted,
                "measured_us": measured,
                "residual_us": measured - predicted,
                "expanded_run_budget_us": expanded,
                "within_expanded_budget": observed.get("within_expanded_budget"),
            }
        )
    return {"points": points, "physical_agreement_assessed": False}


def comparison_csv(comparison):
    output = io.StringIO(newline="")
    fields = (
        "basis",
        "direction",
        "configuration",
        "repetition",
        "case_id",
        "child_run_id",
        "message_bytes",
        "frame_bytes",
        "security",
        "predicted_us",
        "measured_us",
        "residual_us",
        "expanded_run_budget_us",
        "within_expanded_budget",
    )
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(comparison["points"])
    return output.getvalue()


def observed_result(reference, rows, requested):
    return {
        **reference,
        "sample_count": len(rows),
        "requested_samples": requested,
        "residual_us_median": median(row["duration_minus_prediction_us"] for row in rows)
        if rows
        else None,
        "measurement_basis": "node-local TX command through TX done; includes radio and IRQ delay",
        "on_air_marker_available": False,
        "physical_agreement_assessed": False,
    }


def message_request(spec, case, ordinal):
    policy = case["policy"]
    link = Link(
        ack_mode="none" if policy == "none" else "stop_wait",
        max_retries=int(policy == "controlled_retry"),
    )
    values = {
        "direction": case["direction"],
        "radio": Radio(tx_power_dbm=2),
        "security": "aes128_gcm",
        "link": link,
        "message_bytes": case["message_bytes"],
        "source_seed": (spec.seed + 10 * (case["repetition"] - 1) + ordinal) % 2**32,
        "timeout_ms": 30000,
    }
    if policy == "controlled_retry":
        injection = Injection(
            injection_id=str(uuid4()),
            stage="rx_before_reassembly",
            action="drop",
            message_id=1,
            fragment_index=0,
            attempt_index=1,
            xor_mask=None,
            byte_offset=None,
            block_size=None,
        )
        return LabRadioRunRequest(**values, injection=injection)
    return RadioRunRequest(**values)


def message_observation(record, request):
    if not fault_accounting.verified_control(record):
        return None
    expected = known_data(request.source_seed, 1, request.message_bytes)
    fault = fault_accounting.assess(record, expected) if record.get("lab") else None
    if fault and fault["outcome"] != "pass":
        return None
    sender = record["sender"]
    accounting = record["accounting"]
    settings = record["applied_settings"][sender]["radio"]
    radio = Radio.model_validate({k: v for k, v in settings.items() if k != "ldro_enabled"})
    if settings["ldro_enabled"] != ldro_enabled(radio):
        return None
    complete = [
        event
        for event in record["events"]
        if event["name"] == "tx.attempt" and event["data"]["status"] == "completed"
    ]
    tx = record["summaries"][sender]
    first_tx, last_tx = tx["first_tx_command_us"], tx["last_tx_done_us"]
    if first_tx is None or last_tx is None or last_tx < first_tx:
        return None
    acks = [
        event["uptime_us"]
        for event in record["events"]
        if event["role"] == sender
        and event["name"] == "ack.result"
        and event["data"]["status"] == "received"
    ]
    model = preview(KnownDataPlan(radio=radio, link=request.link, spec=request.plan().spec))
    budget = model["timing"]
    expected_retries = int(bool(fault))
    if accounting["data_retries"] != expected_retries:
        return None
    completion = max(last_tx, max(acks, default=last_tx))
    observed_us = completion - first_tx
    return {
        "child_run_id": record["id"],
        "security": request.security,
        "modeled_nominal_run_us": budget["nominal_duration_us"],
        "modeled_nominal_sender_us": budget["nominal_duration_us"] - budget["budget"]["drain_us"],
        "modeled_worst_case_run_us": budget["worst_case_duration_us"],
        "modeled_frame_airtime_total_us": sum(
            airtime_us(radio, event["data"]["frame_bytes"]) for event in complete
        ),
        "observed_sender_completion_us": observed_us,
        "observed_sender_scope": "first TX command through last TX done or accepted ACK",
        "first_tx_command_us": first_tx,
        "last_tx_done_us": last_tx,
        "last_accepted_ack_event_us": max(acks, default=None),
        "original_data_frames": accounting["data_originals"],
        "data_attempts": accounting["data_attempts"],
        "confirmed_ack_transmissions": accounting["ack_transmissions"],
        "controlled_retry_checks": fault["checks"] if fault else [],
        "within_expanded_budget": observed_us <= budget["worst_case_duration_us"],
        "physical_agreement_assessed": False,
    }
