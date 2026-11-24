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


def inspect_pcm(pcm: bytes, expected_samples: int) -> dict:
    if type(expected_samples) is not int or not 1 <= expected_samples <= 24000:
        raise ValueError("Expected sample count must be 1–24000")
    if len(pcm) != expected_samples * 2:
        raise ValueError("PCM length does not match the exact requested sample count")
    samples = struct.unpack(f"<{expected_samples}h", pcm)
    peak = max(abs(v) for v in samples)
    rms = (sum(v * v for v in samples) / expected_samples) ** 0.5
    width = max(1, (expected_samples + 127) // 128)
    return {
        "sample_count": expected_samples,
        "raw_bytes": len(pcm),
        "sample_rate_hz": 8000,
        "channels": 1,
        "bit_depth": 16,
        "duration_s": expected_samples / 8000,
        "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
        "peak_abs": peak,
        "rms": rms,
        "all_zero": peak == 0,
        "near_silence": rms <= 32,
        "silence_rms_threshold": 32,
        "clipped_samples": sum(v in (-32768, 32767) for v in samples),
        "waveform": [
            {"min": min(samples[i : i + width]) / 32768, "max": max(samples[i : i + width]) / 32768}
            for i in range(0, expected_samples, width)
        ],
        "signal_warning": "All samples are zero; microphone response is unverified"
        if peak == 0
        else "Near silence; check response with a known spoken phrase"
        if rms <= 32
        else None,
        "hardware_qualified": False,
    }


def pcm_wav(pcm: bytes, expected_samples: int) -> bytes:
    inspect_pcm(pcm, expected_samples)
    target = io.BytesIO()
    with wave.open(target, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(pcm)
    return target.getvalue()
