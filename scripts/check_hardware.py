"""Explicit opt-in single-board acceptance check; disconnect its dashboard slot first."""

import argparse
import asyncio
import json
from pathlib import Path

from lora_testbed.nodes import NodeSession


async def check(args):
    events = []
    node = NodeSession("A", lambda role, event: events.append(event))
    try:
        await node.connect(args.port)
        if node.identity.device_id != args.device_id:
            raise ValueError("Attached device identity differs from the explicitly selected board")
        checks = {"identity": True, "schema_match": True}
        initial_framing_errors = node.framing_errors
        for name, arguments, expected in [
            ("status.get", {"unexpected": True}, "INVALID_ARGUMENT"),
            ("unknown.command", {}, "UNSUPPORTED_COMMAND"),
            ("run.prepare", {}, "MISSING_CAPABILITY"),
        ]:
            try:
                await node.request(name, arguments)
                raise AssertionError(f"{name} was unexpectedly accepted")
            except ValueError as exc:
                assert expected in str(exc), str(exc)
                checks[expected.lower()] = True
        async with node.command_lock:
            await asyncio.to_thread(node.serial.write, b"x" * 5000 + b"\n[]\n\xff\n")
        await node.request("status.get")
        checks["malformed_input_resynchronization"] = True
        await asyncio.sleep(args.seconds)
        snapshot = node.snapshot()
        assert node.connected and len(events) >= max(2, args.seconds - 2)
        assert (
            snapshot["event_gaps"] == 0 and snapshot["framing_errors"] == initial_framing_errors
        ), {
            "initial_framing_errors": initial_framing_errors,
            "event_gaps": snapshot["event_gaps"],
            "framing_errors": snapshot["framing_errors"],
            "diagnostics": snapshot["diagnostics"],
        }
        assert node.health.telemetry_drops == 0
        checks["live_health"] = True
        checks["no_event_gaps"] = True
        report = {
            "device": node.identity.model_dump(),
            "checks": checks,
            "startup_framing_diagnostics": node.startup_records,
            "measurement_event_gaps": snapshot["event_gaps"],
            "measurement_framing_errors": snapshot["framing_errors"] - initial_framing_errors,
            "sample_count": len(events),
            "last_health": node.health.model_dump(),
            "events": events,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "device_id": node.identity.device_id,
                    "checks": checks,
                    "sample_count": len(events),
                    "report": str(args.report),
                },
                indent=2,
            )
        )
    finally:
        await node.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--seconds", type=int, default=15)
    parser.add_argument("--report", type=Path, default=Path("data/hardware-check.json"))
    arguments = parser.parse_args()
    if not 3 <= arguments.seconds <= 300:
        parser.error("--seconds must be between 3 and 300")
    asyncio.run(check(arguments))
