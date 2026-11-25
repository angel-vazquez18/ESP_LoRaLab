"""Fault controls through a pair of native node runtimes and the radio fixtures."""

import hashlib

import pytest
from test_lab_fault_commands_native import LabPair, injection
from test_node_control_native import native_library as native_library

from lora_testbed.experiments_v2 import Link, known_data, preview
from lora_testbed.fault_protocol_v2 import Applied
from lora_testbed.run_protocol_v2 import ARM_WINDOW_US


@pytest.mark.parametrize("action", ["drop", "drop_ack"])
@pytest.mark.parametrize("direction", ["A_TO_B", "B_TO_A"])
@pytest.mark.parametrize("protected", [False, True])
def test_exact_retry_recovers_without_duplicate_delivery(
    native_library, action, direction, protected
):
    pair = LabPair(native_library)
    pair.protected = protected
    try:
        entry = injection(action)
        pair.prepare(
            entry,
            direction=direction,
            link=Link(fragment_payload_bytes=64, ack_mode="stop_wait", max_retries=1),
        )
        data = pair.sent(pair.source)
        pair.tx_done(pair.source)
        first = pair.inject(pair.target, data)
        pair.tick(pair.target, 20001)
        accepted = [r for r in first if r.get("name") == "rx.accepted"]
        assert len(accepted) == int(action == "drop_ack")
        assert pair.summary(pair.target)["tx_attempts"] == 0
        applied = next(
            Applied.model_validate(r["data"])
            for r in pair.events[pair.target]
            if r.get("name") == "fault.applied"
        )
        assert applied.injection_id == entry["injection_id"]
        assert applied.before_sha256 == applied.after_sha256 == hashlib.sha256(data).hexdigest()
        arrived = next(r["data"] for r in first if r.get("name") == "rx.frame")
        assert applied.target_arrived_us == arrived["rx_done_us"]
        assert applied.target_frame_seq == arrived["frame_seq"]

        timeout = preview(pair.plan)["timing"]["budget"]["ack_timeout_us"]
        pair.tick(pair.source, timeout + 1)
        pair.tick(pair.source, 50001)
        assert pair.sent(pair.source) == data
        pair.tx_done(pair.source)
        second = pair.inject(pair.target, data)
        assert sum(r.get("name") == "rx.accepted" for r in second) == int(action == "drop")
        pair.tick(pair.target, 20001)
        ack = pair.sent(pair.target)
        assert ack[3] == 2 and ack[34:38] == data[16:20]
        pair.tx_done(pair.target)
        rows = pair.inject(pair.source, ack)
        assert any(r.get("name") == "ack.result" for r in rows)
        assert pair.summary(pair.source)["tx_attempts"] == 2
        assert pair.summary(pair.target)["delivered_messages"] == 1
        assert pair.summary(pair.target)["tx_attempts"] == 1
        assert sum(r.get("name") == "fault.applied" for r in pair.events[pair.target]) == 1
    finally:
        pair.close()


def test_bad_tag_does_not_advance_receiver_fault_arrival_ordinal(native_library):
    pair = LabPair(native_library)
    try:
        pair.prepare(injection("drop"))
        data = pair.sent(pair.source)
        damaged = data[:-1] + bytes([data[-1] ^ 1])
        first = pair.inject(pair.target, damaged)
        assert any(r.get("name") == "rx.rejected" for r in first)
        second = pair.inject(pair.target, data)
        assert not any(r.get("name") == "rx.accepted" for r in second)
        pair.tick(pair.target)
        events = [r for r in pair.events[pair.target] if r.get("name") == "fault.applied"]
        assert len(events) == 1
        assert events[0]["data"]["before_sha256"] == hashlib.sha256(data).hexdigest()
    finally:
        pair.close()


@pytest.mark.parametrize("protected", [False, True])
@pytest.mark.parametrize("selected", [0, 2])
def test_duplicate_transmits_identical_bytes_without_an_extra_original(
    native_library, protected, selected
):
    pair = LabPair(native_library)
    pair.protected = protected
    try:
        entry = injection("duplicate", fragment_index=selected)
        pair.prepare(entry, link=Link(fragment_payload_bytes=16), byte_count=33)
        for index in range(3):
            data = pair.sent(pair.source)
            assert int.from_bytes(data[24:26], "big") == index
            pair.tx_done(pair.source)
            pair.inject(pair.target, data)
            pair.tick(pair.source, 50001)
            if index == selected:
                assert pair.sent(pair.source) == data
                pair.tx_done(pair.source)
                pair.inject(pair.target, data)
                pair.tick(pair.source, 50001)

        attempts = [row for row in pair.events[pair.source] if row.get("name") == "tx.attempt"]
        extras = [row["data"] for row in pair.events[pair.source] if row.get("name") == "fault.tx"]
        assert len(attempts) == 3 and len(extras) == 1
        assert extras[0]["fragment_index"] == selected
        assert extras[0]["injection_id"] == entry["injection_id"]
        assert extras[0]["status"] == "completed"
        assert extras[0]["wire_sha256"] == attempts[selected]["data"]["wire_sha256"]
        assert pair.summary(pair.source)["original_packets"] == 3
        result = pair.summary(pair.target)
        assert result["accepted_fragments"] == 3 and result["delivered_messages"] == 1
        assert any(
            row.get("name") == "rx.rejected" and row["data"]["stage"] == "replay"
            for row in pair.events[pair.target]
        )
    finally:
        pair.close()


@pytest.mark.parametrize("protected, block", [(False, 4), (True, 4), (True, 32)])
def test_reverse_block_preserves_wire_sequences_and_exact_order(native_library, protected, block):
    pair = LabPair(native_library)
    pair.protected = protected
    try:
        entry = injection("reverse_block", fragment_index=1, block_size=block)
        length = (block + 2) * 16 + 1
        pair.prepare(
            entry, direction="B_TO_A", link=Link(fragment_payload_bytes=16), byte_count=length
        )
        order = [0, *range(block, 0, -1), block + 1, block + 2]
        for index in order:
            data = pair.sent(pair.source)
            assert int.from_bytes(data[24:26], "big") == index
            assert int.from_bytes(data[16:20], "big") == index + 1
            pair.tx_done(pair.source)
            pair.inject(pair.target, data)
            pair.tick(pair.source, 50001)
        assert [
            row["data"]["fragment_index"]
            for row in pair.events[pair.target]
            if row.get("name") == "rx.accepted"
        ] == order
        assert [
            row["data"]["fragment_index"]
            for row in pair.events[pair.source]
            if row.get("name") == "tx.attempt"
        ] == order
        source = pair.summary(pair.source)
        target = pair.summary(pair.target)
        assert source["original_packets"] == source["tx_attempts"] == len(order)
        assert target["accepted_fragments"] == len(order) and target["delivered_messages"] == 1
        delivered = next(
            row["data"] for row in pair.events[pair.target] if row.get("name") == "message.result"
        )
        assert delivered["sha256"] == hashlib.sha256(known_data(743, 1, length)).hexdigest()
        assert sum(row.get("name") == "fault.applied" for row in pair.events[pair.source]) == 1
    finally:
        pair.close()


def test_lost_middle_fragment_reports_only_the_missing_index(native_library):
    pair = LabPair(native_library)
    try:
        pair.prepare(
            injection("drop", fragment_index=1), link=Link(fragment_payload_bytes=16), byte_count=33
        )
        for _ in range(3):
            data = pair.sent(pair.source)
            pair.tx_done(pair.source)
            pair.inject(pair.target, data)
            pair.tick(pair.source, 50001)
        budget = preview(pair.plan)["timing"]["budget"]
        elapsed = budget["reassembly_timeout_us"] + ARM_WINDOW_US + 1
        while elapsed:
            step = min(elapsed, 1_000_000)
            assert pair.node(pair.target).request("control.keepalive")["ok"]
            pair.tick(pair.target, step)
            elapsed -= step
        for _ in range(5):
            pair.tick(pair.target)
        rows = pair.events[pair.target]
        assert [r["data"]["fragment_index"] for r in rows if r.get("name") == "rx.accepted"] == [
            0,
            2,
        ]
        missed = [r["data"]["ranges"] for r in rows if r.get("name") == "message.missing"]
        assert missed == [[[1, 1]]]
        result = pair.summary(pair.target)
        assert result["delivered_messages"] == 0 and result["failed_messages"] == 1
    finally:
        pair.close()


def test_overlapping_reorder_plan_is_rejected_before_arming(native_library):
    pair = LabPair(native_library)
    try:
        entry = injection("reverse_block", fragment_index=1, block_size=3)
        pair.prepare(entry, start=False, byte_count=81, link=Link(fragment_payload_bytes=16))
        node = pair.node(pair.source)
        conflicting = injection("reverse_block", fragment_index=3, block_size=2)
        rejected = node.request(
            "fault.set", dict(injections=[conflicting], replace=False), run_id=pair.run
        )
        assert not rejected["ok"] and rejected["error"]["code"] == "INVALID_ARGUMENT"
        states = node.request("fault.status", {}, run_id=pair.run)["result"]["entries"]
        assert [row["injection_id"] for row in states] == [entry["injection_id"]]
    finally:
        pair.close()
