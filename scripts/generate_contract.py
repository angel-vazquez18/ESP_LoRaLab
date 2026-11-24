"""Generate shared schemas and diagnostic metadata, or detect drift without writes."""

import argparse
import hashlib
import json
from pathlib import Path

from lora_testbed import (
    artifact_contract_v2,
    audio_contract_v2,
    codec_contract_v2,
    control_v2,
    crypto_benchmark_v2,
    ptt_contract_v2,
    rf_events_v2,
    run_protocol_v2,
)
from lora_testbed.experiments_v2 import KnownDataPlan
from lora_testbed.v2 import schema, schema_digest


def outputs(root: Path) -> dict[Path, str]:
    def document(value):
        return json.dumps(value, indent=2) + "\n"

    board = json.loads(
        (root / "hardware/boards/heltec_wifi_lora32_v4.json").read_text()
    )
    if any(
        board["ptt"][key] != ptt_contract_v2.POLICY[key]
        for key in ("gpio", "active_level", "internal_pullup")
    ):
        raise ValueError("PTT wiring differs from the selected supplement policy")
    pins = board["amplifier"]["gpio"]
    mic = board["microphone"]["gpio"]
    radio_file = root / "hardware/boards/heltec_v4_radio_variants.json"
    radio = json.loads(radio_file.read_text())
    radio_header = "#pragma once\n"
    radio_header += f'#define RADIO_BOARD_REFERENCE_SHA256 "{hashlib.sha256(radio_file.read_bytes()).hexdigest()}"\n'
    for name, gpio in radio["common_gpio"].items():
        radio_header += f"#define RADIO_GPIO_{name.upper()} {gpio}\n"
    radio_header += f"#define RADIO_GPIO_V42_MODE {radio['variants']['heltec_v4_2_gc1109']['fem_mode_gpio']}\n"
    radio_header += f"#define RADIO_GPIO_V43_MODE {radio['variants']['heltec_v4_3_kct8103l']['fem_mode_gpio']}\n"
    vector_file = root / "contracts/v2/crypto_benchmark_vectors.json"
    vectors = json.loads(vector_file.read_text())

    def array(value):
        return ",".join(f"0x{byte:02x}" for byte in bytes.fromhex(value))

    vector_header = "#pragma once\n#include <stdint.h>\n"
    vector_header += "typedef struct { unsigned bytes; uint8_t header[40], plain[199], protected_bytes[215]; } crypto_benchmark_vector;\n"
    vector_header += (
        "static const uint8_t crypto_benchmark_public_key[16] = {"
        + array(vectors["key_hex"])
        + "};\n"
    )
    vector_header += (
        "static const crypto_benchmark_vector crypto_benchmark_vectors[4] = {\n"
    )
    for v in vectors["vectors"]:
        vector_header += (
            "{"
            + str(v["payload_bytes"])
            + ",{"
            + array(v["header_hex"])
            + "},{"
            + array(v["plaintext_hex"])
            + "},{"
            + array(v["protected_hex"])
            + "}},\n"
        )
    vector_header += "};\n"
    return {
        root / "contracts/v2/ptt_capture.schema.json": document(ptt_contract_v2.schema()),
        root / "firmware/lora_node/main/generated/ptt_profile.h": (
            "#pragma once\n"
            f'#define PTT_PROFILE "{ptt_contract_v2.PROFILE}"\n'
            f'#define PTT_SCHEMA_SHA256 "{ptt_contract_v2.schema_digest()}"\n'
            f"#define PTT_GPIO {board['ptt']['gpio']}\n"
            f"#define PTT_DEBOUNCE_US {ptt_contract_v2.DEBOUNCE_US}LL\n"
        ),
        root / "contracts/v2/codec_io.schema.json": document(
            codec_contract_v2.schema()
        ),
        root / "firmware/lora_node/main/generated/codec_profile.h": (
            "#pragma once\n"
            f'#define CODEC_PROFILE "{codec_contract_v2.PROFILE}"\n'
            f'#define CODEC_SCHEMA_SHA256 "{codec_contract_v2.schema_digest()}"\n'
        ),
        root / "contracts/v2/crypto_benchmark.schema.json": document(
            crypto_benchmark_v2.schema()
        ),
        root
        / "firmware/lora_node/main/generated/crypto_benchmark_vectors.h": vector_header,
        root / "firmware/lora_node/main/generated/crypto_benchmark_profile.h": (
            "#pragma once\n"
            f'#define CRYPTO_BENCH_PROFILE "{crypto_benchmark_v2.PROFILE}"\n'
            f'#define CRYPTO_BENCH_SCHEMA_SHA256 "{crypto_benchmark_v2.schema_digest()}"\n'
            f'#define CRYPTO_BENCH_VECTOR_SHA256 "{hashlib.sha256(vector_file.read_bytes()).hexdigest()}"\n'
        ),
        root / "firmware/lora_node/main/generated/radio_board.h": radio_header,
        root / "contracts/v2/audio.schema.json": document(audio_contract_v2.schema()),
        root / "firmware/lora_node/main/generated/audio_profile.h": (
            "#pragma once\n"
            f'#define AUDIO_PROFILE "{audio_contract_v2.PROFILE}"\n'
            f'#define AUDIO_SCHEMA_SHA256 "{audio_contract_v2.schema_digest()}"\n'
            f"#define AUDIO_MAX_SAMPLES {audio_contract_v2.MAX_SAMPLES}U\n"
            f"#define AUDIO_SAMPLE_RATE {audio_contract_v2.SAMPLE_RATE}U\n"
            f"#define AUDIO_OUTPUT_BCLK {pins['bclk']}\n"
            f"#define AUDIO_OUTPUT_WS {pins['lrc']}\n"
            f"#define AUDIO_OUTPUT_DIN {pins['din']}\n"
            f"#define AUDIO_INPUT_BCLK {mic['sck']}\n"
            f"#define AUDIO_INPUT_WS {mic['ws']}\n"
            f"#define AUDIO_INPUT_SD {mic['sd']}\n"
            "#define AUDIO_WARMUP_SAMPLES 4800U\n"
        ),
        root / "contracts/v2/diagnostic.schema.json": document(schema()),
        root / "contracts/v2/control.schema.json": document(control_v2.schema()),
        root / "contracts/v2/artifact.schema.json": document(
            artifact_contract_v2.schema()
        ),
        root / "firmware/lora_node/main/generated/artifact_profile.h": (
            "#pragma once\n"
            f'#define ARTIFACT_PROFILE "{artifact_contract_v2.PROFILE}"\n'
            f'#define ARTIFACT_SCHEMA_SHA256 "{artifact_contract_v2.schema_digest()}"\n'
            f"#define ARTIFACT_SLOTS {artifact_contract_v2.ARTIFACT_SLOTS}U\n"
            f"#define ARTIFACT_MAX_BYTES {artifact_contract_v2.MAX_ARTIFACT_BYTES}U\n"
            f"#define ARTIFACT_TOTAL_BYTES {artifact_contract_v2.TOTAL_ARTIFACT_BYTES}U\n"
            f"#define ARTIFACT_CHUNK_BYTES {artifact_contract_v2.CHUNK_BYTES}U\n"
        ),
        root / "firmware/lora_node/main/generated/contract_schema.h": (
            f'#pragma once\n#define CONTRACT_SCHEMA_SHA256 "{control_v2.schema_digest()}"\n'
        ),
        root / "firmware/diagnostic/main/contract_schema.h": (
            f'#pragma once\n#define CONTRACT_SCHEMA_SHA256 "{schema_digest()}"\n'
        ),
        root / "contracts/v2/known_data.schema.json": document(
            KnownDataPlan.model_json_schema()
        ),
        root / "contracts/v2/known_data_events.schema.json": document(
            rf_events_v2.schema()
        ),
        root / "contracts/v2/execution.schema.json": document(run_protocol_v2.schema()),
        root / "firmware/lora_node/main/generated/execution_profile.h": (
            "#pragma once\n"
            f'#define EXECUTION_PROFILE "{run_protocol_v2.EXECUTION_PROFILE}"\n'
            f'#define EXECUTION_SCHEMA_SHA256 "{run_protocol_v2.schema_digest()}"\n'
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail on drift without writing files"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    stale = []
    for path, expected in outputs(root).items():
        if args.check:
            if not path.exists() or path.read_text() != expected:
                stale.append(str(path.relative_to(root)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected)
    if stale:
        print("Generated contract drift: " + ", ".join(stale))
        return 1
    print("Generated contracts match" if args.check else "Generated contracts updated")
    print(f"Diagnostic schema: {schema_digest()}")
    print(f"Execution schema: {run_protocol_v2.schema_digest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
