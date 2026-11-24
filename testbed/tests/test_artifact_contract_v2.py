"""Contract checks only: no physical serial port or node-side file store."""

import base64
import hashlib
import json
import zlib
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from lora_testbed import artifact_contract_v2 as artifacts
from lora_testbed import control_v2, v2

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = json.loads((ROOT / "contracts/v2/artifact_examples.json").read_text())


def limits(**updates):
    return artifacts.Capabilities.model_validate(
        {**EXAMPLES["capability_example"], "schema_sha256": artifacts.schema_digest(), **updates}
    )


def entry(name):
    return deepcopy(next(e for e in EXAMPLES["valid"] if e["name"] == name))


def chunk(data, offset=0):
    return {
        "artifact_id": entry("artifact.put")["args"]["artifact_id"],
        "offset": offset,
        "data_b64": base64.b64encode(data).decode(),
        "crc32": f"{zlib.crc32(data):08x}",
    }


@pytest.mark.parametrize("name", artifacts.ARGUMENTS)
def test_valid_and_invalid_examples_for_every_command_and_result(name):
    valid = entry(name)
    artifacts.Command.model_validate(
        {**EXAMPLES["example_envelope"], "name": name, "args": valid["args"]}
    )
    assert artifacts.validate_arguments(name, valid["args"], limits()).model_dump() == valid["args"]
    assert (
        artifacts.validate_result(name, valid["args"], valid["result"], limits()).model_dump()
        == valid["result"]
    )
    invalid = next(e for e in EXAMPLES["invalid"] if e["name"] == name)
    with pytest.raises(ValueError):
        artifacts.validate_arguments(name, invalid["args"], limits())
    with pytest.raises(ValueError):
        artifacts.validate_result(name, valid["args"], invalid["result"], limits())


def test_full_envelope_uses_exact_boot_target_and_strict_arguments():
    command = artifacts.Command.model_validate(EXAMPLES["example_envelope"])
    assert len(v2.encode(command)) <= 4096
    for update in ({"target_boot_id": None}, {"name": "audio.play"}, {"extra": 1}):
        with pytest.raises(ValidationError):
            artifacts.Command.model_validate({**command.model_dump(), **update})
    for value in (True, 1.0, "1"):
        bad = command.model_dump()
        bad["args"]["length_bytes"] = value
        with pytest.raises(ValidationError):
            artifacts.Command.model_validate(bad)


@pytest.mark.parametrize("name", artifacts.ARGUMENTS)
def test_unknown_argument_members_are_rejected(name):
    value = entry(name)
    with pytest.raises(ValidationError):
        artifacts.ARGUMENTS[name].model_validate({**value["args"], "unexpected": True})


def test_crc_and_sha_match_independent_public_artifact_vector():
    vector = json.loads((ROOT / "contracts/v2/conformance_vectors.json").read_text())[
        "artifact_chunk"
    ]
    data = artifacts.decoded_chunk(vector["data_b64"], vector["crc32"])
    assert data == b"123456789"
    assert hashlib.sha256(data).hexdigest() == entry("artifact.begin")["args"]["sha256"]
    assert vector["crc32"] == "cbf43926"


def test_chunk_boundary_decoding_canonical_base64_and_crc():
    maximum = chunk(bytes(range(256)) * 4)
    assert artifacts.Put.model_validate(maximum).model_dump() == maximum
    assert (
        len(
            v2.encode(
                artifacts.Command.model_validate(
                    {**EXAMPLES["example_envelope"], "name": "artifact.put", "args": maximum}
                )
            )
        )
        <= 4096
    )
    for bad in (
        chunk(b"x" * 1025),
        chunk(b""),
        {**maximum, "data_b64": "!not-base64!"},
        {**maximum, "crc32": "ABCDEF00"},
        {**maximum, "crc32": "00000000"},
        chunk(b"x", artifacts.MAX_ARTIFACT_BYTES),
        {**chunk(b"M"), "data_b64": "TR=="},  # Nonzero pad bits encode the same byte.
    ):
        with pytest.raises(ValueError):
            artifacts.Put.model_validate(bad)
    assert artifacts.Put.model_validate(chunk(b"x")).offset == 0


@pytest.mark.parametrize("value", [True, 0.0, "0", -1, 131073])
def test_offsets_reject_wrong_types_and_out_of_range_values(value):
    with pytest.raises(ValidationError):
        artifacts.Put.model_validate({**chunk(b"x"), "offset": value})


def test_pcm_counts_and_opaque_data_have_separate_metadata():
    begin = {
        **entry("artifact.begin")["args"],
        "format": "pcm_s16le_8000_mono",
        "length_bytes": 48000,
    }
    assert artifacts.Begin.model_validate(begin).length_bytes == 48000
    for size in (0, 1, 47999, 48002):
        with pytest.raises(ValueError):
            artifacts.Begin.model_validate({**begin, "length_bytes": size})
    manifest = {
        **entry("artifact.commit")["result"],
        **begin,
        "next_offset": 48000,
        "sample_rate_hz": 8000,
        "sample_count": 24000,
    }
    artifacts.Manifest.model_validate(manifest)
    for update in (
        {"sample_count": 23999},
        {"sample_rate_hz": 16000},
        {"sample_rate_hz": 8000.0},
        {"codec": "codec2_3200_v1"},
    ):
        with pytest.raises(ValueError):
            artifacts.Manifest.model_validate({**manifest, **update})
    with pytest.raises(ValueError):
        artifacts.Manifest.model_validate({**entry("artifact.commit")["result"], "sample_count": 1})


def test_slot_budget_and_manifest_state_boundaries():
    template = entry("artifact.commit")["result"]
    files = [
        {
            **template,
            "artifact_id": f"00000000-0000-4000-8000-{n:012d}",
            "length_bytes": 65536,
            "next_offset": 65536,
        }
        for n in range(4)
    ]
    artifacts.ListResult(artifacts=files)
    with pytest.raises(ValueError):
        artifacts.ListResult(
            artifacts=files + [{**files[0], "artifact_id": "99999999-9999-4999-8999-999999999999"}]
        )
    with pytest.raises(ValueError):
        artifacts.ListResult(
            artifacts=[{**a, "length_bytes": 131072, "next_offset": 131072} for a in files]
        )
    for update in ({"next_offset": 8}, {"state": "uploading", "in_use": True}, {"next_offset": 10}):
        with pytest.raises(ValueError):
            artifacts.CommitResult.model_validate({**template, **update})
    artifacts.Manifest.model_validate({**template, "state": "uploading", "next_offset": 0})
    artifacts.Manifest.model_validate({**template, "state": "failed", "next_offset": 8})


def test_lower_advertised_limits_and_reply_correlation():
    smaller = limits(
        max_artifact_bytes=8,
        node_total_artifact_bytes=8,
        node_artifact_slots=1,
        artifact_chunk_bytes=4,
    )
    for name, args in (
        ("artifact.begin", entry("artifact.begin")["args"]),
        ("artifact.put", chunk(b"12345")),
        ("artifact.put", chunk(b"x", 8)),
        ("artifact.get", {**entry("artifact.get")["args"], "length_bytes": 5}),
        ("artifact.get", {**entry("artifact.get")["args"], "offset": 9, "length_bytes": 1}),
    ):
        with pytest.raises(ValueError):
            artifacts.validate_arguments(name, args, smaller)
    value = entry("artifact.get")
    for result in (
        {**value["result"], "artifact_id": "44444444-4444-4444-8444-444444444444"},
        {**value["result"], "offset": 1},
        {**value["result"], "length_bytes": 8},
    ):
        with pytest.raises(ValueError):
            artifacts.validate_result("artifact.get", value["args"], result, limits())
    short = {**chunk(b"x", 8), "length_bytes": 1, "eof": True}
    artifacts.validate_result(
        "artifact.get",
        {"artifact_id": short["artifact_id"], "offset": 8, "length_bytes": 1024},
        short,
        limits(),
    )
    eof = {**chunk(b"", 9), "length_bytes": 0, "eof": True}
    artifacts.GetResult.model_validate(eof)
    with pytest.raises(ValueError):
        artifacts.GetResult.model_validate({**eof, "eof": False})


def test_capability_limits_reject_inconsistent_or_wrongly_typed_values():
    for update in (
        {"node_artifact_slots": 5},
        {"node_total_artifact_bytes": 131071},
        {"artifact_chunk_bytes": True},
        {"commands": ["artifact.get", "artifact.get"]},
        {"commands": []},
        {"commands": ["artifact.unknown"]},
        {"max_artifact_bytes": 0},
    ):
        with pytest.raises(ValueError):
            limits(**update)


def test_profile_limits_match_selected_baseline_without_changing_other_profiles():
    resources = json.loads((ROOT / "contracts/v2/default_profile.json").read_text())["resources"]
    assert artifacts.MAX_ARTIFACT_BYTES == resources["max_artifact_bytes"]
    assert artifacts.TOTAL_ARTIFACT_BYTES == resources["node_total_artifact_bytes"]
    assert artifacts.ARTIFACT_SLOTS == resources["node_artifact_slots"]
    assert artifacts.CHUNK_BYTES == resources["artifact_chunk_bytes"]
    assert v2.schema_digest() == "769ba12d1d83969065f7b482890b0a26c5d51586bcf8badab200f47bd8e15002"
    assert (
        control_v2.schema_digest()
        == "ea836540f956cd4c6748453aaa0dd94d76b6d151166c53a42c570842db5a5cbd"
    )
    header = (ROOT / "firmware/lora_node/main/generated/contract_schema.h").read_text()
    assert f'"{control_v2.schema_digest()}"' in header


def test_advertisement_example_carries_the_generated_contract_digest():
    advertised = artifacts.Capabilities.model_validate(EXAMPLES["capability_example"])
    assert advertised.schema_sha256 == artifacts.schema_digest()
