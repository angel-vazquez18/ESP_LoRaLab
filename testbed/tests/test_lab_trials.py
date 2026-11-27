"""The public lab trial uses real host orchestration and isolated C/radio fixtures."""

import asyncio
from copy import deepcopy

import pytest
from test_lab_fault_commands_native import injection
from test_multi_fragment_radio import Pair
from test_node_control_native import native_library as native_library

from lora_testbed import fault_accounting
from lora_testbed.experiments_v2 import Link, known_data
from lora_testbed.host import Host
from lora_testbed.radio_runs import LabRadioRunRequest


def trial(action, retries=0):
    ack = "stop_wait" if retries or action == "drop_ack" else "none"
    return LabRadioRunRequest(
        injection=injection(
            action, fragment_index=1, block_size=3 if action == "reverse_block" else None
        ),
        direction="B_TO_A",
        security="aes128_gcm",
        message_bytes=81,
        link=Link(fragment_payload_bytes=16, ack_mode=ack, max_retries=retries),
    )


@pytest.mark.parametrize(
    "action,retries",
    [
        ("xor_byte", 0),
        ("replay", 0),
        ("drop", 0),
        ("drop", 1),
        ("drop_ack", 1),
        ("duplicate", 0),
        ("reverse_block", 0),
    ],
)
def test_trial_matches_confirmed_fault_and_fresh_intact_controls(
    tmp_path, native_library, action, retries
):
    async def scenario():
        host = Host(tmp_path)
        pair = Pair(host, native_library, lab=True)
        bridge = None
        try:
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            requested = trial(action, retries)
            assert host.radio_preflight(requested)["ready"]
            record = await host.start_lab_trial(requested)
            with pytest.raises(RuntimeError, match="owns"):
                await host.start_radio(requested.control())
            async with asyncio.timeout(30):
                await host.lab_trials.task
            saved = host.lab_trials.get(record["id"])
            children = {k: host.radio.get(v) for k, v in saved["children"].items()}
            assert saved["status"] == "completed", (saved, [r["error"] for r in children.values()])
            assert saved["outcome"] == "pass", (saved, [r["error"] for r in children.values()])
            assert not saved["hardware_qualified"]
            assert set(children) == {"before", "fault", "after"}
            assert len({r["session_id"] for r in children.values()}) == 3
            assert all(child["cleanup"]["confirmed"] for child in children.values())
            assert not host.busy
            if action == "duplicate":
                duplicated = deepcopy(children["fault"])
                matching = next(
                    row
                    for row in duplicated["events"]
                    if row["name"] == "rx.frame" and row["data"]["fragment_index"] == 1
                )
                duplicated["events"].append(matching)
                outcome = fault_accounting.assess(duplicated, known_data(743, 1, 81))
                assert outcome["outcome"] == "inconclusive"
                assert any(
                    row["code"] == "exactly_one_rejected_duplicate_after_insertion"
                    and row["outcome"] == "inconclusive"
                    for row in outcome["checks"]
                )
            if action == "reverse_block":
                changed = deepcopy(children["fault"])
                receive_indexes = [
                    i
                    for i, row in enumerate(changed["events"])
                    if row["role"] == changed["receiver"] and row["name"] == "rx.frame"
                ]
                first, second = receive_indexes[:2]
                changed["events"][first], changed["events"][second] = (
                    changed["events"][second],
                    changed["events"][first],
                )
                outcome = fault_accounting.assess(changed, known_data(743, 1, 81))
                assert outcome["outcome"] == "inconclusive"
                assert any(
                    row["code"] == "complete_reversed_block" and row["outcome"] == "inconclusive"
                    for row in outcome["checks"]
                )
            if action == "xor_byte":
                assert children["fault"]["available_content"] == ["source", "wire"]
                rejected = deepcopy(children["fault"])
                for row in rejected["events"]:
                    if row["name"] == "rx.frame":
                        row["data"]["crc_ok"] = False
                assessment = fault_accounting.assess(rejected, known_data(743, 1, 81))
                assert assessment["outcome"] == "inconclusive"
                assert any(
                    row["code"] == "matching_crc_valid_arrival" and row["outcome"] == "inconclusive"
                    for row in assessment["checks"]
                )
                missing = deepcopy(children["fault"])
                missing["events"] = [e for e in missing["events"] if e["name"] != "rx.rejected"]
                assert fault_accounting.assess(missing, known_data(743, 1, 81))["outcome"] == (
                    "inconclusive"
                )
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())


def test_standard_firmware_cannot_reserve_or_configure_a_lab_trial(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        try:
            pair = Pair(host, native_library)
            await pair.connect()
            preflight = host.radio_preflight(trial("drop"))
            assert not preflight["ready"]
            assert all(any(role in reason for reason in preflight["blockers"]) for role in "AB")
            with pytest.raises(ValueError, match="lab firmware"):
                await host.start_lab_trial(trial("drop"))
            assert not host.busy and not host.radio.snapshot()["runs"]
        finally:
            await host.close()

    asyncio.run(scenario())


def test_stop_whole_trial_prevents_later_frames(tmp_path, native_library):
    async def scenario():
        host = Host(tmp_path)
        try:
            pair = Pair(host, native_library, lab=True)
            await pair.connect()
            record = await host.start_lab_trial(trial("replay"))
            stopped = await host.lab_trials.stop(record["id"])
            assert stopped["status"] == "cancelled"
            assert not set(stopped["children"]) & {"fault", "after"}
            assert not host.busy
            assert all(not node.rf_run_id for node in host.physical.values())
        finally:
            await host.close()

    asyncio.run(scenario())


def test_lab_http_preflight_and_saved_list_use_shared_service(tmp_path):
    from fastapi.testclient import TestClient

    from lora_testbed.app import create_app

    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/api/lab/preflight", json=trial("duplicate").model_dump())
        assert response.status_code == 200
        assert response.json()["ready"] is False
        assert (
            client.post("/api/lab/trials", json=trial("duplicate").model_dump()).status_code == 400
        )
        assert client.get("/api/lab/trials").json() == {"active_id": None, "trials": []}
