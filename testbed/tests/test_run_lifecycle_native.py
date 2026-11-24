"""Preparation and arming protect real finite run effects and resource ownership."""

import pytest
from test_node_control_native import NativeNode
from test_node_control_native import native_library as native_library
from test_rf_execution_native import setup


def test_sender_requires_a_fresh_arm_before_any_transmission(native_library):
    lib = native_library
    node = NativeNode(lib, radio=lib.native_radio_create())
    try:
        run, revision, _ = setup(node, sender=True)
        transfers = lib.native_radio_transfers()
        rejected = node.request("run.start", {"config_revision": revision}, run_id=run)
        assert not rejected["ok"] and rejected["error"]["code"] == "INVALID_STATE"
        assert lib.native_radio_transfers() == transfers
        assert node.request("status.get")["result"]["state"] == "prepared"
        armed = node.request("run.arm", {"config_revision": revision}, run_id=run)
        assert armed["ok"] and armed["result"]["role"] == "sender"
        assert armed["result"]["receiver_ready"] is False
        assert armed["result"]["arm_deadline_us"] == node.now() + 5_000_000
        assert lib.native_radio_transfers() == transfers
        assert node.request("run.start", {"config_revision": revision}, run_id=run)["ok"]
        assert lib.native_radio_transfers() > transfers
    finally:
        node.close()


def test_receiver_reserves_all_working_memory_during_prepare_not_arm(native_library):
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        run, revision, _ = setup(node)
        reserved = dict(node.allocations)
        node.allocation_fails = True
        armed = node.request("run.arm", {"config_revision": revision}, run_id=run)
        assert armed["ok"], armed.get("error")
        assert node.allocations == reserved
        assert armed["result"]["role"] == "receiver"
        assert armed["result"]["arm_deadline_us"] == node.now() + 5_000_000
    finally:
        node.close()


@pytest.mark.parametrize("sender", [False, True])
@pytest.mark.parametrize("ack", [False, True])
def test_each_prepare_reservation_failure_rolls_back_and_allows_a_fresh_attempt(
    native_library, sender, ack
):
    from uuid import uuid4

    from lora_testbed.experiments_v2 import KnownDataPlan, KnownDataSpec, Link, preview

    class FailingNode(NativeNode):
        fail_at = None
        calls = 0

        def allocate(self, context, length):
            self.calls += 1
            if self.calls == self.fail_at:
                return None
            return super().allocate(context, length)

    failed_positions = []
    for position in range(1, 10):
        node = FailingNode(native_library, radio=native_library.native_radio_create())
        try:
            node.claim()
            run = str(uuid4())
            assert node.request(
                "session.open",
                {
                    "session_id": "0102030405060708",
                    "peer_device_id": "esp-aabbccddeeff",
                    "peer_boot_id": "esp-aabbccddeeff:1",
                    "security": "none",
                    "tx_key_hex": None,
                    "rx_key_hex": None,
                },
                run_id=run,
            )["ok"]
            link = Link(ack_mode="stop_wait" if ack else "none", max_retries=2 if ack else 0)
            assert node.request("config.set", {"radio": {}, "link": link.model_dump()})["ok"]
            plan = KnownDataPlan(
                link=link,
                spec=KnownDataSpec(
                    message_count=1,
                    direction="A_TO_B" if sender else "B_TO_A",
                    max_duration_ms=30000,
                ),
            )
            arguments = {
                "spec": plan.spec.model_dump(),
                "budget": preview(plan)["timing"]["budget"],
            }
            baseline = dict(node.allocations)
            node.calls, node.fail_at = 0, position
            reply = node.request("run.prepare", arguments, run_id=run)
            node.fail_at = None
            if reply["ok"]:
                break
            failed_positions.append(position)
            assert node.allocations == baseline
            assert node.request("artifact.list")["result"]["artifacts"] == []
            assert node.request("status.get")["result"]["state"] == "idle"
            assert node.request("run.prepare", arguments, run_id=run)["ok"]
            node.tick()
            node.drain()
            assert node.request("session.close", run_id=run)["ok"]
            # Committed evidence is retained; only working/reserved memory retires.
            files = node.request("artifact.list")["result"]["artifacts"]
            assert all(file["state"] == "committed" for file in files)
            for file in files:
                assert node.request("artifact.delete", {"artifact_id": file["artifact_id"]})["ok"]
            assert node.allocations == baseline
        finally:
            node.close()
    assert len(failed_positions) >= 3


@pytest.mark.parametrize(
    "elapsed,accepted", [(4_999_999, True), (5_000_000, False), (5_000_001, False)]
)
def test_sender_start_window_has_an_exact_boundary_and_rejection_has_no_radio_effects(
    native_library, elapsed, accepted
):
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        run, revision, _ = setup(node, sender=True)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        # Refresh the independent owner lease without extending the run arm.
        node.time += 4_000_000
        assert node.request("control.keepalive")["ok"]
        node.time += elapsed - 4_000_000
        transfers = native_library.native_radio_transfers()
        reply = node.request("run.start", {"config_revision": revision}, run_id=run)
        assert reply["ok"] is accepted
        if not accepted:
            assert reply["error"]["code"] in ("INVALID_STATE", "TIMEOUT")
            assert native_library.native_radio_transfers() == transfers
            assert node.request("status.get")["result"]["state"] == "idle"
            assert node.request("run.summary", run_id=run)["result"]["stop_reason"] == "timeout"
            assert not node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
    finally:
        node.close()


def test_prepared_work_expires_even_while_the_owner_lease_is_fresh(native_library):
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        run, _, _ = setup(node, sender=False, duration=3000)
        node.tick(3_000_000)
        node.drain()
        assert node.request("status.get")["result"]["state"] == "idle"
        assert node.request("artifact.list")["result"]["artifacts"] == []
        assert not node.allocations
        assert node.request("run.summary", run_id=run)["result"]["stop_reason"] == "timeout"
    finally:
        node.close()


@pytest.mark.parametrize("sender", [False, True])
def test_failed_radio_arm_or_start_retires_work_and_owned_security(native_library, sender):
    from test_protected_rf_execution_native import protected_setup

    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        run, revision = protected_setup(node, sender=sender)
        if sender:
            assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        native_library.native_radio_fail()
        reply = node.request(
            "run.start" if sender else "run.arm", {"config_revision": revision}, run_id=run
        )
        assert not reply["ok"]
        health = node.request("status.get")["result"]
        assert health["state"] == "idle" and health["run_id"] is None
        assert health["security_ready"] is False
        files = node.request("artifact.list")["result"]["artifacts"]
        assert all(file["state"] == "committed" for file in files)
        for file in files:
            node.request("artifact.delete", {"artifact_id": file["artifact_id"]})
        assert not node.allocations
    finally:
        node.close()


def test_cleanup_failure_remains_separate_from_operator_cancellation(native_library):
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        run, revision, _ = setup(node)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        native_library.native_radio_fail()
        node.request("run.stop", {"reason": "operator"}, run_id=run)
        summary = node.request("run.summary", run_id=run)["result"]
        assert summary["stop_reason"] == "operator"
        assert summary["cleanup_errors"] == ["RADIO_STOP_FAILED"]
    finally:
        node.close()


@pytest.mark.parametrize(
    "phase",
    ["sender_prepared", "receiver_prepared", "sender_armed", "receiver_armed", "sender_running"],
)
@pytest.mark.parametrize("cleanup", ["stop", "close", "lease", "disconnect"])
def test_each_owned_phase_cleans_keys_and_work_then_allows_a_new_session(
    native_library, phase, cleanup
):
    from test_protected_rf_execution_native import protected_setup

    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        sender = phase.startswith("sender")
        run, revision = protected_setup(node, sender=sender)
        if not phase.endswith("prepared"):
            assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        if phase.endswith("running"):
            assert node.request("run.start", {"config_revision": revision}, run_id=run)["ok"]
        if cleanup in ("stop", "close"):
            args = {"reason": "operator"} if cleanup == "stop" else {}
            assert node.request(
                "run.stop" if cleanup == "stop" else "session.close", args, run_id=run
            )["ok"]
        elif cleanup == "lease":
            node.tick(5_000_001)
            node.drain()
        else:
            node.lib.node_control_link(node.node, False)
            node.lib.node_control_link(node.node, True)
        if cleanup in ("lease", "disconnect"):
            node.claim()
        health = node.request("status.get")["result"]
        assert health["state"] == "idle" and health["security_ready"] is False
        if cleanup == "stop":
            assert node.request("session.close", run_id=run)["ok"]
        node.claim()
        files = node.request("artifact.list")["result"]["artifacts"]
        assert all(file["state"] == "committed" and not file["in_use"] for file in files)
        for file in files:
            assert node.request("artifact.delete", {"artifact_id": file["artifact_id"]})["ok"]
        assert not node.allocations
        new_run, _ = protected_setup(node, sender=sender)
        assert new_run != run
        assert node.request("status.get")["result"]["security_ready"] is True
        assert node.request("session.close", run_id=new_run)["ok"]
    finally:
        node.close()


def test_failed_encoded_prepare_releases_borrow_without_deleting_source(native_library):
    from test_codec_decode_native import encoded_source
    from test_codec_encode_native import readback
    from test_protected_voice_native import prepare_voice

    nodes = {
        "A": NativeNode(native_library, radio=native_library.native_radio_create()),
        "B": NativeNode(
            native_library, radio=native_library.native_radio_create(), device="esp-66778899aabb"
        ),
    }
    try:
        node = nodes["A"]
        node.claim()
        identifier, source = encoded_source(node)
        content = readback(node, identifier, source["length_bytes"])
        baseline = dict(node.allocations)
        node.allocation_fails = True
        run, _, error = prepare_voice(nodes, source, reject=True)
        node.allocation_fails = False
        assert error["code"] == "INTERNAL_ERROR"
        assert node.allocations == baseline
        manifest = next(
            file
            for file in node.request("artifact.list")["result"]["artifacts"]
            if file["artifact_id"] == identifier
        )
        assert manifest["state"] == "committed" and not manifest["in_use"]
        assert readback(node, identifier, source["length_bytes"]) == content
        assert node.request("session.close", run_id=run)["ok"]
    finally:
        for node in nodes.values():
            node.close()


def test_full_telemetry_queue_cannot_extend_the_receiver_resource_deadline(native_library):
    import ctypes as C
    import json

    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        run, revision, _ = setup(node, duration=3000)
        assert node.request("run.arm", {"config_revision": revision}, run_id=run)["ok"]
        malformed = b"x" * 41
        for _ in range(200):
            native_library.native_radio_inject(node.radio, malformed, len(malformed), 2)
            node.tick()  # Intentionally stop draining telemetry.
        node.time += 4_000_000
        command = node.command("control.keepalive")
        node.feed(json.dumps(command).encode() + b"\n")
        output = C.create_string_buffer(4096)
        length = node.lib.node_control_output(node.node, output, len(output))
        reply = json.loads(output.raw[:length])
        assert reply["kind"] == "reply" and reply["command_id"] == command["command_id"]
        assert reply["ok"]  # Keep owner fresh while telemetry remains queued.
        node.tick(4_000_000)
        node.drain()
        assert node.request("status.get")["result"]["state"] == "idle"
        assert not node.allocations
        summary = node.request("run.summary", run_id=run)["result"]
        assert summary["stop_reason"] == "timeout"
        assert "missing_range_evidence_incomplete" in summary["validity_reasons"]
    finally:
        node.close()
