"""Verify one or two Heltec audio benches while the serial connections stay open.

Uses pyserial from PlatformIO's Python environment. Close other serial monitors
first. Runs a 1 kHz tone per node, then one tone on both nodes together. Logs
prove firmware/serial completion only; a listener must confirm audible output.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time

import serial
from serial.tools import list_ports


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWN_NODES = {
    "8CFD49B5B78C": {"label": "Heltec-A", "assigned_port": "COM6"},
    "441BF66F99E4": {"label": "Heltec-B", "assigned_port": "COM7"},
}
DIAGNOSTICS_END = "[I2S] Frequencies above are configured targets, not measurements; MCLK disabled"
TONE_START = "[AUDIO] Playing 1 kHz speaker test tone..."
TONE_COMPLETE = "[AUDIO] Tone transfer complete; verify audible output"
MAC_PATTERN = re.compile(r"(?i)(?:[0-9a-f]{2}:){5}[0-9a-f]{2}")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def normalized_mac(value):
    return re.sub(r"[^0-9A-Fa-f]", "", value or "").upper()


def discover_nodes(ports):
    available = {item.device.upper(): item for item in list_ports.comports()}
    result = []
    seen_serials = set()
    for port_name in ports:
        device = available.get(port_name.upper())
        if device is None:
            raise RuntimeError(f"{port_name} is not a connected serial device")
        hardware_serial = normalized_mac(device.serial_number)
        if (device.vid, device.pid) != (0x303A, 0x1001):
            raise RuntimeError(f"{port_name} is not the expected Espressif USB Serial/JTAG device")
        if hardware_serial not in KNOWN_NODES:
            raise RuntimeError(f"{port_name} has an unrecognized USB serial: {device.serial_number}")
        if hardware_serial in seen_serials:
            raise RuntimeError("Both selected ports must refer to different boards")
        seen_serials.add(hardware_serial)
        node = KNOWN_NODES[hardware_serial]
        result.append({
            "port": device.device,
            "label": node["label"],
            "assigned_port": node["assigned_port"],
            "port_matches_assignment": device.device.upper() == node["assigned_port"],
            "usb_serial": device.serial_number,
            "mac_normalized": hardware_serial,
            "description": device.description,
            "hardware_id": device.hwid,
        })
    return result


class Connection:
    def __init__(self, node, folder):
        self.node = node
        self.port = serial.Serial(port=None, baudrate=115200, timeout=0, write_timeout=2)
        self.port.dtr = False
        self.port.rts = False
        self.port.port = node["port"]
        # COM6.log is still a reserved Windows device name, not a disk file.
        # Prefix every sanitized port name so logging cannot address a device
        # or escape the selected output directory.
        safe_port = re.sub(r"[^A-Za-z0-9_-]", "_", node["port"])[:80] or "port"
        node["log_file"] = f"serial-{safe_port}.log"
        self.log = (folder / node["log_file"]).open("x", encoding="utf-8")
        self.pending = bytearray()
        self.received_bytes = 0

    def note(self, message):
        self.log.write(f"{utc_now()} {message}\n")
        self.log.flush()

    def open(self):
        self.port.open()
        self.note(f"OPEN {self.node['label']} at 115200 baud; DTR=0 RTS=0")

    def send(self, command, stage):
        sent_at = utc_now()
        self.note(f"TX stage={stage} command={command!r}")
        payload = (command + "\n").encode("ascii")
        written = self.port.write(payload)
        if written != len(payload):
            raise RuntimeError(f"{self.node['port']}: short serial write")
        return sent_at

    def read_lines(self):
        size = self.port.in_waiting
        if not size:
            return []
        data = self.port.read(min(size, 8192))
        self.received_bytes += len(data)
        if self.received_bytes > 2 * 1024 * 1024:
            raise RuntimeError(f"{self.node['port']}: excessive serial output")
        self.pending.extend(data)
        lines = []
        while b"\n" in self.pending:
            raw, _, rest = self.pending.partition(b"\n")
            self.pending = bytearray(rest)
            line = raw.decode("utf-8", errors="replace").rstrip("\r")
            self.note("RX " + line)
            lines.append(line)
        if len(self.pending) > 16384:
            raise RuntimeError(f"{self.node['port']}: unterminated serial line")
        return lines

    def close(self):
        try:
            if self.port.is_open:
                self.port.close()
                self.note("CLOSE")
            if self.pending:
                self.note("RX partial: " + self.pending.decode("utf-8", errors="replace"))
        finally:
            self.log.close()


def drain(connections, duration=0.3):
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        for connection in connections:
            connection.read_lines()
        time.sleep(0.01)


def validate_identity(connection, lines):
    text = "\n".join(lines)
    observed_macs = {normalized_mac(mac) for mac in MAC_PATTERN.findall(text)}
    expected_mac = connection.node["mac_normalized"]
    if expected_mac not in observed_macs:
        raise RuntimeError(f"{connection.node['port']}: firmware MAC did not match USB hardware identity")
    required = (
        "[I2S] MIC requested=1 ready=1, SPK requested=1 ready=1",
        "[I2S] MIC BCLK=4 WS=6 SD=38,",
        "[I2S] SPK BCLK=40 LRC=41 DIN=47,",
        "[AMP] SD/MODE=GPIO48;",
    )
    for marker in required:
        if marker not in text:
            raise RuntimeError(f"{connection.node['port']}: missing expected diagnostic: {marker}")


def run_stage(connections, targets, command, name, summary, timeout=8.0):
    # Drain prior output, then require the new command's start marker before
    # accepting a completion. Tone completion must also be followed by IDLE.
    drain(connections)
    stage = {"name": name, "command": command, "started_at": utc_now(), "ports": {}}
    summary["stages"].append(stage)
    active = {connection.node["port"]: connection for connection in targets}
    for port_name, connection in active.items():
        stage["ports"][port_name] = {
            "label": connection.node["label"], "sent_at": None,
            "started": False, "transfer_complete": False, "passed": False,
            "finished": False, "diagnostics": [],
        }
    # All writes are issued before collecting responses; reads below service
    # both handles, including the node not targeted by an individual tone.
    write_times = []
    for port_name, connection in active.items():
        write_times.append(time.monotonic())
        stage["ports"][port_name]["sent_at"] = connection.send(command, name)
    stage["command_dispatch_span_ms"] = round((max(write_times) - min(write_times)) * 1000, 3)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for connection in connections:
            port_name = connection.node["port"]
            for line in connection.read_lines():
                if port_name not in active:
                    continue
                state = stage["ports"][port_name]
                if state["finished"]:
                    continue
                if "FAILED" in line or "Guru Meditation" in line or "panic" in line.lower():
                    if command in ("i", "v"):
                        state.setdefault("error_lines", []).append(line)
                    else:
                        raise RuntimeError(f"{port_name}: {line}")
                if command == "i":
                    if line == "[SYSTEM]":
                        state["started"] = True
                    if state["started"]:
                        state["diagnostics"].append(line)
                    if state["started"] and line == DIAGNOSTICS_END:
                        # Finish collecting every node's diagnostics even if
                        # one node is unhealthy; both are needed to debug it.
                        try:
                            if state.get("error_lines"):
                                raise RuntimeError(f"{port_name}: " + "; ".join(state["error_lines"]))
                            validate_identity(connection, state["diagnostics"])
                        except RuntimeError as exc:
                            state["error"] = str(exc)
                            print(f"{port_name} {connection.node['label']}: identity/readiness FAIL: {exc}", flush=True)
                        else:
                            state["passed"] = True
                            print(f"{port_name} {connection.node['label']}: identity and Rev B I2S readiness PASS", flush=True)
                        state["finished"] = True
                        state["completed_at"] = utc_now()
                elif command == "v":
                    if line == "[PINS] BEGIN":
                        state["started"] = True
                    if state["started"]:
                        state["diagnostics"].append(line)
                        if line.startswith("[PINS]"):
                            print(f"{port_name}: {line}", flush=True)
                        if line.startswith("[PINS] ERROR:"):
                            state.setdefault("error_lines", []).append(line)
                    if state["started"] and line == "[PINS] END":
                        state["finished"] = True
                        state["completed_at"] = utc_now()
                        if state.get("error_lines"):
                            state["error"] = f"{port_name}: " + "; ".join(state["error_lines"])
                        else:
                            state["passed"] = True  # Probe completed, not audible-output verification.
                else:
                    if line == TONE_START:
                        state["started"] = True
                    elif line == TONE_COMPLETE and state["started"]:
                        state["transfer_complete"] = True
                    elif line == "[STATE] IDLE" and state["transfer_complete"]:
                        state["passed"] = True
                        state["finished"] = True
                        state["completed_at"] = utc_now()
                        print(f"{port_name} {connection.node['label']}: {name} digital transfer PASS", flush=True)
        if all(state["finished"] for state in stage["ports"].values()):
            stage["completed_at"] = utc_now()
            failures = [state["error"] for state in stage["ports"].values() if "error" in state]
            if failures:
                raise RuntimeError("; ".join(failures))
            return
        time.sleep(0.01)
    waiting = [port for port, state in stage["ports"].items() if not state["finished"]]
    raise RuntimeError(f"Stage {name} timed out waiting for: {', '.join(waiting)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ports", nargs="+", default=["COM6", "COM7"], metavar="PORT",
                        help="One or two ports; defaults to COM6 COM7")
    parser.add_argument("--output-dir", type=Path, help="New directory for logs and summary; must not already exist")
    parser.add_argument("--identify-only", action="store_true", help="Check both connections, identity and readiness without tones")
    parser.add_argument("--probe-pins", action="store_true",
                        help="Collect speaker clock and enable-pin measurements using firmware command v")
    parser.add_argument("--tone-repetitions", type=int, choices=range(1, 11), default=1,
                        metavar="1-10", help="Individual tones per node before the paired test")
    parser.add_argument("--tone-seconds", type=int, choices=(1, 15), default=1,
                        help="Continuous tone duration; 15 seconds allows oscilloscope capture")
    args = parser.parse_args(argv)
    if len(args.ports) not in (1, 2):
        parser.error("Select one or two ports")
    tone_command = "b" if args.tone_seconds == 15 else "s"
    tone_timeout = args.tone_seconds + 8
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    folder = args.output_dir or PROJECT_ROOT / "captures" / f"{stamp}-heltec-speaker-bench"
    folder.mkdir(parents=True, exist_ok=False)
    summary = {
        "started_at": utc_now(), "requested_ports": args.ports,
        "identify_only": args.identify_only, "nodes": [], "stages": [],
        "tone_repetitions": args.tone_repetitions,
        "tone_seconds": args.tone_seconds,
        "probe_pins": args.probe_pins,
        "both_connections_open_together": False, "software_passed": False,
        "audible_output": "Not automatically verified; listener confirmation required",
    }
    connections = []
    result = 1
    try:
        summary["nodes"] = discover_nodes(args.ports)
        for node in summary["nodes"]:
            print(f"{node['label']}: {node['port']}, USB serial {node['usb_serial']}", flush=True)
            if not node["port_matches_assignment"]:
                print(f"  Port changed from recorded {node['assigned_port']}; identity follows hardware MAC.", flush=True)
            connection = Connection(node, folder)
            connections.append(connection)
            connection.open()
        summary["both_connections_open_together"] = (
            len(connections) == 2 and all(connection.port.is_open for connection in connections))
        drain(connections, duration=1.5)
        run_stage(connections, connections, "i", "identity_and_readiness", summary)
        if args.probe_pins:
            run_stage(connections, connections, "v", "speaker_pin_probe", summary)
        if not args.identify_only:
            for connection in connections:
                port_name = connection.node["port"]
                for repetition in range(args.tone_repetitions):
                    print(f"Playing {args.tone_seconds}-second 1 kHz tone {repetition + 1}/{args.tone_repetitions} on "
                          f"{connection.node['label']} ({port_name})...", flush=True)
                    stage = f"individual_{port_name}"
                    if args.tone_repetitions > 1:
                        stage += f"_{repetition + 1}"
                    run_stage(connections, [connection], tone_command, stage, summary, timeout=tone_timeout)
                    drain(connections, duration=0.8)
            if len(connections) == 2:
                print(f"Playing a {args.tone_seconds}-second 1 kHz tone on both nodes together...", flush=True)
                run_stage(connections, connections, tone_command, "paired_tones", summary, timeout=tone_timeout)
        summary["software_passed"] = True
        result = 0
    except (OSError, RuntimeError, serial.SerialException) as exc:
        summary["error"] = str(exc)
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        summary["error"] = "Interrupted by user"
        result = 130
    finally:
        close_errors = []
        for connection in connections:
            try:
                connection.close()
            except (OSError, serial.SerialException) as exc:
                close_errors.append(str(exc))
        if close_errors:
            summary["close_errors"] = close_errors
            summary["software_passed"] = False
            result = 1
        summary["finished_at"] = utc_now()
        summary["connections_closed"] = all(not connection.port.is_open for connection in connections)
        (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Logs and summary: {folder.resolve()}", flush=True)
    if result == 0:
        print(f"PASS: {len(connections)} serial connection(s) stayed open and all requested firmware checks completed.", flush=True)
        if not args.identify_only:
            print("Audible output still requires listener confirmation.", flush=True)
    return result


if __name__ == "__main__":
    sys.exit(main())
