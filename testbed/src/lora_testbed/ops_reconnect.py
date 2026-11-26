"""Review owned node interruptions and recovery from durable radio evidence."""

from .experiments_v2 import known_data

MAX_RECOVERY_SECONDS = 5


def reference(spec, case):
    return next(
        (
            item
            for item in spec.ops_usb_evidence or ()
            if (item.target_role, item.direction, item.repetition)
            == (case["target_role"], case["direction"], case["repetition"])
        ),
        None,
    )


def blockers(radio, reference):
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


def assess(radio, item):
    old, new = (radio.get(identifier) for identifier in (item.interrupted, item.recovery))
    target = item.target_role
    peer = "B" if target == "A" else "A"
    failures = old.get("connection_failures") or {}
    fault = failures.get(target) or {}
    if (
        old["status"] != "interrupted"
        or old["failure_stage"] != "transmitting"
        or set(failures) != {target}
        or fault["kind"] != "serial_io"
        or fault["connection_id"] != old["physical_bindings"][target]["connection_id"]
    ):
        raise ValueError(
            "A serial I/O failure on the selected role during transmission is required"
        )
    elapsed = old["cleanup_completed_monotonic_ns"] - fault["host_monotonic_ns"]
    peer_cleanup = old["cleanup"]["details"][peer]
    if (
        not 0 <= elapsed <= MAX_RECOVERY_SECONDS * 1_000_000_000
        or not peer_cleanup["confirmed"]
        or not {"run stopped", "session closed", "idle confirmed"} <= set(peer_cleanup["steps"])
    ):
        raise ValueError("The continuously connected peer did not confirm bounded stop and idle")
    prior, fresh = old["physical_bindings"], new["physical_bindings"]
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
    }
