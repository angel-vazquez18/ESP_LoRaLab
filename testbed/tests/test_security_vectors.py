"""Independent AES-GCM oracle for public project wire examples, not node qualification."""

import json
import struct

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from lora_testbed.paths import REPOSITORY_ROOT

FIXTURES = json.loads((REPOSITORY_ROOT / "contracts/v2/security_vectors.json").read_text())
VECTORS = FIXTURES["vectors"]


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["name"])
def test_public_protected_frame_matches_independent_cipher_and_exact_header(vector):
    v = vector
    header = bytes.fromhex(v["header_aad_hex"])
    nonce = bytes.fromhex(v["nonce_hex"])
    key = bytes.fromhex(FIXTURES["source_keys_hex"][v["source_role"]])
    plaintext = bytes.fromhex(v["plaintext_hex"])
    encrypted = bytes.fromhex(v["ciphertext_hex"] + v["tag_hex"])
    assert AESGCM(key).encrypt(nonce, plaintext, header) == encrypted
    assert AESGCM(key).decrypt(nonce, encrypted, header) == plaintext
    assert len(header) == 40 and len(bytes.fromhex(v["tag_hex"])) == 16
    assert nonce == header[8:20] and len(nonce) == 12
    assert bytes.fromhex(v["frame_hex"]) == header + encrypted
    assert v["frame_bytes"] == 40 + len(plaintext) + 16 <= 255
    fields = struct.unpack(">2sBBBBBBQIIHHIHIH", header)
    assert fields == (
        b"LT",
        2,
        v["frame_type"],
        1 + 2 * v["ack_requested"],
        {"A": 1, "B": 2}[v["source_role"]],
        {"A": 1, "B": 2}[v["destination_role"]],
        0,
        int(v["session_id"], 16),
        v["frame_seq"],
        v["message_id"],
        0,
        1,
        v["message_bytes"],
        len(plaintext),
        v["referenced_frame_seq"],
        0,
    )


def test_original_contract_vector_still_matches_the_independent_cipher():
    v = json.loads((REPOSITORY_ROOT / "contracts/v2/conformance_vectors.json").read_text())[
        "rf_protected"
    ]
    actual = AESGCM(bytes.fromhex(v["key_hex"])).encrypt(
        bytes.fromhex(v["nonce_hex"]),
        bytes.fromhex(v["plaintext_hex"]),
        bytes.fromhex(v["header_aad_hex"]),
    )
    assert actual.hex() == v["ciphertext_hex"] + v["tag_hex"]


def test_mutating_any_header_byte_body_tag_nonce_or_source_key_fails_authentication():
    v = VECTORS[0]
    header = bytes.fromhex(v["header_aad_hex"])
    nonce = bytes.fromhex(v["nonce_hex"])
    protected = bytes.fromhex(v["ciphertext_hex"] + v["tag_hex"])
    cipher = AESGCM(bytes.fromhex(FIXTURES["source_keys_hex"]["A"]))
    for index in range(40):
        changed = bytearray(header)
        changed[index] ^= 1
        with pytest.raises(InvalidTag):
            cipher.decrypt(nonce, protected, bytes(changed))
    for index in range(len(protected)):
        changed = bytearray(protected)
        changed[index] ^= 1
        with pytest.raises(InvalidTag):
            cipher.decrypt(nonce, bytes(changed), header)
    with pytest.raises(InvalidTag):
        cipher.decrypt(nonce[:-1] + b"\x02", protected, header)
    with pytest.raises(InvalidTag):
        AESGCM(bytes.fromhex(FIXTURES["source_keys_hex"]["B"])).decrypt(nonce, protected, header)


def test_public_retry_ack_and_exhaustion_examples_have_unambiguous_boundaries():
    by_name = {v["name"]: v for v in VECTORS}
    retry = FIXTURES["exact_retry"]
    assert retry["attempt_1_frame_hex"] == retry["attempt_2_frame_hex"]
    assert retry["attempt_1_frame_hex"] == by_name[retry["vector"]]["frame_hex"]
    assert retry["expected_classification"] == "retry_duplicate"
    ack = by_name["ack_b_for_data_a"]
    assert ack["frame_bytes"] == 56 and ack["plaintext_hex"] == ""
    assert not ack["ack_requested"] and ack["referenced_frame_seq"] == 1
    assert ack["frame_seq"] != by_name[retry["vector"]]["frame_seq"]
    final = by_name["data_final_sequence_max_capacity"]
    assert final["frame_bytes"] == 255 and final["nonce_hex"].endswith("ffffffff")
    assert FIXTURES["secret_command_fields"] == {
        "session.open": ["args.tx_key_hex", "args.rx_key_hex"]
    }
    assert not any("key_hex" in name for name in FIXTURES["retained_setup_fields"])
