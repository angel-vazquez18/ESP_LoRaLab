import json
from pathlib import Path

import pytest

from lora_testbed.frames_v2 import data_frame, parse_data

ROOT = Path(__file__).resolve().parents[2]


def test_rf_bytes_match_existing_cross_language_fixture():
    fixture = json.loads((ROOT / "contracts/v2/conformance_vectors.json").read_text())[
        "rf_unprotected"
    ]
    frame = data_frame("0102030405060708", 1, 1, 0, 1, 10, "A", "B", b"testbed-v2")
    assert frame.hex() == fixture["frame_hex"]
    assert len(frame) == 50
    decoded = parse_data(frame, 160)
    assert decoded["body"] == b"testbed-v2" and decoded["source_role"] == "A"
    for malformed in (
        frame[:-1],
        frame[:38] + b"\x00\x01" + frame[40:],
        frame[:24] + b"\x00\x01" + frame[26:],
    ):
        with pytest.raises(ValueError):
            parse_data(malformed, 160)
