"""Check required checkout resources and conflicting planned GPIO assignments."""

import json
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    required = (
        "AGENTS.md",
        "CONTEXT.md",
        "docs/project_brief.md",
        "docs/architecture.md",
        "docs/status.md",
        "docs/agent_workflow.md",
        "docs/experiment_implementation_checklist.md",
        "docs/test_procedures.md",
        "contracts/v2/default_profile.json",
        "contracts/AGENTS.md",
        "firmware/AGENTS.md",
        "testbed/AGENTS.md",
        "testbed/frontend/AGENTS.md",
        "testbed/pyproject.toml",
        "testbed/uv.lock",
        "testbed/frontend/package-lock.json",
        "firmware/lora_node/main/lora_node.c",
        "firmware/lora_node/sdkconfig.defaults",
        "firmware/lora_node/main/platform/esp32_platform.c",
        "firmware/lora_node/main/platform/esp32_platform.h",
        "firmware/lora_node/main/transport/usb_transport.c",
        "firmware/lora_node/main/transport/usb_transport.h",
        "firmware/lora_node/main/control/node_control.c",
        "firmware/lora_node/main/control/node_control.h",
        "firmware/lora_node/main/protocol/strict_json.c",
        "firmware/lora_node/main/protocol/strict_json.h",
        "firmware/lora_node/main/generated/contract_schema.h",
        "firmware/diagnostic/main/contract_schema.h",
        "hardware/reference/node-wiring.png",
        "hardware/reference/node-wiring.mmd",
    )
    errors = [f"Missing {name}" for name in required if not (root / name).is_file()]
    board = json.loads(
        (root / "hardware/boards/heltec_wifi_lora32_v4.json").read_text()
    )
    pins = list(board["microphone"]["gpio"].values())
    pins += list(board["amplifier"]["gpio"].values()) + [board["ptt"]["gpio"]]
    reserved = set()
    for group in board["onboard"].values():
        reserved.update(group.values())
    if len(pins) != len(set(pins)) or set(pins) & reserved:
        errors.append(
            "External GPIO assignments duplicate a signal or conflict with onboard pins"
        )
    if board["gnss"]["enabled"]:
        errors.append(
            "Audio profile shares GNSS pins: GNSS must remain disabled and disconnected"
        )
    if board["status"] != "planned_not_hardware_validated":
        errors.append("Planning profile must not imply physical validation")
    if errors:
        print("\n".join(errors))
        return 1
    print("Repository resources and planned GPIO assignments check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
