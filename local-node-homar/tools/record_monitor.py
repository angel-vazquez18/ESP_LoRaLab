"""Recording console: m records/saves; r records/plays/saves the same audio.

Uses the existing firmware commands m, r and d. No firmware update is needed.
Close other serial monitors first. Files default to <project>/captures, regardless
of the working directory. Only pyserial (included with PlatformIO) is required.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time

from capture_audio import read_export, save_capture

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HELP = ("m [label] = record + save | r [label] = record + speaker playback + save | "
        "d [label] = save last recording | q = quit")


def parse_command(line):
    parts = line.strip().split(maxsplit=1)
    if not parts:
        return None, ""
    command = parts[0].lower()
    if command not in ("m", "r", "d", "q", "help", "?"):
        raise ValueError(HELP)
    if len(parts) > 1 and command not in ("m", "r", "d"):
        raise ValueError("Only m, r and d accept a label")
    return command, parts[1].strip() if len(parts) > 1 else "unlabelled"


def new_capture_folder(root, label):
    # User labels are metadata, never paths. Prefix also avoids Windows device names.
    safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "-", label).strip("-_")[:60] or "unlabelled"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    root.mkdir(parents=True, exist_ok=True)
    for sequence in range(1000):
        suffix = f"-{sequence}" if sequence else ""
        folder = root / f"{timestamp}-{safe_label}{suffix}"
        try:
            folder.mkdir()  # Atomic reservation: never reuse another recording's folder.
            return folder
        except FileExistsError:
            continue
    raise RuntimeError("Could not reserve a new capture folder")


def wait_for_recording(port, log, report):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        line = port.readline(512)
        log.extend(line)
        if len(log) > 256 * 1024:
            raise RuntimeError("Excessive serial output; check baud rate/firmware")
        text = line.decode("utf-8", errors="replace").strip()
        if text.startswith(("[MIC]", "[MIC RAW]", "[AUDIO]")):
            report(text)
        if b"[AUDIO] Recording failed" in line:
            raise RuntimeError("Microphone recording failed; no old recording exported")
        if b"[AUDIO] Recording complete" in line:
            return
    raise RuntimeError("Recording did not complete within 10 seconds; no recording exported")


def wait_for_playback(port, log, report):
    deadline = time.monotonic() + 10
    completed = False
    while time.monotonic() < deadline:
        line = port.readline(512)
        log.extend(line)
        if len(log) > 256 * 1024:
            raise RuntimeError("Excessive serial output; check baud rate/firmware")
        text = line.decode("utf-8", errors="replace").strip()
        if text.startswith("[AUDIO]"):
            report(text)
        if text == "[AUDIO] Direct playback FAILED":
            raise RuntimeError("Speaker playback failed; use d to save the recording separately")
        if text == "[AUDIO] Direct playback complete (digital path)":
            completed = True
        if text == "[STATE] IDLE":
            if completed:
                return
            raise RuntimeError("ESP32 returned to IDLE without confirming direct playback; no recording exported")
    raise RuntimeError("Playback did not complete within 10 seconds; no recording exported")


def firmware_metrics(log):
    text = log.decode("utf-8", errors="replace")
    result = {"diagnostic_lines": [line for line in text.splitlines()
                                   if line.startswith(("[MIC]", "[MIC RAW]", "[AUDIO]"))]}
    pcm = re.search(r"\[MIC\] samples=(\d+) min=(-?\d+) max=(-?\d+) mean=([-\d.]+) "
                    r"AC_RMS=([\d.]+) zero=(\d+) clipped=(\d+)", text)
    if pcm:
        fields = ("samples", "min", "max", "mean", "ac_rms", "zero_samples", "clipped_samples")
        result["pcm"] = {key: float(value) if key in ("mean", "ac_rms") else int(value)
                         for key, value in zip(fields, pcm.groups())}
    raw = re.search(r"\[MIC RAW\] zero_words=(\d+) all_one_words=(\d+) "
                    r"longest_identical_run=(\d+) / (\d+)", text)
    if raw:
        result["raw"] = dict(zip(("zero_words", "all_one_words", "longest_identical_run", "samples"),
                                  map(int, raw.groups())))
    return result


def capture_once(port, root, label, *, record=True, playback=False, report=print):
    if playback and not record:
        raise ValueError("Speaker playback requires a new recording (r)")
    folder = new_capture_folder(root, label)
    stem = folder / "recording"
    log = bytearray()
    metadata = {
        "label": label,
        "requested_at_utc": datetime.now(timezone.utc).isoformat(),
        "serial_port": str(port.port),
        "mode": ("new_recording_direct_playback" if playback else
                 "new_recording" if record else "export_existing"),
        "playback_status": "requested" if playback else "not_requested",
        # Export-only cannot determine when the previous recording was made.
        "recording_time_known": record,
    }
    try:
        # Ignore accumulated heartbeats/old status, then issue only one command.
        # No reset: d must retain the recording in the ESP32's RAM.
        port.reset_input_buffer()
        if record:
            report("Recording requested. Speak for three seconds when 'Speak now' appears.")
            port.write(b"r\n" if playback else b"m\n")
            wait_for_recording(port, log, report)
            if playback:
                report("Listen to the ESP32 speaker now. The same recording will be saved afterwards.")
                wait_for_playback(port, log, report)
                # Firmware completion confirms I2S transfer, not audible quality.
                metadata["playback_status"] = "digital_path_complete"
        report("Saving recording from ESP32... (about five seconds)")
        port.write(b"d\n")
        payload, rate, crc = read_export(port, log)
        metadata["received_at_utc"] = datetime.now(timezone.utc).isoformat()
        metadata["firmware"] = firmware_metrics(log)
        metrics = save_capture(stem, payload, rate, crc, metadata=metadata, verbose=False)
    except (Exception, KeyboardInterrupt) as error:
        metadata["error"] = str(error) or "Interrupted"
        (folder / "error.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        report(f"Capture failed; diagnostic files: {folder}")
        raise
    finally:
        stem.with_suffix(".serial.txt").write_text(log.decode("utf-8", errors="replace"), encoding="utf-8")
    report(f"SAVED: {stem.with_suffix('.wav')}")
    report(f"  min={metrics['min']} max={metrics['max']} AC_RMS={metrics['ac_rms']:.1f} "
           f"rail={metrics['rail_percent']:.2f}% zero={metrics['zero_percent']:.2f}%")
    report("  Also saved: recording.json, recording.svg, recording.serial.txt")
    return stem, metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM4")
    parser.add_argument("--folder", type=Path, default=PROJECT_ROOT / "captures")
    parser.add_argument("--once", metavar="LABEL", help="Save one recording and exit (no console)")
    parser.add_argument("--export", action="store_true", help="With --once: export last recording without recording again")
    args = parser.parse_args(argv)
    if args.export and args.once is None:
        parser.error("--export requires --once LABEL; use d [label] in the console")
    try:
        import serial
    except ImportError:
        parser.error("pyserial is missing. Launch with tools/record-monitor.ps1 using PlatformIO's Python.")
    port = serial.Serial(port=None, baudrate=115200, timeout=.2, write_timeout=2)
    port.dtr = port.rts = False
    port.port = args.port
    try:
        port.open()
        root = args.folder.resolve()
        print(f"Recording console connected to {args.port}. Save folder: {root}", flush=True)
        print("Record for 3 seconds; r also plays those 3 seconds on the ESP32 speaker, then saves.")
        print("Saving takes about 5 seconds. m records/saves without speaker playback.")
        if args.once is not None:
            capture_once(port, root, args.once, record=not args.export)
            return 0
        print(HELP)
        print("Type a command and press Enter. Wait for SAVED before entering another command.")
        while True:
            try:
                command, label = parse_command(input("record> "))
            except ValueError as error:
                print(error)
                continue
            if command == "q":
                return 0
            if command in (None, "help", "?"):
                if command:
                    print(HELP)
                continue
            try:
                capture_once(port, root, label, record=command in ("m", "r"), playback=command == "r")
            except RuntimeError as error:
                print(f"ERROR: {error}")
                # A timeout can leave late serial bytes queued. Never replay m
                # automatically; the user controls every new recording.
                print("Wait for the ESP32 to finish before retrying. Use d to retry exporting its last recording.")
    except (EOFError, KeyboardInterrupt):
        print("\nRecording console closed.")
        return 0
    except (serial.SerialException, OSError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        print(f"Close the IDE/PlatformIO serial monitor and check {args.port}, then run again.", file=sys.stderr)
        return 1
    finally:
        if port.is_open:
            port.close()


if __name__ == "__main__":
    raise SystemExit(main())
