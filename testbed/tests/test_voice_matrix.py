"""Exercise reference planning, isolated execution and recorded comparison scope."""

import asyncio
from uuid import uuid4

from test_node_control_native import native_library as native_library
from test_voice_workflows import AudioPair

from lora_testbed.audio import inspect_wav, pcm_wav, save_wav
from lora_testbed.host import Host
from lora_testbed.integration_matrices import MatrixRequest, compile_matrix


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
    assert len(prompts) == 18 and all(case["driver"] == "voice_operator" for case in prompts)
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
