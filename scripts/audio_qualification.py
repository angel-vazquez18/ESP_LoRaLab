"""Prepare and inspect local audio evidence; never opens a serial port or qualifies it by itself."""

import argparse
import hashlib
import io
import json
import math
import struct
import wave
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

SAMPLES = 24000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pcm_wav(pcm):
    if len(pcm) != SAMPLES * 2:
        raise ValueError("Qualification requires exactly 48000 PCM bytes")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(pcm)
    return output.getvalue()


def read_pcm(content):
    with wave.open(io.BytesIO(content)) as wav:
        if (
            wav.getnchannels(),
            wav.getsampwidth(),
            wav.getframerate(),
            wav.getnframes(),
        ) != (1, 2, 8000, SAMPLES):
            raise ValueError("Expected a three-second 8 kHz signed-16-bit mono WAV")
        pcm = wav.readframes(SAMPLES)
        if len(pcm) != SAMPLES * 2:
            raise ValueError("WAV samples are truncated")
        return pcm


def reference():
    values = []
    for i in range(SAMPLES):
        fade = min(1, i / 320, (SAMPLES - 1 - i) / 320)
        values.append(round(1000 * fade * math.sin(2 * math.pi * 440 * i / 8000)))
    return struct.pack(f"<{SAMPLES}h", *values)


def read_file(path, limit):
    if path.stat().st_size > limit:
        raise ValueError("Evidence file exceeds its size bound")
    with path.open("rb") as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Evidence file exceeds its size bound")
    return data


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def prepare(directory, device_id=None):
    directory.mkdir(parents=True, exist_ok=False)
    pcm = reference()
    (directory / "quiet-reference.pcm").write_bytes(pcm)
    (directory / "quiet-reference.wav").write_bytes(pcm_wav(pcm))
    data = {
        "schema": "local_audio_qualification_v1",
        "prepared_at": datetime.now(UTC).isoformat(),
        "expected_device_id": device_id,
        "reference": {
            "pcm_sha256": digest(pcm),
            "samples": SAMPLES,
            "sample_rate_hz": 8000,
            "peak_limit": 1000,
            "tone_hz": 440,
            "fade_samples": 320,
            "output_gain_ratio": "1/8",
            "configured_hardware_gain_db": 6,
        },
        "operator": None,
        "observed_at": None,
        "printed_revision": None,
        "wiring_independently_checked": None,
        "microphone_response_notes": None,
        "speaker": {"impedance_ohm": 8, "rated_power_w": 1, "supply_v": 3.3},
        "listening": {
            "reference_heard": None,
            "captured_heard": None,
            "distortion_notes": None,
        },
        "captures": {"speech": None, "quiet": None},
        "instruments": {
            "sample_clock": {
                "available": None,
                "measurement": None,
                "limitation": None,
            },
            "rail": {"available": None, "measurement": None, "limitation": None},
        },
        "recovery": {
            "invalid_upload_rejected": None,
            "invalid_upload_evidence": None,
            "cancel_then_valid": None,
            "cancel_evidence": None,
            "usb_issue_21_evidence": None,
        },
        "notes": "Preparation only. Configured rates are not measured rates. No automatic issue closure.",
    }
    save_json(directory / "observations.json", data)
    return data


def local_file(directory, name):
    path = (directory / name).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("Evidence paths must stay inside the packet directory")
    return path


def fetch(base, suffix, limit):
    url = urlsplit(base)
    if (
        url.scheme != "http"
        or url.hostname not in ("127.0.0.1", "localhost")
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Use the local loopback HTTP backend")
    with urlopen(base.rstrip("/") + suffix, timeout=20) as response:
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError("Evidence response exceeds its size bound")
    return content


def collect(directory, kind, job_id, base):
    # GET only: the operator must first perform the speech/quiet capture deliberately.
    data = json.loads(read_file(directory / "observations.json", 1048576))
    if (
        kind not in data["captures"]
        or len(job_id) != 36
        or any(c not in "0123456789abcdef-" for c in job_id)
    ):
        raise ValueError("Choose speech/quiet and a lowercase UUID job ID")
    record = json.loads(fetch(base, f"/api/audio/operations/{job_id}", 1048576))
    if (
        record["status"] != "completed"
        or record["action"] != "capture"
        or record["sample_count"] != SAMPLES
    ):
        raise ValueError("Choose a completed exact three-second capture")
    wav = fetch(base, f"/api/audio/operations/{job_id}/wav", 48044)
    pcm = read_pcm(wav)
    if digest(pcm) != record["clip"]["pcm_sha256"]:
        raise ValueError("Captured PCM hash disagrees with the audio record")
    if (
        data["expected_device_id"]
        and record["identity"]["device_id"] != data["expected_device_id"]
    ):
        raise ValueError("Capture belongs to a different device")
    for name in (f"{kind}.wav", f"{kind}-job.json"):
        if (directory / name).exists():
            raise ValueError(
                "Evidence already exists; prepare a fresh packet instead of overwriting"
            )
    (directory / f"{kind}.wav").write_bytes(wav)
    save_json(directory / f"{kind}-job.json", record)
    data["captures"][kind] = {
        "wav": f"{kind}.wav",
        "record": f"{kind}-job.json",
        "pcm_sha256": digest(pcm),
    }
    save_json(directory / "observations.json", data)
    return data["captures"][kind]


def assess(directory):
    data = json.loads(read_file(directory / "observations.json", 1048576))
    pending, failed, verified = [], [], []
    if not all(
        (
            data.get("operator"),
            data.get("observed_at"),
            data.get("printed_revision"),
            data.get("wiring_independently_checked") is True,
        )
    ):
        pending.append("Operator/revision/independently checked wiring")
    for key in ("reference_heard", "captured_heard"):
        value = data["listening"][key]
        if value is None:
            pending.append(key)
        elif value is not True:
            failed.append(key)
    if not data["listening"].get("distortion_notes"):
        pending.append("Listening/distortion notes")
    if not data.get("microphone_response_notes"):
        pending.append("Spoken phrase/microphone response notes")
    try:
        pcm = read_file(directory / "quiet-reference.pcm", 48000)
        wav_pcm = read_pcm(read_file(directory / "quiet-reference.wav", 48044))
        if (
            len(pcm) != 48000
            or pcm != wav_pcm
            or digest(pcm) != data["reference"]["pcm_sha256"]
        ):
            raise ValueError("Reference PCM/WAV/hash disagree")
    except (OSError, ValueError, wave.Error, EOFError) as exc:
        failed.append(f"Quiet reference: {exc}")
    boots = []
    for kind in ("speech", "quiet"):
        entry = data["captures"][kind]
        if not entry:
            pending.append(f"{kind} capture/WAV/job evidence")
            continue
        try:
            wav = read_file(local_file(directory, entry["wav"]), 48044)
            pcm = read_pcm(wav)
            record = json.loads(
                read_file(local_file(directory, entry["record"]), 1048576)
            )
            identity = record["identity"]
            if (
                record["status"] != "completed"
                or record["action"] != "capture"
                or identity["provenance"] != "hardware"
                or (
                    data["expected_device_id"]
                    and identity["device_id"] != data["expected_device_id"]
                )
                or digest(pcm) != entry["pcm_sha256"]
                or digest(pcm) != record["clip"]["pcm_sha256"]
                or record["sample_count"] != SAMPLES
                or record["clip"]["raw_bytes"] != 48000
            ):
                raise ValueError("Physical identity/count/hash evidence disagrees")
            terminal = record["node_result"]
            result = terminal["result"]
            if (
                terminal["status"] != "completed"
                or result["samples_completed"] != SAMPLES
                or result.get("samples_requested") != SAMPLES
                or result.get("dma_completed") is not True
                or result.get("artifact", {}).get("sha256") != digest(pcm)
                or result["underflows"]
                or result.get("overflows", 0)
            ):
                raise ValueError("DMA/count result is incomplete or failed")
            if kind == "speech" and not any(pcm):
                raise ValueError(
                    "All-zero speech does not establish microphone response"
                )
            values = struct.unpack(f"<{SAMPLES}h", pcm)
            if any(v in (-32768, 32767) for v in values):
                raise ValueError("Clipping needs investigation before qualification")
            boots.append((identity["device_id"], identity["firmware_build_id"]))
            verified.append(kind)
        except (OSError, ValueError, KeyError, TypeError, wave.Error, EOFError) as exc:
            failed.append(f"{kind}: {exc}")
    if len(set(boots)) > 1:
        failed.append(
            "Captures use different devices/firmware builds; start a coherent packet"
        )
    for kind, item in data["instruments"].items():
        measurement = item["measurement"]
        measured = isinstance(measurement, dict) and all(
            measurement.get(k) for k in ("instrument", "method", "observed", "trace")
        )
        if measured:
            measured = local_file(directory, measurement["trace"]).is_file()
        if item["available"] is True and measured:
            verified.append(f"{kind} measured (operator supplied)")
        elif item["available"] is False and item["limitation"]:
            verified.append(f"{kind} explicit instrument limitation")
        else:
            pending.append(
                f"{kind} measured evidence or explicit instrument limitation"
            )
    for key in ("invalid_upload_rejected", "cancel_then_valid"):
        if data["recovery"][key] is not True:
            pending.append(key)
    for key in ("invalid_upload_evidence", "cancel_evidence"):
        evidence = data["recovery"].get(key)
        if not evidence or not local_file(directory, evidence).is_file():
            pending.append(key)
    recovery = data["recovery"]["usb_issue_21_evidence"]
    if not recovery or not local_file(directory, recovery).is_file():
        pending.append("Physical USB recovery issue #21 evidence")
    return {
        "status": "failed"
        if failed
        else "pending"
        if pending
        else "ready_for_human_review",
        "verified": verified,
        "pending": pending,
        "failed": failed,
        "automatic_hardware_qualification": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "collect", "assess"):
        p = sub.add_parser(name)
        p.add_argument("directory", type=Path)
        if name == "prepare":
            p.add_argument("--device-id")
        if name == "collect":
            p.add_argument("--kind", choices=["speech", "quiet"], required=True)
            p.add_argument("--job-id", required=True)
            p.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.directory, args.device_id)
        elif args.command == "collect":
            result = collect(args.directory, args.kind, args.job_id, args.base)
        else:
            result = assess(args.directory)
    except (OSError, ValueError, KeyError, wave.Error, EOFError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(result, indent=2))
    return (
        2
        if result.get("status") == "pending"
        else 1
        if result.get("status") == "failed"
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
