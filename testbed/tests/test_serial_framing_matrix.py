"""Exercise IF-01 framing through the production matrix and native control parser."""

import asyncio
from collections import Counter

import pytest
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed import v2
from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest
from lora_testbed.serial_framing import INVALID_LINES, REJECTION_COUNTERS, VARIANTS, assess_counters


def test_grouped_framing_cases_reconcile_device_counters_and_host_boundaries(
    tmp_path, native_library
):
    async def scenario():
        host = Host(tmp_path)
        peer = NativeSerial(native_library)
        node = host.physical["B"]
        node.opener = lambda _: peer
        try:
            await node.connect("isolated-native-serial")
            spec = MatrixRequest(catalog_id="IF-01", groups=["C3"], roles=["B"])
            preview = host.procedures.matrix_preview(spec, host.radio)
            assert preview["ready_case_count"] == 3 * len(VARIANTS)
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(60):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "pass", saved
            assert set(saved["physical_bindings"]) == {"B"}
            assert not saved["hardware_validated"]
            rows = list(host.procedures.all_evidence(saved["id"]))
            for case in saved["cases"]:
                variant = case["variant"]
                assert case["cleanup_verified"] and case["assessment"] == "pass"
                documents = [row["document"] for row in rows if row["case_id"] == case["id"]]
                [assessment] = [
                    doc["counter_assessment"] for doc in documents if "counter_assessment" in doc
                ]
                assert assessment["observed_deltas"] == assessment["expected_deltas"]
                expected = INVALID_LINES[variant][1] if variant in INVALID_LINES else None
                assert {k for k, count in assessment["observed_deltas"].items() if count} == (
                    {expected} if expected else set()
                )
                counts = Counter(doc["direction"] for doc in documents)
                assert counts["host_to_node"] == counts["node_to_host"]
                assert counts["node_to_host"] == {
                    "representative_board_splits": 4,
                    "concatenated_records": 3,
                }.get(variant, 2)
                if variant in ("maximum_size_record", "oversized_record", "crlf_record"):
                    [writes] = [doc["serial_writes"] for doc in documents if "serial_writes" in doc]
                    if variant == "maximum_size_record":
                        assert sum(chunk["bytes"] for chunk in writes) == v2.MAX_LINE_BYTES
                    elif variant == "oversized_record":
                        assert sum(chunk["bytes"] for chunk in writes[:-1]) == v2.MAX_LINE_BYTES + 1
                    else:
                        [command] = [
                            v2.Command.model_validate(doc["record"])
                            for doc in documents
                            if doc["direction"] == "host_to_node"
                        ][1:]
                        assert writes[0]["bytes"] == len(v2.encode(command)) + 1
                if variant == "split_every_boundary":
                    [boundaries] = [
                        doc["framing_boundaries"]
                        for doc in documents
                        if "framing_boundaries" in doc
                    ]
                    assert boundaries["checked_boundaries"] == boundaries["expected_boundaries"]
                    assert boundaries["checked_boundaries"] > 100
            assert not node.pending
            assert node.health.node_role == "B" and node.health.state == "idle"
        finally:
            await host.close()

    asyncio.run(scenario())


def test_cancelling_after_partial_record_closes_port_and_releases_pending_waiter(
    tmp_path, native_library
):
    async def scenario():
        host = Host(tmp_path)
        peer = NativeSerial(native_library)
        node = host.physical["A"]
        node.opener = lambda _: peer
        try:
            await node.connect("isolated-native-serial")
            original = node.write_wire
            partial = asyncio.Event()

            async def watch(wire):
                written = await original(wire)
                if wire == b"{":
                    partial.set()
                return written

            node.write_wire = watch
            task = asyncio.create_task(
                node.exercise_serial_framing("representative_board_splits", lambda _: None)
            )
            async with asyncio.timeout(3):
                await partial.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert peer.closed and not node.connected and not node.pending
        finally:
            await host.close()

    asyncio.run(scenario())


def test_counter_evidence_distinguishes_missing_telemetry_from_wrong_deltas():
    before = {"traffic": dict.fromkeys(REJECTION_COUNTERS, 0)}
    missing = {"traffic": {}}
    assert assess_counters("oversized_record", before, missing) == {
        "outcome": "inconclusive",
        "missing_counters": list(REJECTION_COUNTERS),
    }
    no_rejection = assess_counters("oversized_record", before, before)
    assert no_rejection["outcome"] == "fail"
    assert no_rejection["expected_deltas"]["rx_oversized"] == 1
    assert no_rejection["observed_deltas"]["rx_oversized"] == 0
