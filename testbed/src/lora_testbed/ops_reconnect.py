"""Review owned node interruptions and recovery from durable radio evidence."""

from .experiments_v2 import known_data

MAX_RECOVERY_SECONDS = 5


def reference(spec, case):
    selected = spec.ops_reset_evidence if case["group"] == "C2" else spec.ops_usb_evidence
    return next(
        (
            item
            for item in selected or ()
            if (item.target_role, item.direction, item.repetition)
            == (case["target_role"], case["direction"], case["repetition"])
        ),
        None,
    )


def blockers(radio, reference, procedures):
    if reference is None:
        return ["Attach the interrupted and fresh known-data radio runs"]
    try:
        old, new = (
            radio.get(identifier) for identifier in (reference.interrupted, reference.recovery)
        )
    except ValueError as exc:
        return [str(exc)]
    if (old["status"], new["status"]) != ("interrupted", "completed"):
        return ["Provide an interrupted radio run and a completed recovery"]
    if proof := getattr(reference, "stale_boot_procedure", None):
        if procedures.get(proof) is None:
            return ["The saved stale-boot procedure is unavailable"]
    return []


def archived_radio(radio, run):
    wire = run.get("saved_files", {}).get("wire") or {}
    if (
        not wire.get("length_bytes")
        or not wire.get("sha256")
        or wire["sha256"] != run.get("wire_sha256")
    ):
        raise ValueError("The recorded serial evidence is incomplete")
    radio.content(run["id"], "wire")


def verify_saved_known_data(radio, child):
    spec = child["plan"]["spec"]
    size = spec["message_bytes"]
    if spec["source"] != "known_data" or not 1 <= size <= 65536:
        raise ValueError("Use a bounded known-data radio transfer")
    expected = known_data(spec["source_seed"], 1, size)
    for kind in ("source", "recovered"):
        with radio.content(child["id"], kind).open("rb") as stream:
            if stream.read(size + 1) != expected:
                raise ValueError("Recovery bytes differ from the saved known-data recipe")


def assess(host, item):
    radio = host.radio
    old, new = (radio.get(identifier) for identifier in (item.interrupted, item.recovery))
    target = item.target_role
    peer = "B" if target == "A" else "A"
    prior, fresh = old["physical_bindings"], new["physical_bindings"]
    failures = old.get("connection_failures") or {}
    fault = failures.get(target) or {}
    reset = getattr(item, "stale_boot_procedure", None)
    valid_fault = fault.get("kind") == "serial_io" or (
        reset
        and fault.get("kind") == "identity_change"
        and fault["observed_device_id"] == fresh[target]["device_id"]
        and fault["observed_boot_id"] == fresh[target]["boot_id"]
    )
    if (
        old["status"] != "interrupted"
        or old["failure_stage"] != "transmitting"
        or set(failures) != {target}
        or not valid_fault
        or fault["connection_id"] != prior[target]["connection_id"]
    ):
        raise ValueError(
            "A matching interruption on the selected role during transmission is required"
        )
    elapsed = old["cleanup_completed_monotonic_ns"] - fault["host_monotonic_ns"]
    peer_cleanup = old["cleanup"]["details"][peer]
    if (
        not 0 <= elapsed <= MAX_RECOVERY_SECONDS * 1_000_000_000
        or not peer_cleanup["confirmed"]
        or not {"run stopped", "session closed", "idle confirmed"} <= set(peer_cleanup["steps"])
    ):
        raise ValueError("The continuously connected peer did not confirm bounded stop and idle")
    if (
        any(prior[role]["device_id"] != fresh[role]["device_id"] for role in "AB")
        or prior[target]["connection_id"] == fresh[target]["connection_id"]
        or prior[peer] != fresh[peer]
        or old["session_id"] == new["session_id"]
        or new["host_transaction"]["start_ns"] <= old["cleanup_completed_monotonic_ns"]
    ):
        raise ValueError("Recovery requires the same devices and a fresh connection and session")
    if (
        new["status"] != "completed"
        or old["plan"] != new["plan"]
        or new["plan"]["spec"]["direction"] != item.direction
        or not new["cleanup"]["confirmed"]
        or not (new.get("verification") or {}).get("bytes_equal")
        or not (new.get("accounting") or {}).get("evidence_complete")
    ):
        raise ValueError("Fresh recovery requires a completed transfer with the matched settings")
    for child in (old, new):
        archived_radio(radio, child)
    verify_saved_known_data(radio, new)
    reset_proof = (
        verify_reset(host.procedures, reset, target, prior, fresh, old, new) if reset else {}
    )
    return {
        "fault": fault,
        "target_role": target,
        "peer_role": peer,
        "stop_bound_s": MAX_RECOVERY_SECONDS,
        "fault_to_cleanup_ms": elapsed / 1_000_000,
        "peer_cleanup": peer_cleanup,
        "faulted_cleanup": old["cleanup"]["details"][target],
        "faulted_radio_run": old["id"],
        "original_error": old["error"],
        "recovery_radio_run": new["id"],
        "bindings_before": prior,
        "bindings_after": fresh,
        "run_deadline_ms": new["plan"]["spec"]["max_duration_ms"],
        "verification": new["verification"],
        **reset_proof,
    }


def verify_reset(procedures, identifier, target, prior, fresh, old, new):
    if prior[target]["boot_id"] == fresh[target]["boot_id"]:
        raise ValueError("Board reset requires a new boot of the same device")
    old_key_set, new_key_set = (run["security"].get("key_set_id") for run in (old, new))
    if (
        not old_key_set
        or not new_key_set
        or old_key_set == new_key_set
        or any(
            run["security"]["profile"] != "aes128_gcm"
            or not run["security"]["keys_retired_on_host"]
            or set(run["security"]["provisioned"]) != {"A", "B"}
            for run in (old, new)
        )
    ):
        raise ValueError("Board reset requires independently provisioned protected sessions")
    proof = procedures.get(identifier)
    if (
        not proof
        or proof["catalog_id"] != "IF-01"
        or proof["status"] != "completed"
        or proof["physical_bindings"].get(target) != fresh[target]
        or not old["finished_at"]
        <= proof["created_at"]
        <= proof["finished_at"]
        <= new["created_at"]
    ):
        raise ValueError("Run the stale-boot check on the reconnected role before recovery")
    case = next(
        (
            row
            for row in proof["cases"]
            if row["variant"] == "stale_boot"
            and row["role"] == target
            and row["assessment"] == "pass"
            and row["cleanup_verified"]
        ),
        None,
    )
    if not case:
        raise ValueError("The reconnected node must pass the stale-boot check")
    observations = [row["document"] for row in procedures.evidence(identifier, case_id=case["id"])]
    assert_stale_boot_trace(observations, prior[target], fresh[target])
    return {
        "reset_proof": {
            "procedure_id": identifier,
            "case_id": case["id"],
            "old_boot_id": prior[target]["boot_id"],
            "new_boot_id": fresh[target]["boot_id"],
            "old_key_set_id": old_key_set,
            "new_key_set_id": new_key_set,
            "stale_boot_rejected": True,
            "idle_without_session_or_keys": True,
        }
    }


def assert_stale_boot_trace(observations, prior, fresh):
    binding = {
        edge: {key: value for key, value in item.items() if key != "role"}
        for edge, item in (("previous_boot", prior), ("current_boot", fresh))
    }
    summary = next(
        (
            row
            for row in observations
            if row.get("observed_error") == "STALE_BOOT"
            and all(row.get(key) == value for key, value in binding.items())
        ),
        None,
    )
    sent = [row["record"] for row in observations if row.get("direction") == "host_to_node"]
    stale_commands = {
        row["command_id"]
        for row in sent
        if row["name"] == "diag.run" and row["target_boot_id"] == prior["boot_id"]
    }
    idle_commands = {row["command_id"] for row in sent if row["name"] == "status.get"}
    replies = [
        row["record"]
        for row in observations
        if row.get("direction") == "node_to_host"
        and (row["record"]["device_id"], row["record"]["boot_id"])
        == (fresh["device_id"], fresh["boot_id"])
    ]
    rejected = any(
        row["command_id"] in stale_commands
        and not row["ok"]
        and row["error"]["code"] == "STALE_BOOT"
        and row["error"]["field"] == "target_boot_id"
        for row in replies
    )
    statuses = [
        row["result"] for row in replies if row["command_id"] in idle_commands and row["ok"]
    ]
    idle = bool(statuses) and all(
        row["state"] == "idle"
        and row["run_id"] is None
        and row["operation_id"] is None
        and row["security_ready"] is False
        for row in statuses
    )
    if not summary or summary["unexpected_operation_ids"] or not rejected or not idle:
        raise ValueError("Retained replies must show stale-boot rejection and idle, unkeyed state")
