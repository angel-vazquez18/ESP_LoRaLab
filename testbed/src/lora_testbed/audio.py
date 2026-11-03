"""Bounded reference-clip ingestion; no simulated compression or voice delivery."""

import hashlib
import io
import struct
import wave
from pathlib import Path
from uuid import uuid4

from .storage import utc_now

MAX_UPLOAD_BYTES = 1_048_576


def inspect_wav(content: bytes, name: str) -> dict:
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("WAV upload exceeds 1 MiB")
    try:
        with wave.open(io.BytesIO(content), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 8000):
                raise ValueError("Use an 8 kHz, 16-bit mono PCM WAV")
            count = audio.getnframes()
            if not 1 <= count <= 24_000:
                raise ValueError("Reference clips must be between one sample and three seconds")
            pcm = audio.readframes(count)
            if len(pcm) != count * 2:
                raise ValueError("WAV sample data is truncated")
    except (wave.Error, EOFError, struct.error) as exc:
        raise ValueError("Invalid or unsupported PCM WAV") from exc
    samples = struct.unpack(f"<{count}h", pcm)
    width = max(1, (count + 127) // 128)
    peaks = [max(abs(v) for v in samples[i : i + width]) / 32768 for i in range(0, count, width)]
    return {
        "id": str(uuid4()),
        "name": name,
        "created_at": utc_now(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "sample_rate_hz": 8000,
        "channels": 1,
        "bit_depth": 16,
        "sample_count": count,
        "raw_bytes": len(pcm),
        "duration_s": count / 8000,
        "file_bytes": len(content),
        "peaks": peaks,
        "kind": "reference",
        "codec": "PCM16 (uncompressed)",
    }


def save_wav(root: Path, reference: dict, content: bytes):
    directory = root / "audio"
    directory.mkdir(exist_ok=True)
    (directory / f"{reference['id']}.wav").write_bytes(content)
