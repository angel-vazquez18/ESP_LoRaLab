"""Exercise reference planning, isolated execution and recorded comparison scope."""

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from test_node_control_native import native_library as native_library
from test_voice_workflows import AudioPair

from lora_testbed.app import create_app
from lora_testbed.audio import inspect_wav, pcm_wav, save_wav
from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest, compile_matrix
from lora_testbed.voice_runs import VoiceRunRequest


def add_reference(host, directory, sample_count):
    content = pcm_wav(b"\x00\x08" * sample_count, sample_count)
    reference = inspect_wav(content, "fixture.wav")
    save_wav(directory, reference, content)
    host.store.save_reference(reference)
    return reference["id"]


def test_voice_plan_retains_reference_identity_direction_and_operator_cases():
    references = [str(uuid4()) for _ in range(3)]
    spec = MatrixRequest(catalog_id="VOICE-02", voice_reference_ids=references)
    plan = compile_matrix(spec)
    assert plan["full_plan"] and plan["case_count"] == 36
    assert {case["reference_id"] for case in plan["cases"] if case["group"] == "C1"} == set(
        references
    )
    prompts = [case for case in plan["cases"] if case["group"] == "C2"]
    assert len(prompts) == 18 and all(
        case["driver"] == "voice_microphone_review" for case in prompts
    )
    assert all(case["comparison_bytes"] == [1200, 64] for case in plan["cases"])


def test_reference_matrix_preserves_independent_comparisons_and_unchecked_listening(
    native_library,
    tmp_path,
):
    async def scenario():
        host = Host(tmp_path)
        pair = AudioPair(host, native_library)
        bridge = None
        try:
            await pair.connect()
            good_id = add_reference(host, tmp_path, 24000)
            wrong_id = add_reference(host, tmp_path, 8000)
            wrong_scope = MatrixRequest(
                catalog_id="VOICE-02",
                groups=["C1"],
                voice_reference_ids=[wrong_id],
                directions=["A_TO_B"],
                repetitions=1,
            )
            preview = host.procedures.matrix_preview(wrong_scope, host.radio, host.voice)
            assert not preview["ready_case_count"]
            assert any("24,000 samples" in text for text in preview["cases"][0]["blockers"])
            spec = MatrixRequest(
                catalog_id="VOICE-02",
                voice_reference_ids=[good_id],
                directions=["A_TO_B"],
                repetitions=1,
            )
            bridge = asyncio.create_task(pair.bridge())
            started = await host.start_procedure_matrix(spec)
            async with asyncio.timeout(40):
                await host.procedures.task
            saved = host.procedures.get(started["id"])
            assert saved["status"] == "completed", saved
            reference, *prompts = saved["cases"]
            assert reference["assessment"] == "pass", reference
            assert all(prompt["status"] == "blocked" for prompt in prompts)
            result = reference["measurements"]
            assert result["reference_id"] == good_id
            assert result["physical_listening"] == "pending" and not saved["hardware_validated"]
            assert all(value["matched"] for value in result["comparison_matches"].values())
            evidence = [
                item["document"]["voice_comparison"]
                for item in host.procedures.all_evidence(saved["id"])
                if "voice_comparison" in item["document"]
            ]
            [report] = evidence
            assert report["physical_listening"]["heard"] == "not_checked"
            assert not report["one_way_latency"]["valid"]
            assert (
                report["artifacts"]["encoded"]["sha256"]
                == report["artifacts"]["recovered"]["sha256"]
            )
            assert host.voice.get(reference["voice_run_id"])["cleanup"]["confirmed"]
            assert not host.busy
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            await host.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("direction", ["A_TO_B", "B_TO_A"])
def test_saved_microphone_voice_reviews_original_content_and_receiver_listening(
    native_library, tmp_path, direction
):
    async def scenario():
        app = create_app(tmp_path)
        async with app.router.lifespan_context(app):
            host = app.state.host
            pair = AudioPair(host, native_library)
            await pair.connect()
            bridge = asyncio.create_task(pair.bridge())
            try:
                accepted = await host.start_voice(
                    VoiceRunRequest(source="microphone", direction=direction)
                )
                async with asyncio.timeout(35):
                    await host.voice.task
                live = host.voice.get(accepted["id"])
                assert live["status"] == "completed" and live["cleanup"]["confirmed"], live
            finally:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            for node in host.physical.values():
                await node.close()
            args = {
                "catalog_id": "VOICE-02",
                "groups": ["C2"],
                "directions": [direction],
                "repetitions": 1,
            }
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://127.0.0.1"
            ) as ui:
                path = "/api/procedures/matrix"
                missing = (await ui.post(f"{path}/preview", json=args)).json()
                assert missing["case_count"] == 3 and missing["ready_case_count"] == 0
                args["voice_microphone_evidence"] = [
                    {
                        "direction": direction,
                        "utterance": 1,
                        "repetition": 1,
                        "voice_run_id": live["id"],
                    }
                ]
                other_direction = "B_TO_A" if direction == "A_TO_B" else "A_TO_B"
                wrong = await ui.post(
                    f"{path}/preview",
                    json={
                        **args,
                        "directions": [other_direction],
                        "voice_microphone_evidence": [
                            {
                                **args["voice_microphone_evidence"][0],
                                "direction": other_direction,
                            }
                        ],
                    },
                )
                assert wrong.json()["ready_case_count"] == 0

                async def review():
                    accepted = await ui.post(path, json=args)
                    assert accepted.status_code == 202, accepted.json()
                    async with asyncio.timeout(5):
                        await host.procedures.task
                    saved = host.procedures.get(accepted.json()["id"])
                    assert not saved["hardware_validated"] and not saved["physical_bindings"]
                    [case] = [row for row in saved["cases"] if row["status"] != "blocked"]
                    return case

                unchecked = await review()
                assert unchecked["assessment"] == "inconclusive", unchecked
                assert "listening" in unchecked["reason"]
                recorded = await ui.post(
                    f"/api/voice/runs/{live['id']}/listening",
                    json={
                        "heard": "heard",
                        "notes": "Isolated fixture",
                    },
                )
                assert recorded.status_code == 200
                case = await review()
                assert case["assessment"] == "pass" and case["cleanup_verified"], case
                result = case["measurements"]
                assert result["voice_link"]["verified_delivered_bytes"] == 1200
                assert result["source_capture_id"] == live["jobs"]["source_audio"]
                assert len(set(case["run_ids"])) == 3
                for basis, size in (("equal_encoded_bytes", 1200), ("standard_64_bytes", 64)):
                    comparison = result["comparisons"][basis]["measurements"]
                    assert comparison["verified_delivered_bytes"] == size
                assert not result["one_way_latency"]["valid"]
                assert len((await ui.get(result["encoded_artifact"])).content) == 1200
                assert (await ui.get(result["decoded_wav"])).content[:4] == b"RIFF"
                host.radio.content(live["radio_run_id"], "recovered").write_bytes(b"damaged")
                rejected = await review()
                assert (
                    rejected["assessment"] == "inconclusive" and "incomplete" in rejected["reason"]
                )

    asyncio.run(scenario())
