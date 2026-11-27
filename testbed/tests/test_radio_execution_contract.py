"""Public radio-profile checks; these fixtures never qualify a physical RF link."""

import pytest

from lora_testbed import control_v2, run_protocol_v2
from lora_testbed.adapters import NodeFailure, require_execution_compatible


def identity():
    return {
        "supported_wire_versions": [2],
        "contract_version": "2.0.0",
        "schema_sha256": control_v2.schema_digest(),
        "provenance": "hardware",
        "capabilities": {"radio": False, "resource_limits": {}},
    }


def test_control_protocol_version_does_not_enable_rf_commands():
    node = identity()
    with pytest.raises(NodeFailure, match="MISSING_CAPABILITY"):
        require_execution_compatible(node, "run.start", node["capabilities"])


def advertised():
    from lora_testbed import run_protocol_v2 as execution

    node = identity()
    node["capabilities"]["radio"] = True
    node["capabilities"]["resource_limits"]["execution"] = {
        "profile": run_protocol_v2.EXECUTION_PROFILE,
        "schema_sha256": execution.schema_digest(),
        "commands": ["config.set", "run.start", "run.stop", "run.summary"],
    }
    return node


def test_only_explicit_commands_with_matching_execution_digest_are_available():
    node = advertised()
    require_execution_compatible(node, "run.start", node["capabilities"])
    with pytest.raises(NodeFailure, match="MISSING_CAPABILITY"):
        require_execution_compatible(node, "run.arm", node["capabilities"])
    node["capabilities"]["resource_limits"]["execution"]["schema_sha256"] = "0" * 64
    with pytest.raises(NodeFailure, match="UNSUPPORTED_VERSION"):
        require_execution_compatible(node, "run.start", node["capabilities"])


def test_radio_loss_blocks_new_work_but_allows_cleanup_and_summary():
    from copy import deepcopy

    node = advertised()
    health = deepcopy(node["capabilities"])
    health["radio"] = False
    with pytest.raises(NodeFailure, match="MISSING_CAPABILITY"):
        require_execution_compatible(node, "run.start", health)
    require_execution_compatible(node, "run.stop", health)
    require_execution_compatible(node, "run.summary", health)
    with pytest.raises(NodeFailure, match="MISSING_CAPABILITY"):
        require_execution_compatible(node, "run.start", None)


@pytest.mark.parametrize(
    "error,expected",
    [
        ("radio_board_unselected", "confirmed board revision"),
        ("radio_spi_bus_setup_failed", "SPI bus"),
        ("radio_busy_timeout", "BUSY pin"),
    ],
)
def test_execution_preflight_keeps_the_live_startup_reason(error, expected):
    from copy import deepcopy

    node = advertised()
    health = deepcopy(node["capabilities"])
    health["radio"] = False
    health["radio_limits"] = {"initialization_error": error}
    with pytest.raises(NodeFailure, match=expected) as rejected:
        require_execution_compatible(node, "config.set", health)
    assert rejected.value.reason == error
    assert require_execution_compatible(node, "run.stop", health)


def test_unknown_commands_and_invalid_declarations_are_rejected():
    node = advertised()
    with pytest.raises(NodeFailure, match="UNSUPPORTED_COMMAND"):
        require_execution_compatible(node, "radio.transmit", node["capabilities"])
    node["capabilities"]["resource_limits"]["execution"]["commands"].append("run.start")
    with pytest.raises(NodeFailure, match="UNSUPPORTED_VERSION"):
        require_execution_compatible(node, "run.start", node["capabilities"])


def test_shared_lifecycle_examples_validate_without_accepting_unsupported_settings():
    import json
    from pathlib import Path

    from pydantic import ValidationError

    from lora_testbed import rf_events_v2, run_protocol_v2
    from lora_testbed.experiments_v2 import Radio

    examples = json.loads(
        (Path(__file__).resolve().parents[2] / "contracts/v2/radio_examples.json").read_text()
    )
    assert {entry["command"]["name"] for entry in examples["records"]} == set(
        run_protocol_v2.BASE_EXECUTION_COMMANDS
    )
    for entry in examples["records"]:
        command = run_protocol_v2.Command.model_validate(entry["command"])
        run_protocol_v2.RESULTS[command.name].model_validate(entry["result"])
    attempt = rf_events_v2.AttemptData.model_validate(examples["tx_attempt"])
    assert (attempt.frame_seq, attempt.frame_bytes) == (1, 56)
    assert attempt.tx_done_us > attempt.tx_command_us
    for radio in examples["rejected_configurations"]:
        with pytest.raises(ValidationError):
            Radio.model_validate(radio)


def test_exact_compact_command_sets_expand_without_enabling_normal_lab_commands():
    node = advertised()
    capabilities = node["capabilities"]
    declaration = capabilities["resource_limits"]["execution"]
    declaration["commands"] = "base"
    assert "run.start" in require_execution_compatible(node, "run.start", capabilities).commands
    with pytest.raises(NodeFailure, match="MISSING_CAPABILITY"):
        require_execution_compatible(node, "fault.set", capabilities)
    declaration["commands"] = "lab"
    with pytest.raises(NodeFailure, match="MISSING_CAPABILITY"):
        require_execution_compatible(node, "fault.set", capabilities)
    capabilities["fault_injection"] = True
    assert "fault.set" in require_execution_compatible(node, "fault.set", capabilities).commands
    declaration["commands"] = "unknown"
    with pytest.raises(NodeFailure, match="UNSUPPORTED_VERSION"):
        require_execution_compatible(node, "run.start", capabilities)
