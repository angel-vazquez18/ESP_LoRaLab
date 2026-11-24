"""Local public-vector measurements through the same C serial seam as firmware."""

import pytest
from test_node_control_native import NativeNode
from test_node_control_native import native_library as native_library


def test_crypto_benchmark_accepts_a_single_node_without_radio_or_private_keys(native_library):
    node = NativeNode(native_library)
    try:
        node.claim()
        hello = node.request()["result"]
        assert "crypto_benchmark" in hello["capabilities"]["resource_limits"]["diag_kinds"]
        accepted = node.request(
            "diag.run", {"kind": "crypto_benchmark", "iterations": 1000, "payload_bytes": 16}
        )
        assert accepted["ok"], accepted
    finally:
        node.close()


def collect(node, limit=4000):
    records = []
    for _ in range(limit):
        node.tick()
        records.extend(node.drain())
        if any(r.get("name") == "operation.result" for r in records):
            return records
    pytest.fail("Bounded benchmark did not produce a terminal record")


@pytest.mark.parametrize("size", [16, 64, 160, 199])
def test_all_public_sizes_have_separate_checked_first_warmup_and_1000_timed_samples(
    native_library, size
):
    from lora_testbed.crypto_benchmark_v2 import assess

    node = NativeNode(native_library, realtime=True)
    try:
        node.claim()
        assert node.request(
            "diag.run", {"kind": "crypto_benchmark", "iterations": 1000, "payload_bytes": size}
        )["ok"]
        records = collect(node)
        terminal = next(r for r in records if r.get("name") == "operation.result")
        assert terminal["data"]["status"] == "completed", terminal
        assessment = assess(records)
        assert assessment["complete"], assessment
        assert assessment["checked_samples"] == 4204
        assert set(assessment["timed"]) == {"encrypt", "decrypt", "invalid_tag", "copy"}
        for path in assessment["timed"].values():
            assert len(path) == 1000 and all(t >= 0 for t in path)
        assert not node.request("status.get")["result"]["security_ready"]
    finally:
        node.close()


def test_cancelled_and_missing_page_results_never_produce_a_distribution(native_library):
    from copy import deepcopy

    from lora_testbed.crypto_benchmark_v2 import assess

    node = NativeNode(native_library)
    try:
        node.claim()
        accepted = node.request(
            "diag.run", {"kind": "crypto_benchmark", "iterations": 1000, "payload_bytes": 160}
        )["result"]
        node.tick()
        records = node.drain()
        records += node.send(
            node.command("operation.stop", {"operation_id": accepted["operation_id"]})
        )
        terminal = next(r for r in records if r.get("name") == "operation.result")
        assert terminal["data"]["status"] == "cancelled"
        assert terminal["data"]["result"]["checked_counts"]["encrypt"]["first_call"] == 1
        assert not terminal["data"]["result"]["checked_complete"]
        assert not assess(records)["complete"] and not assess(records)["timed"]
        assert node.request(
            "diag.run", {"kind": "crypto_benchmark", "iterations": 2, "payload_bytes": 64}
        )["ok"]
        complete = collect(node)
        assert assess(complete)["complete"]
        missing = deepcopy(complete)
        missing.pop(next(i for i, r in enumerate(missing) if r.get("name") == "crypto.benchmark"))
        assert not assess(missing)["complete"] and not assess(missing)["timed"]
        duplicate = deepcopy(complete)
        duplicate.insert(0, duplicate[0])
        assert not assess(duplicate)["complete"]
    finally:
        node.close()


def test_api_starts_same_benchmark_and_returns_retained_checked_evidence(native_library, tmp_path):
    import time

    from fastapi.testclient import TestClient
    from test_node_control_native import NativeSerial

    from lora_testbed.app import create_app

    serial = NativeSerial(native_library)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        host = client.app.state.host
        host.physical["A"].opener = lambda _: serial
        client.portal.call(host.physical["A"].connect, "isolated-native-core")
        response = client.post(
            "/api/nodes/A/crypto-benchmark", json={"iterations": 2, "payload_bytes": 199}
        )
        assert response.status_code == 200, response.text
        identifier = response.json()["operation_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            evidence = client.get(
                f"/api/nodes/A/crypto-benchmark/{identifier}?include_records=true"
            )
            assert evidence.status_code == 200, evidence.text
            if evidence.json()["assessment"]["complete"]:
                break
            time.sleep(0.01)
        assert evidence.json()["assessment"]["complete"], evidence.text
        assert evidence.json()["assessment"]["checked_samples"] == 212
        assert any(r["name"] == "crypto.benchmark" for r in evidence.json()["records"])
        assert (
            client.post("/api/nodes/A/crypto-benchmark", json={"payload_bytes": 200}).status_code
            == 422
        )
    assert serial.closed


@pytest.mark.parametrize("ending", ["lease", "disconnect", "reset", "timeout"])
def test_owner_loss_deadline_and_pressure_clean_up_without_inventing_full_counts(
    native_library, ending
):
    from lora_testbed.crypto_benchmark_v2 import assess

    node = NativeNode(native_library)
    try:
        node.claim()
        assert node.request(
            "diag.run", {"kind": "crypto_benchmark", "iterations": 10000, "payload_bytes": 199}
        )["ok"]
        # Fill the bounded writer queue without draining it. Measurement then pauses.
        for _ in range(40):
            node.tick()
        if ending == "reset":
            node.close()
            node = NativeNode(native_library, boot=2)
            node.claim()
        elif ending == "disconnect":
            node.lib.node_control_link(node.node, False)
            node.lib.node_control_link(node.node, True)
            node.claim()
        elif ending == "lease":
            node.tick(5000001)
            records = node.drain()
            assert not assess(records)["complete"]
            node.claim()
        else:
            records = node.drain()
            # Keep the owner alive while the finite operation deadline expires.
            for _ in range(31):
                node.request("control.keepalive")
                node.tick(1000000)
                records += node.drain()
            terminal = next(r for r in records if r.get("name") == "operation.result")
            assert terminal["data"]["status"] == "failed"
            assert terminal["data"]["error"]["code"] == "TIMEOUT"
            assert not terminal["data"]["result"]["checked_complete"]
            assert not assess(records)["complete"] and not assess(records)["timed"]
        assert node.request("status.get")["result"]["state"] == "idle"
        assert node.request(
            "diag.run", {"kind": "crypto_benchmark", "iterations": 1, "payload_bytes": 16}
        )["ok"]
        assert assess(collect(node))["complete"]
    finally:
        node.close()


def test_regressing_timer_is_a_checked_failure_with_partial_counts(native_library):
    node = NativeNode(native_library)
    try:
        node.claim()
        assert node.request(
            "diag.run", {"kind": "crypto_benchmark", "iterations": 1, "payload_bytes": 64}
        )["ok"]
        calls = 0

        def broken_clock():
            nonlocal calls
            calls += 1
            return 1000100 - (calls == 4)

        node.now = broken_clock
        terminal = next(r for r in collect(node) if r.get("name") == "operation.result")
        assert terminal["data"]["status"] == "failed"
        assert terminal["data"]["result"]["checked_counts"]["encrypt"]["first_call"] == 0
        assert not terminal["data"]["result"]["checked_complete"]
    finally:
        node.close()


def test_repeated_cancel_releases_actual_crypto_key_slots(native_library):
    node = NativeNode(native_library)
    try:
        node.claim()
        for _ in range(80):
            reply = node.request(
                "diag.run", {"kind": "crypto_benchmark", "iterations": 1000, "payload_bytes": 199}
            )
            assert reply["ok"]
            node.tick()
            node.drain()
            records = node.send(
                node.command("operation.stop", {"operation_id": reply["result"]["operation_id"]})
            )
            terminal = next(r for r in records if r.get("name") == "operation.result")
            assert terminal["data"]["status"] == "cancelled"
        assert node.request("status.get")["result"]["state"] == "idle"
    finally:
        node.close()


@pytest.mark.parametrize("size", [16, 64, 160, 199])
def test_public_benchmark_vector_matches_independent_crypto_oracle(size):
    import json

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from lora_testbed.paths import REPOSITORY_ROOT

    fixture = json.loads(
        (REPOSITORY_ROOT / "contracts/v2/crypto_benchmark_vectors.json").read_text()
    )
    vector = next(v for v in fixture["vectors"] if v["payload_bytes"] == size)
    header = bytes.fromhex(vector["header_hex"])
    plain = bytes.fromhex(vector["plaintext_hex"])
    assert len(header) == 40 and len(plain) == size
    encrypted = AESGCM(bytes.fromhex(fixture["key_hex"])).encrypt(header[8:20], plain, header)
    assert encrypted.hex() == vector["protected_hex"]
