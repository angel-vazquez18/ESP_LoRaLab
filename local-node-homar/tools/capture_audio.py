"""Export the ESP32's last PCM recording, validate CRC, save WAV and metrics.

Requires pyserial (already included in PlatformIO's Python environment).
Close the serial monitor before running. Default: export only, no recording or
playback. --record requests one three-second capture after a five-second cue.
"""
import argparse
import array
from collections import Counter
import json
import math
from pathlib import Path
import re
import sys
import time
import wave
import zlib

HEADER = re.compile(rb"\[PCM_BEGIN\] bytes=(\d+) rate=(\d+) bits=(\d+) channels=(\d+) crc32=([0-9a-fA-F]{8})\r?\n")

def read_export(port, log):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        line = port.readline(512)
        log.extend(line)
        if b"[PCM ERROR]" in line:
            raise RuntimeError(line.decode("ascii", errors="replace").strip())
        match = HEADER.fullmatch(line)
        if match:
            break
    else:
        raise RuntimeError("No PCM header; firmware may lack command d or serial data was corrupted")
    length, rate, bits, channels = map(int, match.groups()[:4])
    expected_crc = int(match.group(5), 16)
    if (length, rate, bits, channels) != (48000, 8000, 16, 1):
        raise RuntimeError("Unexpected PCM format/length; refusing unbounded transfer")
    payload = bytearray()
    while len(payload) < length and time.monotonic() < deadline:
        payload.extend(port.read(min(4096, length - len(payload))))
    if len(payload) != length:
        raise RuntimeError(f"Truncated PCM: {len(payload)}/{length} bytes")
    actual_crc = zlib.crc32(payload)
    if actual_crc != expected_crc:
        raise RuntimeError(f"CRC mismatch: device={expected_crc:08x} host={actual_crc:08x}; no WAV written")
    trailer = bytearray()
    while len(trailer) < 128 and time.monotonic() < deadline:
        trailer.extend(port.read(1))
        if trailer.endswith(b"[PCM_END]\r\n") or trailer.endswith(b"[PCM_END]\n"):
            break
    if bytes(trailer) not in (b"\n[PCM_END]\r\n", b"\n[PCM_END]\n", b"\r\n[PCM_END]\r\n"):
        raise RuntimeError("Missing/invalid PCM trailer; no WAV written")
    log.extend(trailer)
    return bytes(payload), rate, expected_crc

def analyze(payload, rate):
    samples = array.array("h")
    samples.frombytes(payload)
    if sys.byteorder != "little":
        samples.byteswap()
    n = len(samples)
    mean = sum(samples) / n
    ac_rms = math.sqrt(sum((x - mean) ** 2 for x in samples) / n)
    longest = run = 0
    previous = None
    for value in samples:
        run = run + 1 if value == previous else 1
        longest = max(longest, run)
        previous = value
    return samples, {
        "samples": n, "sample_rate_hz": rate, "duration_seconds": n / rate,
        "min": min(samples), "max": max(samples), "mean": mean,
        "ac_rms": ac_rms, "ac_rms_dbfs_relative_to_32768": 20 * math.log10(ac_rms / 32768) if ac_rms else None,
        "zero_percent": 100 * samples.count(0) / n,
        "rail_percent": 100 * sum(x in (-32768, 32767) for x in samples) / n,
        "longest_identical_run_samples": longest,
        "largest_adjacent_jump": max(abs(b - a) for a, b in zip(samples, samples[1:])),
        "most_common_values": Counter(samples).most_common(8),
        "rms_100ms": [math.sqrt(sum(float(x) ** 2 for x in samples[i:i + rate // 10]) /
                                 len(samples[i:i + rate // 10])) for i in range(0, n, rate // 10)],
    }

def save_capture(stem, payload, rate, crc, *, metadata=None, verbose=True):
    samples, metrics = analyze(payload, rate)
    metrics["crc32"] = f"{crc:08x}"
    if metadata is not None:
        metrics["capture"] = metadata
    stem.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(stem.with_suffix(".wav")), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(payload)
    stem.with_suffix(".json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    # A min/max envelope retains narrow spikes that simple downsampling hides.
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="620" viewBox="0 0 1200 620">',
             '<rect width="1200" height="620" fill="white"/>',
             '<g font-family="sans-serif" font-size="17" fill="#17202a">',
             '<text x="60" y="30">Microphone PCM before speaker playback (8 kHz, 16-bit mono)</text>']
    for top, count, caption in ((65, len(samples), "Whole 3-second recording"), (350, min(800, len(samples)), "First 100 milliseconds")):
        height, width = 200, 1080
        mid = top + height / 2
        parts.append(f'<text x="60" y="{top - 10}">{caption}</text>')
        parts.append(f'<rect x="60" y="{top}" width="{width}" height="{height}" fill="#f3f6fa"/>')
        parts.append(f'<path d="M60 {mid}h{width}" stroke="#8899aa"/>')
        commands = []
        buckets = min(width, count)
        for column in range(buckets):
            block = samples[column * count // buckets:(column + 1) * count // buckets]
            x = 60 + column * width / buckets
            y1 = mid - max(block) * height / 65536
            y2 = mid - min(block) * height / 65536
            commands.append(f'M{x:.2f} {y1:.2f}V{max(y1 + .6, y2):.2f}')
        parts.append(f'<path d="{" ".join(commands)}" stroke="#2369bd" fill="none"/>')
        parts.append(f'<text x="60" y="{top + height + 24}">0 s</text><text x="1040" y="{top + height + 24}">{count / rate:.3f} s</text>')
    parts.append('</g></svg>')
    stem.with_suffix(".svg").write_text("\n".join(parts), encoding="utf-8")
    if verbose:
        print(json.dumps({k: v for k, v in metrics.items() if k != "rms_100ms"}, indent=2))
        print(f"Saved: {stem.with_suffix('.wav')} (original level; start PC volume low)")
    return metrics

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM4")
    parser.add_argument("--out", type=Path, required=True, help="Output filename stem (no extension)")
    parser.add_argument("--record", action="store_true", help="Capture new audio before export; otherwise export existing recording")
    args = parser.parse_args()
    for suffix in (".wav", ".json", ".svg", ".serial.txt"):
        if args.out.with_suffix(suffix).exists():
            parser.error(f"Output exists: {args.out.with_suffix(suffix)}; choose a new --out")
    import serial
    port = serial.Serial(port=None, baudrate=115200, timeout=.2, write_timeout=2)
    port.dtr = port.rts = False
    port.port = args.port
    log = bytearray()
    try:
        port.open()
        # Do not pulse reset: export must retain the last recording.
        port.reset_input_buffer()
        if args.record:
            print("Recording begins in five seconds; then speak for three seconds.", flush=True)
            time.sleep(5)
            print("RECORDING NOW", flush=True)
            port.write(b"m\n")
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                line = port.readline(512)
                log.extend(line)
                if b"Recording failed" in line:
                    raise RuntimeError("Microphone capture failed")
                if b"[AUDIO] Recording complete" in line:
                    break
            else:
                raise RuntimeError("Recording completion not received")
        port.write(b"d\n")
        payload, rate, crc = read_export(port, log)
    finally:
        if port.is_open:
            port.close()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.with_suffix(".serial.txt").write_text(log.decode("utf-8", errors="replace"), encoding="utf-8")
    save_capture(args.out, payload, rate, crc)

if __name__ == "__main__":
    main()
