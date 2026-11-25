"""Default-off laboratory hooks through the actual owned node command/radio path."""

import hashlib
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from test_echo_rtt_native import EchoPair
from test_node_control_native import NativeNode
from test_node_control_native import native_library as native_library
from test_secure_replay_native import KEY_A, KEY_B

from lora_testbed.experiments_v2 import KnownDataPlan, KnownDataSpec, Link, known_data, preview
from lora_testbed.fault_protocol_v2 import Injection


def injection(action="xor_byte", **changes):
    return Injection.model_validate(
        dict(
            injection_id=str(uuid4()),
            stage="tx_after_protect" if action == "xor_byte" else "tx_retained",
            action=action,
            message_id=1,
            fragment_index=0,
            attempt_index=1,
            byte_offset=40 if action == "xor_byte" else None,
            xor_mask=1 if action == "xor_byte" else None,
            block_size=None,
        )
        | changes
    ).model_dump()


class LabPair(EchoPair):
    def __init__(self, lib):
        super().__init__(lib, True, node_options={"lab_faults": True})

    def prepare(self, entry, *, start=True, direction="A_TO_B"):
        self.source, self.target = ("A", "B") if direction == "A_TO_B" else ("B", "A")
        self.plan = KnownDataPlan(
            link=Link(fragment_payload_bytes=64),
            spec=KnownDataSpec(
                message_count=1,
                message_bytes=32,
                security="aes128_gcm",
                max_duration_ms=10000,
                direction=direction,
            ),
        )
        budget = preview(self.plan)["timing"]["budget"]
        if entry["action"] == "replay":
            budget["fault_budget_us"] = 2000000
            budget["reassembly_timeout_us"] += 2000000
        for role, node, peer in (
            ("A", self.a, "esp-66778899aabb"),
            ("B", self.b, "esp-001122334455"),
        ):
            assert node.request("hello")["result"]["capabilities"]["fault_injection"]
            assert node.request("control.claim", {"node_role": role})["ok"]
            assert node.request(
                "session.open",
                dict(
                    session_id=self.session,
                    peer_device_id=peer,
                    peer_boot_id=peer + ":1",
                    security="aes128_gcm",
                    tx_key_hex=(KEY_A if role == "A" else KEY_B).hex(),
                    rx_key_hex=(KEY_B if role == "A" else KEY_A).hex(),
                ),
                run_id=self.run,
            )["ok"]
            configured = node.request(
                "config.set", dict(radio={}, link=self.plan.link.model_dump())
            )
            assert configured["ok"]
            self.revisions[role] = configured["result"]["config_revision"]
        configured = self.node(self.source).request(
            "fault.set", dict(injections=[entry], replace=True), run_id=self.run
        )
        assert configured["ok"], configured
        for role in "AB":
            prepared = self.node(role).request(
                "run.prepare",
                dict(spec=self.plan.spec.model_dump(), budget=budget),
                run_id=self.run,
            )
            assert prepared["ok"], prepared
            self.tick(role)
        if start:
            self.arm_and_start()

    def arm_and_start(self):
        for role in (self.target, self.source):
            assert self.node(role).request(
                "run.arm", dict(config_revision=self.revisions[role]), run_id=self.run
            )["ok"]
        assert self.node(self.source).request(
            "run.start", dict(config_revision=self.revisions[self.source]), run_id=self.run
        )["ok"]


def test_normal_image_does_not_advertise_laboratory_commands(native_library):
    node = NativeNode(native_library, radio=native_library.native_radio_create())
    try:
        capabilities = node.request("hello")["result"]["capabilities"]
        assert not capabilities["fault_injection"]
        assert not any(
            name.startswith("fault.")
            for name in capabilities["resource_limits"]["execution"]["commands"]
        )
    finally:
        node.close()


@pytest.mark.parametrize("direction", ["A_TO_B", "B_TO_A"])
@pytest.mark.parametrize("offset", [40, 87])
def test_actual_post_protect_fault_has_valid_radio_crc_and_rejects_authentication(
    native_library, offset, direction
):
    pair = LabPair(native_library)
    try:
        entry = injection(byte_offset=offset)
        pair.prepare(entry, direction=direction)
        changed = pair.sent(pair.source)
        valid = changed[:40] + AESGCM(KEY_A if pair.source == "A" else KEY_B).encrypt(
            changed[8:20], known_data(743, 1, 32), changed[:40]
        )
        assert changed != valid and changed[:40] == valid[:40]
        with pytest.raises(InvalidTag):
            AESGCM(KEY_A if pair.source == "A" else KEY_B).decrypt(
                changed[8:20], changed[40:], changed[:40]
            )
        pair.tx_done(pair.source)
        rejected = pair.inject(pair.target, changed)
        assert any(row.get("name") == "rx.frame" and row["data"]["crc_ok"] for row in rejected)
        assert any(
            row.get("name") == "rx.rejected" and row["data"]["reason"] == "authentication_failed"
            for row in rejected
        )
        applied = next(
            row["data"] for row in pair.events[pair.source] if row.get("name") == "fault.applied"
        )
        assert applied["injection_id"] == entry["injection_id"]
        assert applied["before_sha256"] == hashlib.sha256(valid).hexdigest()
        assert applied["after_sha256"] == hashlib.sha256(changed).hexdigest()
        delivered = pair.inject(pair.target, valid)
        assert (
            sum(
                row.get("name") == "message.result" and row["data"]["status"] == "delivered"
                for row in delivered
            )
            == 1
        )
    finally:
        pair.close()


@pytest.mark.parametrize("direction", ["A_TO_B", "B_TO_A"])
def test_actual_retained_replay_keeps_nonce_bytes_and_delivery_count(native_library, direction):
    pair = LabPair(native_library)
    try:
        entry = injection("replay")
        pair.prepare(entry, direction=direction)
        original = pair.sent(pair.source)
        pair.tx_done(pair.source)
        pair.inject(pair.target, original)
        assert pair.summary(pair.target)["delivered_messages"] == 1
        ready = pair.node(pair.source).request("fault.status", {}, run_id=pair.run)
        assert ready["ok"] and ready["result"]["entries"][0]["state"] == "retained"
        command = pair.node(pair.source).command(
            "fault.fire", dict(injection_id=entry["injection_id"]), run_id=pair.run
        )
        first = pair.node(pair.source).send(command)
        fired = next(row for row in first if row["kind"] == "reply")
        assert fired["ok"], fired
        repeated = pair.node(pair.source).send(command)
        assert next(row for row in repeated if row["kind"] == "reply") == fired
        assert pair.sent(pair.source) == original
        assert fired["result"]["sha256"] == hashlib.sha256(original).hexdigest()
        pair.tx_done(pair.source)
        rejected = pair.inject(pair.target, original)
        assert any(
            row.get("name") == "rx.rejected" and row["data"]["stage"] == "replay"
            for row in rejected
        )
        assert pair.summary(pair.target)["delivered_messages"] == 1
        assert sum(row.get("name") == "tx.attempt" for row in pair.events[pair.source]) == 1
        assert sum(row.get("name") == "fault.tx" for row in pair.events[pair.source]) == 1
        assert not pair.node(pair.source).request(
            "fault.fire", dict(injection_id=entry["injection_id"]), run_id=pair.run
        )["ok"]
    finally:
        pair.close()


@pytest.mark.parametrize(
    "change", [{"byte_offset": 88}, {"fragment_index": 1}, {"message_id": 2}, {"attempt_index": 2}]
)
def test_prepared_wrong_target_rejects_without_changing_armed_hook(native_library, change):
    pair = LabPair(native_library)
    try:
        original = injection()
        pair.prepare(original, start=False)
        bad = injection(**change)
        result = pair.a.request("fault.set", dict(injections=[bad], replace=True), run_id=pair.run)
        assert not result["ok"] and result["error"]["code"] == "INVALID_ARGUMENT"
        status = pair.a.request("fault.status", {}, run_id=pair.run)["result"]
        assert (
            status["count"] == 1
            and status["entries"][0]["injection_id"] == original["injection_id"]
        )
        assert status["entries"][0]["state"] == "planned"
        assert not pair.a.request(
            "fault.fire", dict(injection_id=original["injection_id"]), run_id=pair.run
        )["ok"]
    finally:
        pair.close()


def test_prepared_replay_cannot_exceed_reserved_budget_and_disable_restores_control(native_library):
    pair = LabPair(native_library)
    try:
        pair.prepare(injection(), start=False)
        bad = pair.a.request(
            "fault.set", dict(injections=[injection("replay")], replace=True), run_id=pair.run
        )
        assert not bad["ok"] and bad["error"]["code"] == "INVALID_ARGUMENT"
        assert pair.a.request("fault.set", dict(injections=[], replace=True), run_id=pair.run)["ok"]
        pair.arm_and_start()
        original = pair.sent("A")
        assert AESGCM(KEY_A).decrypt(original[8:20], original[40:], original[:40]) == known_data(
            743, 1, 32
        )
        pair.tx_done("A")
        delivered = pair.inject("B", original)
        assert (
            sum(
                row.get("name") == "message.result" and row["data"]["status"] == "delivered"
                for row in delivered
            )
            == 1
        )
        assert not any(row.get("name") == "fault.applied" for row in pair.events["A"])
    finally:
        pair.close()


@pytest.mark.parametrize("cleanup", ["stop", "lease", "disconnect"])
def test_lab_hooks_retire_with_operation_or_owner_and_old_run_cannot_fire(native_library, cleanup):
    pair = LabPair(native_library)
    try:
        entry = injection("replay")
        pair.prepare(entry, start=False)
        if cleanup == "stop":
            assert pair.a.request("run.stop", dict(reason="operator"), run_id=pair.run)["ok"]
        elif cleanup == "lease":
            pair.tick("A", 5000001)
        else:
            native_library.node_control_link(pair.a.node, False)
            native_library.node_control_link(pair.a.node, True)
        if cleanup != "stop":
            pair.a.claim()
        status = pair.a.request("status.get")["result"]
        assert status["state"] == "idle" and not status["security_ready"]
        assert not pair.a.request(
            "fault.fire", dict(injection_id=entry["injection_id"]), run_id=pair.run
        )["ok"]
        report = pair.a.request("fault.status", {}, run_id=pair.run)
        if cleanup == "stop":
            assert report["ok"] and report["result"]["entries"][0]["state"] == "disabled"
        else:
            assert not report["ok"]
        assert not pair.a.request(
            "run.start", dict(config_revision=pair.revisions["A"]), run_id=pair.run
        )["ok"]
    finally:
        pair.close()


def test_lab_and_all_other_peripherals_keep_hello_health_and_status_within_record_limit(
    native_library,
):
    from test_node_audio_native import AudioFixture

    audio = AudioFixture()
    node = NativeNode(
        native_library,
        radio=native_library.native_radio_create(),
        audio=audio.port,
        ptt=lambda _: False,
        display=lambda *_: True,
        display_status=lambda _: 1,
        boot=4294967295,
        lab_faults=True,
    )
    try:
        node.time = 123456789000000
        hello = node.request("hello")["result"]
        assert hello["capabilities"]["fault_injection"]
        node.claim()
        assert not node.request("audio.capture", dict(artifact_id="invalid", sample_count=160))[
            "ok"
        ]
        assert node.request("status.get")["ok"]
        node.tick(1000000)
        assert any(row.get("name") == "health" for row in node.drain())
    finally:
        node.close()


def test_host_serial_profile_exercises_lab_commands_and_retains_nonsecret_events(native_library):
    import asyncio
    import json

    from test_node_control_native import NativeSerial

    from lora_testbed.nodes import NodeSession

    async def scenario():
        serial = NativeSerial(
            native_library, radio=native_library.native_radio_create(), lab_faults=True
        )
        observations = []
        node = NodeSession("A", lambda *args: observations.append(args), lambda _: serial)
        wire = []
        run = str(uuid4())
        try:
            await node.connect("isolated-lab-faults")
            assert node.identity.capabilities.fault_injection
            await node.request(
                "session.open",
                dict(
                    session_id="0102030405060708",
                    peer_device_id="esp-66778899aabb",
                    peer_boot_id="esp-66778899aabb:1",
                    security="aes128_gcm",
                    tx_key_hex=KEY_A.hex(),
                    rx_key_hex=KEY_B.hex(),
                ),
                run_id=run,
                on_record=wire.append,
            )
            entry = injection()
            assert (
                await node.request("fault.set", dict(injections=[entry], replace=True), run_id=run)
            )["count"] == 1
            report = await node.request("fault.status", {}, run_id=run)
            assert report["count"] == 1 and report["entries"][0]["state"] == "planned"
            plan = KnownDataPlan(
                link=Link(fragment_payload_bytes=64),
                spec=KnownDataSpec(
                    message_count=1, message_bytes=32, security="aes128_gcm", max_duration_ms=10000
                ),
            )
            config = await node.request("config.set", dict(radio={}, link=plan.link.model_dump()))
            prepared = await node.request(
                "run.prepare",
                dict(spec=plan.spec.model_dump(), budget=preview(plan)["timing"]["budget"]),
                run_id=run,
            )
            async with asyncio.timeout(2):
                while not any(
                    row["operation_id"] == prepared["operation_id"]
                    for row in node.operation_results
                ):
                    await asyncio.sleep(0.005)
            await node.request(
                "run.arm", dict(config_revision=config["config_revision"]), run_id=run
            )
            await node.request(
                "run.start", dict(config_revision=config["config_revision"]), run_id=run
            )
            with serial.lock:
                native_library.native_radio_tx_done(serial.core.radio)
            async with asyncio.timeout(2):
                while not any(
                    len(row) == 2
                    and isinstance(row[1], dict)
                    and row[1].get("name") == "fault.applied"
                    for row in observations
                ):
                    await asyncio.sleep(0.005)
            report = await node.request("fault.status", {}, run_id=run)
            assert report["entries"][0]["state"] == "applied"
            assert not node.event_gaps and not node.framing_errors
            serialized = json.dumps(wire)
            assert KEY_A.hex() not in serialized and KEY_B.hex() not in serialized
        finally:
            await node.close()

    asyncio.run(scenario())


def test_fault_status_paginates_all_configured_targets_without_arming_radio(native_library):
    pair = LabPair(native_library)
    try:
        pair.prepare(injection(), start=False)
        for start in range(0, 32, 8):
            rows = [injection(byte_offset=40 + i) for i in range(start, start + 8)]
            result = pair.a.request(
                "fault.set", dict(injections=rows, replace=start == 0), run_id=pair.run
            )
            assert result["ok"] and result["result"]["count"] == start + 8
        seen = []
        for offset in range(0, 32, 4):
            result = pair.a.request("fault.status", dict(offset=offset, limit=4), run_id=pair.run)
            assert result["ok"]
            report = result["result"]
            assert report["count"] == 32 and len(report["entries"]) == 4
            assert report["next_offset"] == offset + 4 and report["eof"] == (offset == 28)
            seen.extend(row["injection_id"] for row in report["entries"])
        assert len(set(seen)) == 32
        overflow = pair.a.request(
            "fault.set",
            dict(injections=[injection(byte_offset=72)], replace=False),
            run_id=pair.run,
        )
        assert not overflow["ok"] and overflow["error"]["code"] == "RESOURCE_LIMIT"
    finally:
        pair.close()


def test_unfired_retained_target_expires_with_null_application_and_wiped_wire(native_library):
    pair = LabPair(native_library)
    try:
        entry = injection("replay")
        pair.prepare(entry)
        original = pair.sent("A")
        pair.tx_done("A")
        pair.inject("B", original)
        pair.tick("A", 4000001)
        report = pair.a.request("fault.status", {}, run_id=pair.run)
        assert report["ok"] and not report["result"]["fire_window_open"]
        row = report["result"]["entries"][0]
        assert row["state"] == "missed" and row["applied_us"] is None
        assert all(original not in value.raw for value in pair.a.allocations.values())
        assert not pair.a.request(
            "fault.fire", dict(injection_id=entry["injection_id"]), run_id=pair.run
        )["ok"]
        assert not any(event.get("name") == "fault.tx" for event in pair.events["A"])
    finally:
        pair.close()


def test_duplicate_configuration_is_idempotent_and_conflicting_retry_keeps_target(native_library):
    from copy import deepcopy

    pair = LabPair(native_library)
    try:
        pair.prepare(injection(), start=False)
        entry = injection(byte_offset=41)
        command = pair.a.command(
            "fault.set", dict(injections=[entry], replace=True), run_id=pair.run
        )
        original = next(row for row in pair.a.send(command) if row["kind"] == "reply")
        assert original["ok"]
        assert next(row for row in pair.a.send(command) if row["kind"] == "reply") == original
        conflict = deepcopy(command)
        conflict["args"]["injections"] = [injection(byte_offset=42)]
        rejected = next(row for row in pair.a.send(conflict) if row["kind"] == "reply")
        assert not rejected["ok"] and rejected["error"]["code"] == "COMMAND_CONFLICT"
        report = pair.a.request("fault.status", {}, run_id=pair.run)["result"]
        assert (
            report["count"] == 1 and report["entries"][0]["injection_id"] == entry["injection_id"]
        )
    finally:
        pair.close()


def test_fault_owner_allocation_failure_can_close_and_recover_fresh_session(native_library):
    from test_protected_rf_execution_native import protected_setup

    node = NativeNode(native_library, radio=native_library.native_radio_create(), lab_faults=True)
    run = str(uuid4())
    try:
        node.claim()
        node.allocation_fails = True
        result = node.request(
            "session.open",
            dict(
                session_id="0302030405060708",
                peer_device_id="esp-66778899aabb",
                peer_boot_id="esp-66778899aabb:1",
                security="aes128_gcm",
                tx_key_hex=KEY_A.hex(),
                rx_key_hex=KEY_B.hex(),
            ),
            run_id=run,
        )
        assert not result["ok"] and not node.allocations
        node.allocation_fails = False
        assert not node.request("status.get")["result"]["security_ready"]
        assert node.request("session.close", run_id=run)["ok"]
        fresh, revision = protected_setup(node, sender=True)
        assert node.request("fault.status", {}, run_id=fresh)["result"]["count"] == 0
        assert node.request("run.arm", dict(config_revision=revision), run_id=fresh)["ok"]
        assert node.request("run.start", dict(config_revision=revision), run_id=fresh)["ok"]
        for advance in (1000, 50000, 1000):
            native_library.native_radio_tx_done(node.radio)
            node.tick(advance)
            node.drain()
        assert node.request("run.summary", run_id=fresh)["result"]["stop_reason"] == "completed"
    finally:
        node.close()
