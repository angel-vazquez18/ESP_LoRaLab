"""Independent RTT matching and clock-cohort statistics, never hardware qualification."""

import hashlib
from copy import deepcopy

import pytest

from lora_testbed.echo_accounting import assess, distributions
from lora_testbed.experiments_v2 import known_data


def record(identifier="run1", rtt=20, *, role="A", boot="A:1"):
    peer = "B" if role == "A" else "A"
    expected = known_data(743, 1, 32)
    session = "0102030405060708"
    common = dict(session_id=session, message_id=1, fragment_index=0)
    result = dict(
        session_id=session,
        request_frame_seq=7,
        reply_frame_seq=9,
        payload_bytes=32,
        payload_sha256=hashlib.sha256(expected).hexdigest(),
        reply_hex=expected.hex(),
        tx_command_us=100,
        reply_accepted_us=100 + rtt,
        rtt_us=rtt,
        valid=True,
        reason="matched",
    )

    def row(source, name, data):
        return dict(
            role=source,
            device_id=source,
            boot_id=boot if source == role else peer + ":1",
            run_id=identifier,
            name=name,
            data=data,
        )

    events = [
        row(
            role,
            "tx.attempt",
            dict(
                **common,
                frame_seq=7,
                frame_type="echo_request",
                frame_bytes=72,
                status="completed",
                attempt_index=1,
                tx_command_us=100,
                tx_done_us=105,
            ),
        ),
        row(
            peer,
            "tx.attempt",
            dict(
                **common,
                frame_seq=9,
                frame_type="echo_reply",
                frame_bytes=72,
                status="completed",
                attempt_index=1,
                tx_command_us=1000000,
                tx_done_us=1000005,
            ),
        ),
        row(
            peer,
            "rx.frame",
            dict(
                **common,
                frame_seq=7,
                frame_type="echo_request",
                frame_bytes=72,
                source_role=role,
                crc_ok=True,
                rx_done_us=999999,
            ),
        ),
        row(
            peer,
            "rx.accepted",
            dict(**common, frame_seq=7, source_role=role, payload_bytes=32, accepted_us=999999),
        ),
        row(
            role,
            "rx.frame",
            dict(
                **common,
                frame_seq=9,
                frame_type="echo_reply",
                frame_bytes=72,
                source_role=peer,
                crc_ok=True,
                rx_done_us=100 + rtt,
            ),
        ),
        row(
            role,
            "rx.accepted",
            dict(**common, frame_seq=9, source_role=peer, payload_bytes=32, accepted_us=100 + rtt),
        ),
        row(role, "echo.result", result),
    ]
    return dict(
        id=identifier,
        sender=role,
        receiver=peer,
        session_id=session,
        status="completed",
        evidence_error=None,
        identities={
            role: dict(device_id=role, boot_id=boot),
            peer: dict(device_id=peer, boot_id=peer + ":1"),
        },
        plan=dict(
            radio={},
            link=dict(fragment_payload_bytes=160, ack_mode="none", max_retries=0),
            spec=dict(source="echo", source_seed=743, message_bytes=32, security="none"),
        ),
        events=events,
        summaries={
            role: dict(echo=deepcopy(result), telemetry_drops=0),
            peer: dict(telemetry_drops=0),
        },
        cleanup=dict(confirmed=True),
        verification=dict(bytes_equal=True),
        host_transaction=dict(start_ns=1000, end_ns=2001000, elapsed_ns=2000000),
    )


def test_exact_local_distribution_uses_nearest_rank_with_n_and_separate_host_time():
    records = [record(str(i), value) for i, value in enumerate([10, 20, 30, 40, 50])]
    result = distributions(records)
    group = result["groups"][0]
    assert group["n"] == 5 and group["median_us"] == 30 and group["p95_us"] == 50
    assert group["samples"][0]["host_transaction_ns"] == 2000000
    assert group["samples"][0]["rtt_us"] == 10
    assert not result["hardware_qualified"]


@pytest.mark.parametrize(
    "fault",
    ["boot", "reference", "content", "tx_time", "accept_time", "gap", "cancel", "duplicate"],
)
def test_inconsistent_evidence_cannot_be_a_timing_sample(fault):
    value = record()
    if fault == "boot":
        value["events"][-1]["boot_id"] = "A:2"
    elif fault == "reference":
        value["events"][-1]["data"]["request_frame_seq"] = 8
    elif fault == "content":
        value["events"][-1]["data"]["reply_hex"] = "00" * 32
    elif fault == "tx_time":
        value["events"][0]["data"]["tx_command_us"] = 99
    elif fault == "accept_time":
        value["events"][-2]["data"]["accepted_us"] = 119
    elif fault == "gap":
        value["evidence_error"] = "telemetry gap"
    elif fault == "cancel":
        value["status"] = "cancelled"
    else:
        value["events"].append(deepcopy(value["events"][-1]))
    result = assess(value)
    assert result["n"] == 0 and result["median_us"] is None and result["p95_us"] is None
    assert result["exclusions"][0]["reason"]


def test_missing_timeout_and_late_duplicate_rejections_are_retained_without_zero_latency():
    value = record()
    result = value["events"][-1]["data"]
    result.update(
        valid=False, reason="timeout", rtt_us=None, reply_accepted_us=None, reply_hex=None
    )
    value["summaries"]["A"]["echo"] = deepcopy(result)
    value["events"] = value["events"][:1] + value["events"][-1:]
    for reason in ("late", "duplicate"):
        value["events"].append(
            dict(
                role="A",
                device_id="A",
                boot_id="A:1",
                run_id=value["id"],
                name="rx.rejected",
                data=dict(reason=reason, stage="reassembly"),
            )
        )
    assessed = assess(value)
    assert assessed["n"] == 0 and assessed["median_us"] is None
    assert assessed["exclusions"][0]["reason"] == "timeout"
    assert [r["reason"] for r in assessed["rejections"]] == ["late", "duplicate"]


def test_roles_boots_and_settings_are_distinct_cohorts_and_duplicate_run_ids_reject():
    values = [record("1"), record("2", role="B", boot="B:1"), record("3", boot="A:2"), record("4")]
    values[-1]["plan"]["radio"] = {"spreading_factor": 8}
    assert len(distributions(values)["groups"]) == 4
    with pytest.raises(ValueError, match="duplicate"):
        distributions([values[0], values[0]])


def test_even_median_and_nearest_rank_boundary_are_exact():
    group = distributions(record(str(i), i) for i in range(11, 31))["groups"][0]
    assert group["n"] == 20 and group["median_us"] == 20.5 and group["p95_us"] == 29


def test_duplicate_rejections_after_success_preserve_one_sample_and_bounded_projection():
    value = record()
    for _ in range(200):
        value["events"].append(
            dict(
                role="A",
                device_id="A",
                boot_id="A:1",
                run_id=value["id"],
                name="rx.rejected",
                data=dict(reason="duplicate", stage="replay"),
            )
        )
    result = assess(value)
    assert result["n"] == 1 and result["rejection_count"] == 200
    assert len(result["rejections"]) == 128 and result["rejections_truncated"]
    group = distributions([value])["groups"][0]
    assert group["n"] == 1 and group["rejection_count"] == 200 and len(group["rejections"]) == 128
    assert len(value["events"]) == 207


def test_selection_limit_is_finite_even_with_streamed_input():
    with pytest.raises(ValueError, match="1000"):
        distributions(record(str(i)) for i in range(1001))
