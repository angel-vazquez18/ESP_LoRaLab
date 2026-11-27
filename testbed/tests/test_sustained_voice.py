"""Exercise the shared fixed-rate runner against both native node cores."""

import asyncio
import hashlib
import io
import json
import zipfile
from time import monotonic_ns
from uuid import uuid4

from test_fixed_source_rf_native import Producer
from test_multi_fragment_radio import Pair
from test_node_control_native import NativeSerial
from test_node_control_native import native_library as native_library

from lora_testbed.audio import inspect_wav, pcm_wav, save_wav
from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest, compile_matrix


def test_default_sustained_source_plan_preserves_profiles_and_windows():
    request = MatrixRequest(catalog_id="VOICE-03", voice_reference_ids=[str(uuid4())])
    plan = compile_matrix(request)
    assert plan["full_plan"] and len(plan["cases"]) == 18
    assert {c["link"]["ack_mode"] for c in plan["cases"]} == {"none", "stop_wait"}
    assert {c["radio"]["bandwidth_hz"] for c in plan["cases"]} == {125000, 500000}
    for case in plan["cases"]:
        assert case["message_count"] == 20
        assert case["producer_duration_ms"] == 60000 and case["drain_cap_ms"] == 30000
        assert case["queue_max_bytes"] == 4800


class SourcePair(Pair):
    async def connect(self):
        producer = Producer(self.lib)
        for role, device in (("A", "esp-001122334455"), ("B", "esp-66778899aabb")):
            worker = producer if role == "A" else None
            peer = NativeSerial(
                self.lib,
                device=device,
                radio=self.lib.native_radio_create(),
                source_worker=worker.port if worker else None,
            )
            self.attach_clock(peer, worker)
            self.serials[role] = peer
            node = self.host.physical[role]
            node.opener = lambda _, selected=peer: selected
            await node.connect("fixture-source-" + role)

    @staticmethod
    def attach_clock(peer, producer):
        core = peer.core
        core.realtime = False
        last_ns = monotonic_ns()
        tick = core.tick

        def advance():
            nonlocal last_ns
            now_ns = monotonic_ns()
            # Run the native device clock faster with sub-frame steps.
            core.time += min(10000, 4 * (now_ns - last_ns) // 1000)
            last_ns = now_ns
            if producer:
                producer.step(core.time)
            tick()

        core.tick = advance


def test_sustained_voice_matrix_saves_source_trace_and_verified_receiver_archive(
    tmp_path, native_library
):
    async def scenario():
        host = Host(tmp_path)
        pair = SourcePair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            wav = pcm_wav(b"\x00\x08" * 24000, 24000)
            reference = inspect_wav(wav, "source.wav")
            save_wav(tmp_path, reference, wav)
            host.store.save_reference(reference)
            bridge = asyncio.create_task(pair.bridge())
            spec = MatrixRequest(
                catalog_id="VOICE-03",
                groups=["C1"],
                directions=["A_TO_B"],
                voice_reference_ids=[reference["id"]],
                repetitions=1,
            )
            plan = host.procedures.matrix_preview(spec, host.radio, host.voice)
            assert plan["ready_case_count"] == 1, plan["cases"][0]["blockers"]
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(70):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed" and saved["assessment"] == "pass", saved
            [case] = saved["cases"]
            voice = host.voice.get(case["voice_run_id"])
            rf = host.radio.get(voice["radio_run_id"])
            link = case["measurements"]
            assert case["cleanup_verified"] and rf["cleanup"]["confirmed"]
            assert rf["plan"]["spec"]["source_duration_ms"] == 60000
            assert rf["plan"]["spec"]["message_count"] == 20
            assert link["accounting"] == "consistent"
            assert link["delivery"]["assessment"] == "verified"
            assert link["delivery"]["verified_messages"] > 0
            assert link["delivery"]["rate_in_sender_window_bps"] is None
            evidence = host.observations.get(link["id"])
            assert evidence["evidence_sha256"] == link["sha256"]
            source = evidence["evidence"]["source"]
            assert len(source["frames"]) == 3000
            assert source["status"]["produced_bytes"] == 24000
            assert source["status"]["peak_occupancy_bytes"] <= 4800
            archive = host.radio.content(rf["id"], "recovered").read_bytes()
            assert hashlib.sha256(archive).hexdigest() == source["delivery"]["archive_sha256"]
            assert len(archive) == 24000 and not saved["hardware_validated"]
            with zipfile.ZipFile(io.BytesIO(host.radio.export(rf["id"]))) as bundle:
                exported = bundle.read("fixed-source-assessment.json")
                manifest = json.loads(bundle.read("sha256.json"))
                assert json.loads(exported)["evidence_sha256"] == link["sha256"]
                assert (
                    hashlib.sha256(exported).hexdigest() == manifest["fixed-source-assessment.json"]
                )
            reverse = host.procedures.matrix_preview(
                spec.model_copy(update={"directions": ["B_TO_A"]}), host.radio, host.voice
            )
            assert (
                "Node B lacks the independent fixed-rate source worker"
                in reverse["cases"][0]["blockers"]
            )
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())
