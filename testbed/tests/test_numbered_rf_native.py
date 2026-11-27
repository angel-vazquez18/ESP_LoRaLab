"""Exercise bounded, separately observed finite messages under one protected session."""

import base64
from hashlib import sha256

import pytest
from test_lab_fault_commands_native import LabPair, injection
from test_node_control_native import native_library as native_library

from lora_testbed.experiments_v2 import Link, known_data, preview
from lora_testbed.run_protocol_v2 import Prepare


def retire_message(pair, role, expected):
    node = pair.node(role)
    artifacts = node.request("artifact.list")["result"]["artifacts"]
    if expected is None:
        assert artifacts == []
        return
    [artifact] = artifacts
    assert artifact["sha256"] == sha256(expected).hexdigest()
    contents = bytearray()
    for offset in range(0, len(expected), 1024):
        reply = node.request(
            "artifact.get",
            {"artifact_id": artifact["artifact_id"], "offset": offset, "length_bytes": 1024},
        )
        assert reply["ok"], reply
        contents.extend(base64.b64decode(reply["result"]["data_b64"]))
    assert contents == expected
    assert node.request("artifact.delete", {"artifact_id": artifact["artifact_id"]})["ok"]


@pytest.mark.parametrize("direction", ["A_TO_B", "B_TO_A"])
@pytest.mark.parametrize("capacity", [16, 64, 160, 199])
def test_ten_numbered_messages_retain_key_and_sequences_across_a_drop(
    native_library, direction, capacity
):
    pair = LabPair(native_library)
    try:
        length = 1200
        count = (length + capacity - 1) // capacity
        pair.prepare(
            None,
            start=False,
            direction=direction,
            numbered=True,
            byte_count=length,
            timeout_ms=30000,
            link=Link(fragment_payload_bytes=capacity),
        )
        spec = pair.plan.spec.model_dump()
        budget = preview(pair.plan)["timing"]["budget"]
        target = pair.node(pair.target)
        retained = None
        app_results = []
        for number in range(1, 11):
            for role in "AB":
                assert pair.node(role).request("control.keepalive")["ok"]
            if number > 1:
                args = Prepare(spec=spec, budget=budget, message_id=number).model_dump()
                if number in (3, 4):
                    entries = (
                        [injection("drop", fragment_index=count // 2, message_id=number)]
                        if number == 3
                        else []
                    )
                    assert target.request(
                        "fault.set", {"injections": entries, "replace": True}, run_id=pair.run
                    )["ok"]
                for role in "AB":
                    node = pair.node(role)
                    if number == 2:
                        for invalid in (dict(args, message_id=1), dict(args, message_id=3)):
                            assert (
                                node.request("run.prepare", invalid, run_id=pair.run)["error"][
                                    "code"
                                ]
                                == "INVALID_STATE"
                            )
                    prepared = node.request("run.prepare", args, run_id=pair.run)
                    assert prepared["ok"], prepared
                    records = pair.tick(role)
                    assert any(
                        row.get("name") == "run.prepared" and row["data"]["message_id"] == number
                        for row in records
                    )

            pair.arm_and_start()
            if number == 2:
                records = pair.inject(pair.target, retained)
                assert any(
                    row.get("name") == "rx.rejected" and row["data"]["reason"] == "replay"
                    for row in records
                )

            for index in range(count):
                data = pair.sent(pair.source)
                assert int.from_bytes(data[16:20], "big") == (number - 1) * count + index + 1
                assert int.from_bytes(data[20:24], "big") == number
                assert int.from_bytes(data[24:26], "big") == index
                if number == 1 and index == 0:
                    retained = data
                pair.tx_done(pair.source)
                records = pair.inject(pair.target, data)
                app_results.extend(
                    row["data"]["message_id"]
                    for row in records
                    if row.get("name") == "message.result" and row["data"]["status"] == "delivered"
                )
                pair.tick(pair.source, 50001)

            if number == 3:
                for _ in range(400):
                    rows = target.send(target.command("control.keepalive"))
                    assert next(row for row in rows if row["kind"] == "reply")["ok"]
                    pair.events[pair.target].extend(rows)
                    pair.tick(pair.target, 100_000)
                    if any(
                        row.get("name") == "run.summary" and row["data"]["message_id"] == number
                        for row in pair.events[pair.target]
                    ):
                        break
                missing = [
                    row["data"]["ranges"]
                    for row in pair.events[pair.target]
                    if row.get("name") == "message.missing" and row["data"]["message_id"] == number
                ]
                assert missing == [[[count // 2, count // 2]]], pair.summary(pair.target)

            summary = pair.summary(pair.target)
            assert summary["message_id"] == number and summary["session_id"] == pair.session
            assert summary["stop_reason"] == ("timeout" if number == 3 else "completed")
            assert summary["delivered_messages"] == int(number != 3)
            assert pair.summary(pair.source)["original_packets"] == count
            for role in "AB":
                node = pair.node(role)
                assert node.request("status.get")["result"]["security_ready"]
                if number == 1:
                    assert (
                        node.request(
                            "run.prepare",
                            dict(spec=spec, budget=budget, message_id=2),
                            run_id=pair.run,
                        )["error"]["code"]
                        == "INVALID_STATE"
                    )
                expected = (
                    None if role == pair.target and number == 3 else known_data(743, number, length)
                )
                retire_message(pair, role, expected)

        assert app_results == [1, 2, 4, 5, 6, 7, 8, 9, 10]
        for role in "AB":
            node = pair.node(role)
            assert node.request("session.close", run_id=pair.run)["ok"]
            assert not node.request("status.get")["result"]["security_ready"]
            assert (
                node.request(
                    "run.prepare",
                    Prepare(spec=spec, budget=budget, message_id=11).model_dump(),
                    run_id=pair.run,
                )["error"]["code"]
                == "INVALID_STATE"
            )
    finally:
        pair.close()
