"""Hash the implementation used by the physical encryption comparison."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
destination = Path(sys.argv[1]).resolve()
destination.relative_to(root)
assert destination.is_dir()
paths = [
    "platformio.ini", "src/lora_crypto_bench.cpp", "include/crypto_radio_frame.h",
    "include/radio_frame.h", "include/audio_diagnostics.h", "include/protocol.h",
    "include/config.h", "include/lora_display_model.h", "lib/chunking/chunker.cpp",
    "lib/chunking/chunker.h", "lib/lora_bench_display/lora_bench_display.cpp",
    "lib/lora_bench_display/lora_bench_display.h", "tools/lora_crypto_bench.py",
    "tools/lora_transfer_bench.py", "tools/verify_heltec_bench.py",
    "tools/run_lora_crypto_comparison.ps1", "test/host/lora_crypto_bench_test.py",
    "test/host/crypto_radio_frame_test.cpp",
    ".pio/build/heltec_crypto_com6/firmware.bin", ".pio/build/heltec_crypto_com7/firmware.bin",
]
def record(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

manifest = {
    "created_at": datetime.now(timezone.utc).isoformat(),
    "purpose": "fresh_20_physical_trials_10_plain_10_aes128gcm",
    "firmware": "lora-crypto-1-gcm", "timing_schema": 1, "crypto_schema": 1,
    "same_binary_per_node_for_both_modes": True,
    "trial_order": "10 PLAIN then 10 GCM; five each direction within each group",
    "nonce_source": "96-bit OS-random nonce on host, unique per GCM trial; provisioned only to TX, carried to RX by LoRa",
    "key_handling": "fresh 128-bit key in RAM only, USB provisioned, command logs redacted, no key saved",
    "encoding": "uncompressed 8000 Hz 16-bit mono PCM; 3 seconds; 48000 audio bytes",
    "units": {"device_timers": "microseconds", "memory": "bytes", "KiB": "1024 bytes"},
    "files": {name: record(root / name) for name in paths},
}
path = destination / "implementation-manifest.json"
assert not path.exists()
path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
build = {
    "build_log": "output/validation/lora-crypto-build.log",
    "same_binary_per_node_for_both_modes": True,
    "hardware_aes_enabled": True,
    "environments": {env: {
        "flash_used_bytes": 490406, "static_ram_used_bytes": 26692,
        "firmware_bin_bytes": (root / f".pio/build/{env}/firmware.bin").stat().st_size,
        "sha256": record(root / f".pio/build/{env}/firmware.bin")["sha256"],
    } for env in ("heltec_crypto_com6", "heltec_crypto_com7")},
    "limits": "Static RAM and linker flash usage are build values, not peak runtime memory or per-message storage. No audio is written to flash.",
}
(destination / "build-info.json").write_text(json.dumps(build, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"manifest": str(path), "file_count": len(paths), "build_info": build}))
