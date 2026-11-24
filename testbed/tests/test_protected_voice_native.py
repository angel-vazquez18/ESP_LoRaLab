"""Committed Codec 2 bytes use actual protected transport and explicit local audio."""

import ctypes as C
import hashlib
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from test_codec_decode_native import decode, encoded_source
from test_codec_encode_native import readback
from test_node_audio_native import AudioFixture
from test_node_control_native import AudioProgress, NativeNode
from test_node_control_native import native_library as native_library
from test_protected_rf_execution_native import sent
from test_secure_replay_native import KEY_A, KEY_B

from lora_testbed.experiments_v2 import KnownDataPlan, KnownDataSpec, Link, preview


def prepare_voice(
    nodes,
    source,
    receiver_sha=None,
    ack=False,
    direction="A_TO_B",
    overrides=None,
    reject=False,
    omit=(),
):
    run = str(uuid4())
    link = Link(guard_us=0, ack_mode="stop_wait" if ack else "none", max_retries=2 if ack else 0)
    plan = KnownDataPlan(
        link=link,
        spec=KnownDataSpec(
            message_count=1,
            direction=direction,
            message_bytes=source["length_bytes"],
            security="aes128_gcm",
            max_duration_ms=30000,
        ),
    )
    spec = plan.spec.model_dump()
    spec.update(
        catalog_id="VOICE-02",
        source="encoded_source",
        source_seed=None,
        source_artifact_id=source["artifact_id"],
        sample_count=source["sample_count"],
        expected_sha256=source["sha256"],
    )
    budget = preview(plan)["timing"]["budget"]
    budget["processing_budget_us"] += 5000000
    budget["reassembly_timeout_us"] += 5000000
    revisions, reservations = {}, {}
    for role, node in nodes.items():
        assert node.request("control.claim", {"node_role": role})["ok"]
        peer = nodes["B" if role == "A" else "A"]
        assert node.request(
            "session.open",
            {
                "session_id": "0102030405060708",
                "peer_device_id": peer.platform.device_id.decode(),
                "peer_boot_id": peer.boot_id,
                "security": "aes128_gcm",
                "tx_key_hex": (KEY_A if role == "A" else KEY_B).hex(),
                "rx_key_hex": (KEY_B if role == "A" else KEY_A).hex(),
            },
            run_id=run,
        )["ok"]
        applied = node.request("config.set", {"radio": {}, "link": link.model_dump()})
        assert applied["ok"]
        revisions[role] = applied["result"]["config_revision"]
        selected = (
            {**spec, "expected_sha256": receiver_sha}
            if role == ("B" if direction == "A_TO_B" else "A") and receiver_sha
            else spec
        )
        if overrides:
            selected = {**selected, **overrides}
        selected = {key: value for key, value in selected.items() if key not in omit}
        prepared = node.request("run.prepare", {"spec": selected, "budget": budget}, run_id=run)
        if reject:
            assert not prepared["ok"]
            return run, revisions, prepared["error"]
        from lora_testbed.run_protocol_v2 import Prepare

        Prepare.model_validate({"spec": selected, "budget": budget})
        assert prepared["ok"], prepared.get("error")
        node.tick()
        reservations[role] = next(
            row["data"]["result"] for row in node.drain() if row.get("name") == "operation.result"
        )
    return run, revisions, reservations


def test_committed_clip_delivers_eight_authenticated_fragments_then_decodes_and_plays(
    native_library,
):
    lib = native_library
    audio = AudioFixture()
    nodes = {
        "A": NativeNode(lib, radio=lib.native_radio_create()),
        "B": NativeNode(
            lib, radio=lib.native_radio_create(), device="esp-66778899aabb", audio=audio.port
        ),
    }
    try:
        nodes["A"].claim()
        identifier, source = encoded_source(nodes["A"])
        encoded = readback(nodes["A"], identifier, 1200)
        run, revision, _ = prepare_voice(nodes, source)
        assert nodes["B"].request("run.arm", {"config_revision": revision["B"]}, run_id=run)["ok"]
        assert nodes["A"].request("run.arm", {"config_revision": revision["A"]}, run_id=run)["ok"]
        assert nodes["A"].request("run.start", {"config_revision": revision["A"]}, run_id=run)["ok"]
        plaintext = bytearray()
        records = []
        for index in range(8):
            raw = sent(nodes["A"])
            assert raw[3] == 1 and raw[4] == 1 and raw[7] == 1
            assert int.from_bytes(raw[24:26], "big") == index
            assert int.from_bytes(raw[26:28], "big") == 8
            plaintext.extend(AESGCM(KEY_A).decrypt(raw[8:20], raw[40:], raw[:40]))
            lib.native_radio_inject(nodes["B"].radio, raw, len(raw), 2)
            nodes["B"].tick(1000)
            records.extend(nodes["B"].drain())
            assert audio.starts == 0
            lib.native_radio_tx_done(nodes["A"].radio)
            nodes["A"].tick(1000)
            nodes["A"].drain()
            nodes["A"].tick(1000)
            nodes["A"].drain()
        assert bytes(plaintext) == encoded
        assert (
            sum(
                row.get("name") == "message.result" and row["data"]["status"] == "delivered"
                for row in records
            )
            == 1
        )
        files = nodes["B"].request("artifact.list")["result"]["artifacts"]
        recovered = next(file for file in files if file["format"] == "codec2_3200_v1")
        assert recovered["kind"] == "recovered" and recovered["sample_count"] == 24000
        assert recovered["source_artifact_id"] == identifier and recovered["frame_count"] == 150
        assert readback(nodes["B"], recovered["artifact_id"], 1200) == encoded
        assert recovered["sha256"] == hashlib.sha256(encoded).hexdigest()
        decoded, terminal = decode(nodes["B"], recovered["artifact_id"])
        assert (
            terminal["status"] == "completed" and terminal["result"]["samples_completed"] == 24000
        )
        assert audio.starts == 0
        played = nodes["B"].request("audio.play", {"artifact_id": decoded})
        assert played["ok"] and audio.starts == 1
        audio.progress = AudioProgress(24000, 24000, 0, True, False)
        nodes["B"].tick()
        result = next(
            row["data"] for row in nodes["B"].drain() if row.get("name") == "operation.result"
        )
        assert result["status"] == "completed" and result["result"]["underflows"] == 0
        assert not result["result"]["heard_verified"]
    finally:
        for node in nodes.values():
            node.close()


@pytest.mark.parametrize("fault", ["drop", "tamper", "hash"])
def test_incomplete_or_unverified_voice_never_publishes_decodable_bytes(native_library, fault):
    lib = native_library
    audio = AudioFixture()
    nodes = {
        "A": NativeNode(lib, radio=lib.native_radio_create()),
        "B": NativeNode(
            lib, radio=lib.native_radio_create(), device="esp-66778899aabb", audio=audio.port
        ),
    }
    try:
        nodes["A"].claim()
        identifier, source = encoded_source(nodes["A"])
        run, revisions, reservations = prepare_voice(
            nodes, source, "0" * 64 if fault == "hash" else None
        )
        receiver = nodes["B"]
        pending = reservations["B"]
        assert pending["artifact_state"] == "reserved"
        assert not receiver.request(
            "audio.decode",
            {"source_artifact_id": pending["artifact_id"], "artifact_id": str(uuid4())},
        )["ok"]
        assert receiver.request("run.arm", {"config_revision": revisions["B"]}, run_id=run)["ok"]
        assert nodes["A"].request("run.arm", {"config_revision": revisions["A"]}, run_id=run)["ok"]
        assert nodes["A"].request("run.start", {"config_revision": revisions["A"]}, run_id=run)[
            "ok"
        ]
        records = []
        for index in range(8):
            raw = bytearray(sent(nodes["A"]))
            if index == 7 and fault == "tamper":
                raw[-1] ^= 1
            if index != 7 or fault != "drop":
                lib.native_radio_inject(receiver.radio, bytes(raw), len(raw), 2)
                receiver.tick(1000)
                records.extend(receiver.drain())
            lib.native_radio_tx_done(nodes["A"].radio)
            nodes["A"].tick(1000)
            nodes["A"].drain()
            nodes["A"].tick(1000)
            nodes["A"].drain()
        assert audio.starts == 0
        assert not any(
            row.get("name") == "message.result" and row["data"]["status"] == "delivered"
            for row in records
        )
        if fault == "tamper":
            assert any(
                row.get("name") == "rx.rejected" and row["data"]["stage"] == "authentication"
                for row in records
            )
        if fault == "hash":
            assert any(
                row.get("name") == "rx.rejected" and row["data"]["reason"] == "content_mismatch"
                for row in records
            )
        assert receiver.request("run.stop", {"reason": "operator"}, run_id=run)["ok"]
        for _ in range(8):
            receiver.tick(1000)
            receiver.drain()
        assert receiver.request("artifact.list")["result"]["artifacts"] == []
        assert not receiver.request(
            "audio.decode",
            {"source_artifact_id": pending["artifact_id"], "artifact_id": str(uuid4())},
        )["ok"]
        assert receiver.request("status.get")["result"]["state"] == "idle"
        assert audio.starts == 0
        assert nodes["A"].request("artifact.delete", {"artifact_id": identifier})["ok"]
    finally:
        for node in nodes.values():
            node.close()


def drive_pair(nodes, lib, drop_ack=False):
    for name in ("native_radio_generation", "native_radio_listening", "native_radio_transmitting"):
        getattr(lib, name).argtypes = [C.c_void_p]
        getattr(lib, name).restype = C.c_uint
    generations = dict.fromkeys(nodes, 0)
    records, frames, flights = {role: [] for role in nodes}, [], []
    dropped = False
    for _ in range(2000):
        for role, node in nodes.items():
            node.tick(10000)
            records[role].extend(node.drain())
            generation = lib.native_radio_generation(node.radio)
            if generation != generations[role]:
                generations[role] = generation
                raw = sent(node)
                frames.append((role, raw))
                flights.append((node.now() + 20000, role, generation, raw))
        pending = []
        for due, role, generation, raw in flights:
            source, target = nodes[role], nodes["B" if role == "A" else "A"]
            if source.now() < due:
                pending.append((due, role, generation, raw))
                continue
            if not lib.native_radio_transmitting(source.radio):
                continue
            lib.native_radio_tx_done(source.radio)
            lost = drop_ack and not dropped and raw[3] == 2
            if lost:
                dropped = True
            elif lib.native_radio_listening(target.radio):
                lib.native_radio_inject(target.radio, raw, len(raw), 2)
        flights = pending
        if all(any(row.get("name") == "run.summary" for row in records[role]) for role in nodes):
            return records, frames
    raise AssertionError("Bounded voice pair did not complete")


@pytest.mark.parametrize("direction", ["A_TO_B", "B_TO_A"])
def test_encoded_voice_retries_lost_ack_and_delivers_once_in_both_directions(
    native_library, direction
):
    lib = native_library
    nodes = {
        "A": NativeNode(lib, radio=lib.native_radio_create()),
        "B": NativeNode(lib, radio=lib.native_radio_create(), device="esp-66778899aabb"),
    }
    source_role = "A" if direction == "A_TO_B" else "B"
    target_role = "B" if source_role == "A" else "A"
    try:
        assert nodes[source_role].request("control.claim", {"node_role": source_role})["ok"]
        identifier, source = encoded_source(nodes[source_role])
        encoded = readback(nodes[source_role], identifier, 1200)
        run, revisions, _ = prepare_voice(nodes, source, ack=True, direction=direction)
        assert nodes[target_role].request(
            "run.arm", {"config_revision": revisions[target_role]}, run_id=run
        )["ok"]
        assert nodes[source_role].request(
            "run.arm", {"config_revision": revisions[source_role]}, run_id=run
        )["ok"]
        assert nodes[source_role].request(
            "run.start", {"config_revision": revisions[source_role]}, run_id=run
        )["ok"]
        records, frames = drive_pair(nodes, lib, drop_ack=True)
        summaries = {
            role: next(row["data"] for row in rows if row.get("name") == "run.summary")
            for role, rows in records.items()
        }
        assert all(summary["stop_reason"] == "completed" for summary in summaries.values()), (
            summaries
        )
        assert (
            summaries[source_role]["original_packets"] == 8
            and summaries[source_role]["tx_attempts"] == 9
        )
        assert (
            summaries[target_role]["accepted_fragments"] == 8
            and summaries[target_role]["delivered_messages"] == 1
        )
        assert summaries[target_role]["duplicates"] == 1
        retry = [
            raw
            for role, raw in frames
            if role == source_role and raw[3] == 1 and raw[24:26] == b"\x00\x00"
        ]
        assert len(retry) == 2 and retry[0] == retry[1]
        recovered = nodes[target_role].request("artifact.list")["result"]["artifacts"][0]
        assert readback(nodes[target_role], recovered["artifact_id"], 1200) == encoded
        assert decode(nodes[target_role], recovered["artifact_id"])[1]["status"] == "completed"
    finally:
        for node in nodes.values():
            node.close()


@pytest.mark.parametrize("phase", ["transfer", "decode", "play"])
def test_voice_stage_cancel_releases_resources_and_following_work_succeeds(native_library, phase):
    lib = native_library
    audio = AudioFixture()
    nodes = {
        "A": NativeNode(lib, radio=lib.native_radio_create()),
        "B": NativeNode(
            lib, radio=lib.native_radio_create(), device="esp-66778899aabb", audio=audio.port
        ),
    }
    try:
        nodes["A"].claim()
        identifier, source = encoded_source(nodes["A"])
        run, revisions, _ = prepare_voice(nodes, source)
        assert nodes["B"].request("run.arm", {"config_revision": revisions["B"]}, run_id=run)["ok"]
        assert nodes["A"].request("run.arm", {"config_revision": revisions["A"]}, run_id=run)["ok"]
        assert nodes["A"].request("run.start", {"config_revision": revisions["A"]}, run_id=run)[
            "ok"
        ]
        if phase == "transfer":
            raw = sent(nodes["A"])
            lib.native_radio_inject(nodes["B"].radio, raw, len(raw), 2)
            nodes["B"].tick(1000)
            nodes["B"].drain()
            for node in nodes.values():
                assert node.request("run.stop", {"reason": "operator"}, run_id=run)["ok"]
                for _ in range(8):
                    node.tick(1000)
                    node.drain()
                assert node.request("session.close", run_id=run)["ok"]
            assert nodes["B"].request("artifact.list")["result"]["artifacts"] == []
            assert audio.starts == 0
            run, revisions, _ = prepare_voice(nodes, source)
            assert nodes["B"].request("run.arm", {"config_revision": revisions["B"]}, run_id=run)[
                "ok"
            ]
            assert nodes["A"].request("run.arm", {"config_revision": revisions["A"]}, run_id=run)[
                "ok"
            ]
            assert nodes["A"].request("run.start", {"config_revision": revisions["A"]}, run_id=run)[
                "ok"
            ]
        records, _ = drive_pair(nodes, lib)
        assert all(
            next(row["data"] for row in rows if row.get("name") == "run.summary")["stop_reason"]
            == "completed"
            for rows in records.values()
        )
        receiver = nodes["B"]
        encoded = receiver.request("artifact.list")["result"]["artifacts"][0]
        if phase == "decode":
            accepted = receiver.request(
                "audio.decode",
                {"source_artifact_id": encoded["artifact_id"], "artifact_id": str(uuid4())},
            )
            assert accepted["ok"]
            for _ in range(5):
                receiver.tick(1000)
                receiver.drain()
            assert receiver.request(
                "operation.stop", {"operation_id": accepted["result"]["operation_id"]}
            )["ok"]
            files = receiver.request("artifact.list")["result"]["artifacts"]
            assert len(files) == 1 and not files[0]["in_use"] and audio.starts == 0
        decoded, terminal = decode(receiver, encoded["artifact_id"])
        assert terminal["status"] == "completed"
        played = receiver.request("audio.play", {"artifact_id": decoded})
        assert played["ok"]
        if phase == "play":
            assert receiver.request(
                "operation.stop", {"operation_id": played["result"]["operation_id"]}
            )["ok"]
            assert audio.stops >= 1
            assert receiver.request("audio.play", {"artifact_id": decoded})["ok"]
        audio.progress = AudioProgress(24000, 24000, 0, True, False)
        receiver.tick()
        result = next(
            row["data"] for row in receiver.drain() if row.get("name") == "operation.result"
        )
        assert result["status"] == "completed"
        assert receiver.request("status.get")["result"]["state"] == "idle"
        assert all(
            not file["in_use"] for file in receiver.request("artifact.list")["result"]["artifacts"]
        )
        assert nodes["A"].request("artifact.delete", {"artifact_id": identifier})["ok"]
    finally:
        for node in nodes.values():
            node.close()


@pytest.mark.parametrize(
    "overrides",
    [
        {"message_bytes": 1199},
        {"sample_count": 24001},
        {"sample_count": 0},
        {"source_seed": 743},
        {"security": "none"},
        {"playback": True},
        {"expected_sha256": "A" * 64},
        {"expected_sha256": "0" * 64},
        {"source_artifact_id": "00000000-0000-0000-0000-000000000000"},
    ],
)
def test_voice_prepare_rejects_invalid_source_geometry_or_protection_without_borrowing(
    native_library, overrides
):
    lib = native_library
    nodes = {
        "A": NativeNode(lib, radio=lib.native_radio_create()),
        "B": NativeNode(lib, radio=lib.native_radio_create(), device="esp-66778899aabb"),
    }
    try:
        nodes["A"].claim()
        identifier, source = encoded_source(nodes["A"])
        _, _, error = prepare_voice(nodes, source, overrides=overrides, reject=True)
        assert error["code"] in ("INVALID_ARGUMENT", "ARTIFACT_NOT_FOUND")
        files = nodes["A"].request("artifact.list")["result"]["artifacts"]
        assert len(files) == 1 and not files[0]["in_use"]
        assert nodes["A"].request("artifact.delete", {"artifact_id": identifier})["ok"]
    finally:
        for node in nodes.values():
            node.close()


def test_voice_prepare_requires_the_explicit_encoded_length_even_when_default_would_match(
    native_library,
):
    lib = native_library
    nodes = {
        "A": NativeNode(lib, radio=lib.native_radio_create()),
        "B": NativeNode(lib, radio=lib.native_radio_create(), device="esp-66778899aabb"),
    }
    try:
        nodes["A"].claim()
        identifier, source = encoded_source(nodes["A"], samples=1280)
        assert source["length_bytes"] == 64
        _, _, error = prepare_voice(nodes, source, reject=True, omit=("message_bytes",))
        assert error["code"] == "INVALID_ARGUMENT"
        assert nodes["A"].request("artifact.delete", {"artifact_id": identifier})["ok"]
    finally:
        for node in nodes.values():
            node.close()
