"""Execute grouped integration cases through the shared physical services."""

import asyncio
import hashlib
from copy import deepcopy
from uuid import uuid4

from . import (
    content_series,
    crypto_benchmark_v2,
    fault_accounting,
    fault_matrices,
    local_voice,
    memory_matrix,
    memory_observation_v2,
    model_series,
    ops_matrix,
    rf_sweeps,
    serial_compatibility,
    serial_framing,
    serial_replies,
    sustained_voice,
    timed_series,
    v2,
    voice_matrix,
)
from .experiments_v2 import known_data
from .integration_matrices import campaign_intent, compile_matrix, link_request
from .nodes import NodeSession
from .paths import REPOSITORY_ROOT
from .physical_campaign_evidence import verify_campaign_bundle
from .radio_runs import (
    KeyMismatchRunRequest,
    LabRadioRunRequest,
    PeerMismatchCheck,
    PeerProfileMismatchCheck,
    PrepareLimitCheck,
    RadioRunRequest,
)
from .storage import utc_now

SERIAL_ERROR_CASES = {
    "invalid_argument": ("status.get", {"unrecognized_parameter": True}, "INVALID_ARGUMENT"),
    "unknown_command": ("validation.unsupported", {}, "UNSUPPORTED_COMMAND"),
    "known_unavailable": ("clock.arm", {}, "MISSING_CAPABILITY"),
}


class IntegrationExecution:
    def __init__(self, ledger):
        self.ledger = ledger

    @staticmethod
    def message_limit(radio):
        values = []
        for node in radio.nodes.values():
            if not node.connected or node.health is None:
                return None
            limits = node.health.capability_availability.resource_limits.get("execution_limits", {})
            maximum = limits.get("max_message_bytes")
            if type(maximum) is not int or not 1 <= maximum <= 65536:
                return None
            values.append(maximum)
        return min(values) if values else None

    def preview(self, spec, radio, voice=None, campaigns=None):
        limit = self.message_limit(radio) if spec.catalog_id in ("PKT-01", "MEM-01") else None
        plan = compile_matrix(spec, message_limit=limit or 65536)
        rows = []
        for case in plan["cases"]:
            if case["driver"] in (
                "known_data_batch",
                "peer_mismatch",
                "rf_sweep",
                "content_series",
            ):
                blockers = radio.preflight(link_request(spec, case, 0))["blockers"]
                if case.get("echo_count"):
                    case["echo_blockers"] = radio.preflight(rf_sweeps.echo_request(spec, case))[
                        "blockers"
                    ]
            elif case["driver"] == "content_negative":
                control = content_series.run_request(spec, case, 0)
                request = (
                    KeyMismatchRunRequest(**control.model_dump())
                    if case["variant"] == "wrong_key"
                    else control
                )
                blockers = radio.preflight(request)["blockers"]
            elif case["driver"] == "ops_campaign":
                blockers = ops_matrix.ready_blockers(spec, case, campaigns)
            elif case["driver"] == "ops_unavailable":
                blockers = [ops_matrix.BLOCKERS[case["group"]]]
            elif case["driver"] in ("local_voice_reference", "local_voice_operator"):
                blockers = local_voice.blockers(voice, case)
            elif case["driver"] in ("voice_reference", "voice_operator"):
                blockers = voice_matrix.blockers(voice, case)
            elif case["driver"] == "sustained_voice":
                blockers = sustained_voice.blockers(voice, case)
            elif case["driver"] == "fault_window_unavailable":
                blockers = ["The retained session cannot yet advance past the replay window"]
            elif case["driver"] == "fault_series":
                request = fault_matrices.selected_request(spec, case, case["target_ordinal"] - 1)
                blockers = radio.preflight(request)["blockers"]
            elif case["driver"] == "model_reference":
                blockers = []
            elif case["driver"] == "model_frame":
                blockers = radio.preflight(model_series.link_request(spec, case, 0))["blockers"]
            elif case["driver"] == "model_message":
                blockers = radio.preflight(model_series.message_request(spec, case, 0))["blockers"]
            elif case["driver"] == "memory_audio_pair":
                blockers = [
                    blocker
                    for role in ("A", "B")
                    for blocker in memory_matrix.role_blockers(self.ledger.nodes[role], role)
                ]
                if set(spec.roles) != {"A", "B"}:
                    blockers.append("Select both roles for paired audio memory")
                elif voice is None:
                    blockers.append("Paired audio preflight is unavailable")
                else:
                    blockers.extend(
                        voice.preflight(memory_matrix.paired_audio_request(case))["blockers"]
                    )
            elif case["driver"] == "memory_audio_local":
                role = case["role"]
                blockers = memory_matrix.local_audio_blockers(
                    self.ledger.nodes[role], role, case["variant"]
                )
            elif case["driver"] == "resource_refusal":
                blockers = (
                    ["Connect both nodes to establish the negotiated message limit"]
                    if limit is None
                    else radio.preflight(self.resource_control_request(case))["blockers"]
                )
            elif case["driver"] == "memory_recovery":
                blockers = [
                    blocker
                    for role in ("A", "B")
                    for blocker in memory_matrix.role_blockers(self.ledger.nodes[role], role)
                ]
                blockers.extend(radio.preflight(memory_matrix.recovery_request(case))["blockers"])
            elif case["driver"] == "memory_idle":
                role = case["role"]
                blockers = memory_matrix.role_blockers(self.ledger.nodes[role], role)
            elif case["driver"] == "memory_link":
                blockers = [
                    blocker
                    for role in ("A", "B")
                    for blocker in memory_matrix.role_blockers(self.ledger.nodes[role], role)
                ]
                if limit is None:
                    blockers.append("Connect both nodes to establish the negotiated memory limit")
                else:
                    blockers.extend(
                        radio.preflight(memory_matrix.link_request(spec, case))["blockers"]
                    )
            elif case["driver"] == "echo_batch":
                blockers = radio.preflight(timed_series.echo_request(spec, case))["blockers"]
            elif case["driver"] == "echo_timeout_fixture":
                blockers = radio.preflight(timed_series.echo_timeout_request(spec, case))[
                    "blockers"
                ]
            elif case["driver"] == "local_crypto":
                blockers = timed_series.crypto_blockers(self.ledger.nodes[case["role"]])
            elif case["driver"] == "serial_matrix":
                blockers = []
                node = self.ledger.nodes[case["role"]]
                if node.connected and case["transport"] != node.control_transport():
                    blockers.append(
                        f"Node {case['role']} must advertise transport {case['transport']}"
                    )
                if case["variant"] not in {
                    "valid_control_cycles",
                    "configuration_unchanged",
                    "competing_claim",
                    "lease_recovery",
                    "health_silence",
                    "conflicting_identity",
                    "stale_boot",
                    *serial_replies.VARIANTS,
                    *serial_compatibility.INCOMPATIBILITIES,
                    *SERIAL_ERROR_CASES,
                    *serial_framing.VARIANTS,
                }:
                    blockers.append("The required framing or serial fault fixture is unavailable")
                if (
                    not node.connected
                    or node.wire_profile != "node_control"
                    or not node.health
                    or node.health.node_role != case["role"]
                    or node.health.state != "idle"
                    or node.snapshot()["connection_state"] != "connected"
                ):
                    blockers.append(
                        f"Node {case['role']} needs a healthy owned main-control connection"
                    )
                if case["variant"] == "configuration_unchanged" and (
                    blocker := node.configuration_probe_blocker()
                ):
                    blockers.append(blocker)
                if case["variant"] in serial_replies.VARIANTS and (
                    not node.health
                    or "memory_probe"
                    not in node.health.capability_availability.resource_limits.get("diag_kinds", ())
                ):
                    blockers.append("Reply perturbation requires the bounded memory probe")
                if case["variant"] == "stale_boot" and not node.previous_boot_binding:
                    blockers.append("Connect the same device before and after a reset")
            elif case["group"] in ("C1", "C2", "C3", "C4", "C7", "C8"):
                blockers = radio.preflight(
                    link_request(
                        spec, {"direction": "A_TO_B", "message_bytes": 64, "repetition": 1}, 0
                    )
                )["blockers"]
            else:
                blockers = ["The selected campaign fixture or operator action is unavailable"]
            rows.append({**case, "blockers": blockers, "ready": not blockers})
        return {
            **plan,
            "cases": rows,
            "ready_case_count": sum(case["ready"] for case in rows),
            "scope": "grouped integration cases; qualification is a separate review",
            "hardware_validated": False,
        }

    async def start(self, spec, host, expected_plan_sha256=None):
        radio, adapter = host.radio, host.adapter
        if self.ledger.busy:
            raise RuntimeError("Another procedure owns the bench")
        planned = self.preview(spec, radio, host.voice, host.campaign_plans)
        if expected_plan_sha256 is not None and planned["sha256"] != expected_plan_sha256:
            raise RuntimeError("The matrix plan changed. Preview the cases again.")
        if not planned["ready_case_count"]:
            raise ValueError("No selected matrix cases can run on this bench")
        ready_cases = [case for case in planned["cases"] if case["ready"]]
        local_drivers = {
            "serial_matrix",
            "local_crypto",
            "memory_idle",
            "memory_audio_local",
            "model_reference",
            "local_voice_reference",
        }
        local_only = all(case["driver"] in local_drivers for case in ready_cases)
        numerical_only = all(case["driver"] == "model_reference" for case in ready_cases)
        required = (
            {case["role"] for case in ready_cases if case["role"] in ("A", "B")}
            if local_only
            else set(spec.roles)
        )
        transports = {
            role: self.ledger.nodes[role].control_transport() for role in sorted(required)
        }
        labels = {"native_usb": "native USB Serial/JTAG", "uart": "UART0 115200 8N1"}
        transport = (
            " and ".join(
                sorted({labels.get(value, "physical serial") for value in transports.values()})
            )
            if transports
            else "no device"
        )
        if not local_only:
            transport += " and owned radio runs"
        run = {
            **planned,
            "id": str(uuid4()),
            "mode": "numerical" if numerical_only else "hardware",
            "status": "running",
            "assessment": "not_assessed",
            "created_at": utc_now(),
            "finished_at": None,
            "reason": None,
            "active_case": None,
            "roles": spec.roles,
            "source_sha256": {
                source: hashlib.sha256((REPOSITORY_ROOT / source).read_bytes()).hexdigest()
                for source in (
                    "docs/test_procedures.md",
                    "testbed/src/lora_testbed/integration_matrices.py",
                    "testbed/src/lora_testbed/integration_execution.py",
                    "testbed/src/lora_testbed/rf_sweeps.py",
                    "testbed/src/lora_testbed/content_series.py",
                    "testbed/src/lora_testbed/timed_series.py",
                    "testbed/src/lora_testbed/memory_matrix.py",
                    "testbed/src/lora_testbed/model_series.py",
                    "testbed/src/lora_testbed/fault_matrices.py",
                    "testbed/src/lora_testbed/fault_accounting.py",
                    "testbed/src/lora_testbed/lab_trials.py",
                    "testbed/src/lora_testbed/voice_matrix.py",
                    "testbed/src/lora_testbed/local_voice.py",
                    "testbed/src/lora_testbed/node_audio.py",
                    "testbed/src/lora_testbed/voice_runs.py",
                    "testbed/src/lora_testbed/ops_matrix.py",
                    "testbed/src/lora_testbed/experiments_v2.py",
                    "testbed/src/lora_testbed/workload_observations.py",
                    "testbed/src/lora_testbed/workload_assessment.py",
                    "testbed/src/lora_testbed/echo_accounting.py",
                    "testbed/src/lora_testbed/crypto_benchmark_v2.py",
                    "testbed/src/lora_testbed/procedure_runs.py",
                    "testbed/src/lora_testbed/radio_runs.py",
                    "testbed/src/lora_testbed/nodes.py",
                    "testbed/src/lora_testbed/serial_compatibility.py",
                    "testbed/src/lora_testbed/serial_framing.py",
                    "testbed/src/lora_testbed/serial_replies.py",
                    "testbed/src/lora_testbed/campaign_plans.py",
                    "testbed/src/lora_testbed/physical_campaigns.py",
                )
            },
            "transport": transport,
            "connection_transports": transports,
            "timing_basis": "exact rational arithmetic in microseconds"
            if numerical_only
            else "per-child node-local and host-monotonic observations",
            "physical_bindings": {role: adapter.bind(role) for role in sorted(required)},
            "full_procedure_passed": False,
        }
        for case in run["cases"]:
            case.update(status="pending", assessment="not_assessed", run_ids=[], assertions=[])
        self.ledger.save(run)
        self.ledger.current = run
        self.ledger.task = asyncio.create_task(self.run(run, spec, host))
        await asyncio.sleep(0)
        return deepcopy(run)

    async def matrix_serial_case(self, run, case, adapter):
        role = case["role"]
        binding = run.get("serial_recovered_bindings", {}).get(role, run["physical_bindings"][role])
        node = adapter.current(binding)
        if node.control_transport() != case["transport"]:
            raise ValueError("Selected serial transport changed before the case")
        before = node.snapshot()

        def record(document):
            self.ledger.append(run["id"], case["id"], document)

        variant = case["variant"]
        if variant == "health_silence":
            await self.matrix_health_silence(run, case, adapter, node, binding, record)
            return
        assessed = None
        status = None
        async with asyncio.timeout(60):
            if variant in serial_framing.VARIANTS:
                baseline = await adapter.request(binding, "status.get", on_record=record)
                adapter.current(binding)
                status, boundaries = await node.exercise_serial_framing(variant, record)
                adapter.current(binding)
                assessed = serial_framing.assess_counters(variant, baseline, status)
                if (
                    boundaries
                    and boundaries["checked_boundaries"] != boundaries["expected_boundaries"]
                ):
                    assessed["outcome"] = "fail"
                record({"direction": "host_fixture", "counter_assessment": assessed})
            elif variant == "configuration_unchanged":
                baseline = await adapter.request(binding, "status.get", on_record=record)
                adapter.current(binding)
                reply = await node.exercise_configuration_rejection(record)
                status = await adapter.request(binding, "status.get", on_record=record)
                keys = ("radio", "link", "config_revision")
                prior = {key: baseline[key] for key in keys}
                latest = {key: status[key] for key in keys}
                error = reply.error.code if reply.error else None
                outcome = "pass" if error == "INVALID_ARGUMENT" and latest == prior else "fail"
                assessed = {"outcome": outcome}
                record(
                    {
                        "direction": "host_assessment",
                        "configuration_before": prior,
                        "configuration_after": latest,
                        "expected_error": "INVALID_ARGUMENT",
                        "observed_error": error,
                        "outcome": outcome,
                    }
                )
            elif variant in serial_compatibility.INCOMPATIBILITIES:
                identity = await adapter.request(binding, "hello", on_record=record)
                assessed = await self.check_incompatible_hello(node.role, identity, variant)
                record(assessed)
            elif variant in serial_replies.VARIANTS:
                assessed = await node.exercise_reply_recovery(variant, record)
                record(assessed)
            elif variant == "stale_boot":
                assessed = await node.exercise_stale_boot(record)
                record(assessed)
            elif variant == "conflicting_identity":
                await node.exercise_reply_conflict(record)
            elif variant == "competing_claim":
                await adapter.request(binding, "control.keepalive", on_record=record)
                adapter.current(binding)
                await node.exercise_competing_claim(record)
            elif variant == "lease_recovery":
                await node.exercise_lease_recovery(record)
            elif variant == "valid_control_cycles":
                for _ in range(case["cycles"]):
                    adapter.current(binding)
                    await node.exercise_control_cycle(record)
            else:
                command, arguments, expected = SERIAL_ERROR_CASES[case["variant"]]
                try:
                    await adapter.request(binding, command, arguments, on_record=record)
                except ValueError as exc:
                    if not str(exc).startswith(expected + ":"):
                        raise
                else:
                    raise ValueError("The invalid request unexpectedly succeeded")
            if status is None:
                status = await adapter.request(binding, "status.get", on_record=record)
        after = node.snapshot()
        if (
            status["state"] != "idle"
            or status["node_role"] != case["role"]
            or after["framing_errors"] != before["framing_errors"]
            or after["event_gaps"] != before["event_gaps"]
            or status["telemetry_drops"] != before["health"]["telemetry_drops"]
        ):
            raise ValueError("Serial case did not restore idle control with complete telemetry")
        outcome = assessed["outcome"] if assessed is not None else "pass"
        case.update(
            status="completed",
            assessment=outcome,
            cleanup_verified=True,
            assertions=[{"code": variant, "outcome": outcome}],
        )

    async def matrix_health_silence(self, run, case, adapter, node, binding, record):
        port = node.port
        assessment = await node.exercise_health_silence(record)
        record(assessment)
        await node.connect(port)
        restored = adapter.bind(node.role)
        status = await adapter.request(restored, "status.get", on_record=record)
        if (
            restored["connection_id"] == binding["connection_id"]
            or restored["device_id"] != binding["device_id"]
            or restored["boot_id"] != binding["boot_id"]
            or node.control_transport() != case["transport"]
            or status["state"] != "idle"
            or status["node_role"] != node.role
        ):
            await node.close()
            raise ValueError(
                "Health-silence recovery did not restore the same idle device and boot"
            )
        record(
            {
                "direction": "host_assessment",
                "previous_binding": binding,
                "recovered_binding": restored,
            }
        )
        run.setdefault("serial_recovered_bindings", {})[node.role] = restored
        outcome = assessment["outcome"]
        case.update(
            status="completed",
            assessment=outcome,
            cleanup_verified=True,
            assertions=[{"code": case["variant"], "outcome": outcome}],
        )

    @staticmethod
    async def check_incompatible_hello(role, identity, variant):
        fixture = serial_compatibility.IdentityFixture(v2.Hello.model_validate(identity), variant)
        candidate = NodeSession(role, lambda *_: None, opener=lambda _: fixture)
        try:
            try:
                await candidate.connect("isolated-compatibility-fixture")
            except ValueError as exc:
                error = str(exc)
            else:
                error = None
            closed = fixture.closed and not candidate.connected and candidate.serial is None
            only_hello = [command["name"] for command in fixture.commands] == ["hello"]
            passed = (
                error == f"Node {role}: UNSUPPORTED_VERSION: {fixture.expected_error}"
                and closed
                and only_hello
                and not candidate.tasks
                and not candidate.pending
                and candidate.wire_profile is None
            )
            return {
                "direction": "host_fixture",
                "scope": "isolated bootstrap hello fixture based on an observed node identity",
                "modified_field": fixture.field,
                "commands": fixture.commands,
                "reply": fixture.reply.model_dump() if fixture.reply else None,
                "expected_error": fixture.expected_error,
                "connection_error": error,
                "port_closed": closed,
                "outcome": "pass" if passed else "fail",
            }
        finally:
            if candidate.serial is not None or candidate.tasks:
                await candidate.close(release=False)

    async def matrix_radio_child(self, run, case, request, radio, adapter, purpose):
        for binding in run["physical_bindings"].values():
            adapter.current(binding)
        child = await radio.start(request)
        identifier = child["id"]
        task = radio.task
        try:
            case["run_ids"].append(identifier)
            self.ledger.save(run)
            await asyncio.shield(task)
        finally:
            if not task.done():
                await radio.stop(identifier)
            result = radio.get(identifier)
            cleanup = bool((result.get("cleanup") or {}).get("confirmed"))
            self.ledger.append(
                run["id"],
                case["id"],
                {
                    "ordinal": len(case["run_ids"]),
                    "purpose": purpose,
                    "child_run_id": identifier,
                    "session_id": result["session_id"],
                    "status": result["status"],
                    "applied_settings": result["applied_settings"],
                    "configuration_check": result.get("configuration_check"),
                    **(
                        {"resource_refusal": result["resource_refusal"]}
                        if "resource_refusal" in result
                        else {}
                    ),
                    "verification": result.get("verification"),
                    "accounting": result.get("accounting"),
                    "cleanup_confirmed": cleanup,
                    "wire_sha256": result.get("wire_sha256"),
                    "error": result.get("error"),
                    "export": f"/api/radio/runs/{identifier}/export",
                },
            )
        if not cleanup:
            raise ValueError("A child left bench cleanup unconfirmed")
        return result

    @staticmethod
    def verified_link_child(result):
        return (
            result["status"] == "completed"
            and (result.get("verification") or {}).get("bytes_equal")
            and (result.get("accounting") or {}).get("evidence_complete")
        )

    async def matrix_mismatch_case(self, run, case, spec, radio, adapter):
        control = link_request(spec, case, 0)
        request = PeerMismatchCheck.from_control(control)
        rejection = await self.matrix_radio_child(
            run, case, request, radio, adapter, "configuration_mismatch"
        )
        expected = (
            rejection["status"] == "failed"
            and rejection.get("configuration_check") == "peer_mismatch"
            and rejection["failure_stage"] == "configuring"
            and not rejection["prepared"]
            and not rejection["events"]
            and len(rejection["applied_settings"]) == 2
            and rejection["applied_settings"]["A"]["radio"]
            != rejection["applied_settings"]["B"]["radio"]
        )
        valid = await self.matrix_radio_child(
            run, case, control, radio, adapter, "restored_configuration"
        )
        recovered = self.verified_link_child(valid)
        case.update(
            status="completed",
            assessment="pass" if expected and recovered else "inconclusive",
            cleanup_verified=True,
            assertions=[
                {
                    "code": "confirmed_mismatch_rejected_before_arming",
                    "outcome": "pass" if expected else "inconclusive",
                },
                {
                    "code": "matched_settings_recovered_delivery",
                    "outcome": "pass" if recovered else "inconclusive",
                },
            ],
        )

    async def matrix_security_case(self, run, case, spec, radio, adapter):
        control = content_series.run_request(spec, case, 0)
        before = await self.matrix_radio_child(run, case, control, radio, adapter, "intact_before")
        baseline = self.verified_link_child(before)
        observed = False
        if baseline and case["variant"] == "wrong_key":
            trial = await self.matrix_radio_child(
                run,
                case,
                KeyMismatchRunRequest(**control.model_dump()),
                radio,
                adapter,
                "controlled_wrong_receiver_key",
            )
            observed = content_series.matched_auth_rejection(trial)
        elif baseline:
            mismatched = PeerProfileMismatchCheck(**control.model_dump(), peer_security="none")
            preflight = radio.preflight(mismatched)
            observed = (
                not preflight["ready"] and "Peer security profile mismatch" in preflight["blockers"]
            )
            self.ledger.append(run["id"], case["id"], {"security_profile_preflight": preflight})
        after = await self.matrix_radio_child(run, case, control, radio, adapter, "intact_after")
        controls = (
            baseline
            and self.verified_link_child(after)
            and before["session_id"] != after["session_id"]
            and before["verification"]["sha256"] == after["verification"]["sha256"]
        )
        passed = bool(observed and controls)
        case.update(
            status="completed",
            assessment="pass" if passed else "inconclusive",
            cleanup_verified=True,
            assertions=[
                {"code": case["variant"], "outcome": "pass" if observed else "inconclusive"},
                {
                    "code": "matched_intact_controls",
                    "outcome": "pass" if controls else "inconclusive",
                },
            ],
        )

    async def matrix_sweep_echoes(self, run, case, spec, radio, adapter, reference):
        requested = case["echo_count"]
        matched = []
        if not case["echo_blockers"]:
            request = rf_sweeps.echo_request(spec, case)
            for _ in range(requested):
                echo = await self.matrix_radio_child(
                    run, case, request, radio, adapter, "matched_rtt"
                )
                if rf_sweeps.matched_echo(reference, echo):
                    matched.append(echo["id"])
        distribution = await radio.collect_echo_distribution(matched) if matched else {"groups": []}
        report = rf_sweeps.echo_report(distribution, requested)
        self.ledger.append(
            run["id"],
            case["id"],
            {
                "matched_rtt": report,
                "echo_run_ids": matched,
                "round_trip_distribution": distribution,
            },
        )
        return report

    async def matrix_link_case(self, run, case, spec, radio, adapter):
        verified = 0
        sweep = case["driver"] == "rf_sweep"
        observations = []
        for ordinal in range(case["message_count"]):
            result = await self.matrix_radio_child(
                run, case, link_request(spec, case, ordinal), radio, adapter, "known_data"
            )
            verified += int(bool(self.verified_link_child(result)))
            if sweep and (sample := rf_sweeps.observation(result)) is not None:
                observations.append(sample)
                self.ledger.append(
                    run["id"],
                    case["id"],
                    {
                        "radio_run_id": result["id"],
                        "observation": sample,
                    },
                )
        complete = (len(observations) if sweep else verified) == case["message_count"]
        timing = (
            await self.matrix_sweep_echoes(run, case, spec, radio, adapter, result)
            if case.get("echo_count")
            else None
        )
        matched_complete = timing is None or timing["unresolved"] == 0
        case.update(
            status="completed",
            assessment="pass" if complete and matched_complete else "inconclusive",
            measurements={
                "verified_messages": verified,
                "requested_messages": case["message_count"],
                **(rf_sweeps.report(observations, case["message_count"]) if sweep else {}),
                **({"matched_rtt": timing} if timing is not None else {}),
            },
            cleanup_verified=True,
            assertions=[
                {
                    "code": "complete_rf_observation_cohort"
                    if sweep
                    else "complete_independent_readbacks",
                    "outcome": "pass" if complete else "inconclusive",
                },
                *(
                    [
                        {
                            "code": "matched_requester_clock_echo_cohort",
                            "outcome": "pass" if matched_complete else "inconclusive",
                        }
                    ]
                    if timing is not None
                    else []
                ),
            ],
        )

    async def matrix_echo_case(self, run, case, spec, radio, adapter):
        request = timed_series.echo_request(spec, case)
        for _ in range(case["message_count"]):
            await self.matrix_radio_child(run, case, request, radio, adapter, "matched_echo")
        distribution = await radio.collect_echo_distribution(case["run_ids"])
        groups = distribution["groups"]
        complete = len(groups) == 1 and groups[0]["n"] == case["message_count"]
        self.ledger.append(run["id"], case["id"], {"round_trip_distribution": distribution})
        case.update(
            status="completed",
            assessment="pass" if complete else "inconclusive",
            measurements={
                "requested_echoes": case["message_count"],
                "verified_echoes": sum(group["n"] for group in groups),
                "distribution_count": len(groups),
            },
            cleanup_verified=True,
            assertions=[
                {
                    "code": "requester_local_exact_echo_distribution",
                    "outcome": "pass" if complete else "inconclusive",
                }
            ],
        )

    async def matrix_echo_timeout(self, run, case, spec, radio, adapter):
        control = timed_series.echo_request(spec, case)
        trial = timed_series.echo_timeout_request(spec, case)
        before = await self.matrix_radio_child(
            run, case, control, radio, adapter, "intact_echo_before"
        )
        missing = await self.matrix_radio_child(
            run, case, trial, radio, adapter, "responder_stopped"
        )
        after = await self.matrix_radio_child(
            run, case, control, radio, adapter, "intact_echo_after"
        )
        report = timed_series.controlled_timeout_report(missing)
        recovered = all(
            child["status"] == "completed" and child["timing"]["n"] == 1
            for child in (before, after)
        )
        self.ledger.append(run["id"], case["id"], {"controlled_echo_timeout": report})
        case.update(
            status="completed",
            assessment="pass" if report["verified"] and recovered else "inconclusive",
            cleanup_verified=True,
            measurements={**report, "matched_controls": recovered},
            assertions=[
                {
                    "code": "bounded_requester_timeout_keeps_rtt_null",
                    "outcome": "pass" if report["verified"] else "inconclusive",
                },
                {
                    "code": "exact_rtt_before_and_after",
                    "outcome": "pass" if recovered else "inconclusive",
                },
            ],
        )

    async def matrix_crypto_case(self, run, case, host):
        binding = run["physical_bindings"][case["role"]]
        node = host.adapter.current(binding)
        before = await host.adapter.request(binding, "status.get")
        if blockers := timed_series.crypto_blockers(node):
            raise ValueError(blockers[0])
        args = crypto_benchmark_v2.Arguments(
            iterations=case["iterations"], payload_bytes=case["message_bytes"]
        )
        service = host.diagnostics
        task = None

        def on_created(identifier):
            case["diagnostic_run_id"] = identifier
            self.ledger.save(run)

        try:
            await service.start(case["role"], binding, args.model_dump(), on_created=on_created)
            task = service.task
            await asyncio.shield(task)
        finally:
            if task is not None and not task.done():
                await service.stop()
            if identifier := case.get("diagnostic_run_id"):
                evidence = service.evidence(identifier, include_records=True)
                job = evidence["job"]
                clean = bool((job.get("cleanup") or {}).get("confirmed"))
                self.ledger.append(
                    run["id"],
                    case["id"],
                    {
                        "diagnostic_run_id": identifier,
                        "identity": job["identity"],
                        "status": job["status"],
                        "cleanup_confirmed": clean,
                        "wire_sha256": job.get("wire_sha256"),
                        "error": job.get("error"),
                        "evidence": (
                            f"/api/diagnostic-runs/{identifier}/evidence?include_records=true"
                        ),
                    },
                )
        if not clean:
            raise ValueError("Local benchmark cleanup is unconfirmed")
        after = await host.adapter.request(binding, "status.get")
        report = timed_series.crypto_report(evidence["operation_events"] or [])
        complete = (
            job["status"] == "completed"
            and report["complete"]
            and report["identification"]["payload_bytes"] == case["message_bytes"]
            and all(path["n"] == case["iterations"] for path in report["distributions"].values())
            and before["telemetry_drops"] == after["telemetry_drops"]
        )
        self.ledger.append(
            run["id"], case["id"], {"crypto_timing": report, "before": before, "after": after}
        )
        case.update(
            status="completed",
            assessment="pass" if complete else "inconclusive",
            measurements=report,
            cleanup_verified=True,
            assertions=[
                {
                    "code": "complete_public_vector_timing_samples",
                    "outcome": "pass" if complete else "inconclusive",
                }
            ],
        )

    async def matrix_ops_case(self, run, case, spec, host):
        for binding in run["physical_bindings"].values():
            host.adapter.current(binding)
        service = host.physical_campaigns
        plan = host.campaign_plans.create(ops_matrix.campaign_request(spec, case))
        expected = case["planned_campaign_cases"]
        if not ops_matrix.verified_batches(plan, expected):
            raise ValueError("Campaign batch linkage or case count differs from the OPS plan")
        self.ledger.append(
            run["id"],
            case["id"],
            {"plan_id": plan["id"], "plan_sha256": plan["plan_sha256"], "batches": plan["batches"]},
        )
        launched = await service.start(plan["id"], _procedure_id=run["id"])
        identifier, task = launched["id"], service.task
        try:
            case["campaign_ids"] = [identifier]
            self.ledger.save(run)
            await asyncio.shield(task)
        finally:
            if not task.done():
                await service.cancel(identifier, "Recovery matrix stopped")
            result = service.get(identifier)
            self.ledger.append(
                run["id"],
                case["id"],
                {
                    "campaign_id": identifier,
                    "status": result["status"],
                    "case_counts": result["case_counts"],
                    "cleanup": result["cleanup"],
                    "export": f"/api/physical-campaigns/executions/{identifier}/export",
                },
            )
        clean = bool(result["cleanup"]["confirmed"])
        if not clean:
            raise ValueError("OPS campaign cleanup is unconfirmed")
        archive = await host.campaign_exports.export(identifier)
        checked = await asyncio.to_thread(verify_campaign_bundle, archive)
        planned_order = [entry["id"] for entry in plan["cases"]]
        actual_order = [entry["case_id"] for entry in result["cases"]]
        expected_children = expected + 2 * (expected - expected // 5)
        passed = (
            result["status"] == "completed"
            and result["case_counts"].get("completed") == expected
            and actual_order == planned_order
            and checked["case_count"] == expected
            and checked["child_count"] == expected_children
        )
        self.ledger.append(run["id"], case["id"], {"checked_export": checked})
        case.update(
            status="completed",
            assessment="pass" if passed else "inconclusive",
            cleanup_verified=True,
            measurements={
                "planned_cases": expected,
                "completed_cases": result["case_counts"].get("completed", 0),
                "batches": plan["batch_count"],
                "verified_export": checked,
            },
            assertions=[
                {
                    "code": "bounded_linkage_and_complete_archive",
                    "outcome": "pass" if passed else "inconclusive",
                }
            ],
        )

    async def matrix_local_voice_case(self, run, case, host):
        def emit(document):
            if jobs := document.get("local_audio_jobs"):
                case["audio_jobs"] = jobs
                self.ledger.save(run)
            if "local_audio_cleanup_confirmed" in document:
                case["cleanup_verified"] = document["local_audio_cleanup_confirmed"]
            self.ledger.append(run["id"], case["id"], document)

        report = await local_voice.execute(host, case, run["physical_bindings"][case["role"]], emit)
        self.ledger.append(run["id"], case["id"], {"local_reference_report": report})
        case.update(
            status="completed",
            assessment="pass",
            cleanup_verified=True,
            measurements=report,
            assertions=[
                {"code": "verified_reference_codec_and_playback_command", "outcome": "pass"}
            ],
        )

    async def matrix_voice_case(self, run, case, host):
        for binding in run["physical_bindings"].values():
            host.adapter.current(binding)
        service = host.voice
        fixed_rate = case["driver"] == "sustained_voice"
        request = (
            sustained_voice.request_for(case) if fixed_rate else voice_matrix.request_for(case)
        )
        started = await service.start(request)
        identifier, task = started["id"], service.task
        try:
            case["voice_run_id"] = identifier
            self.ledger.save(run)
            await asyncio.shield(task)
        finally:
            if not task.done():
                await service.stop(identifier)
            result = service.get(identifier)
            clean = bool((result.get("cleanup") or {}).get("confirmed"))
            self.ledger.append(
                run["id"],
                case["id"],
                {
                    "voice_run_id": identifier,
                    "radio_run_id": result["radio_run_id"],
                    "comparison_runs": result["comparisons"],
                    "status": result["status"],
                    "error": result["error"],
                    "cleanup_confirmed": clean,
                    "voice_evidence": f"/api/voice/runs/{identifier}/inspection",
                    **(
                        {"source_observation": result.get("source_observation")}
                        if fixed_rate
                        else {}
                    ),
                },
            )
        if not clean:
            raise ValueError("Voice child cleanup is unconfirmed")
        if fixed_rate:
            assessment = result.get("source_observation") or {}
            complete = (
                result["status"] == "completed"
                and assessment.get("accounting") == "consistent"
                and assessment.get("delivery", {}).get("assessment") == "verified"
            )
            verdict = "pass" if complete else "inconclusive"
            case.update(
                status="completed",
                assessment=verdict,
                measurements=assessment,
                cleanup_verified=True,
                assertions=[
                    {"code": "fixed_source_accounting_and_receiver_archive", "outcome": verdict}
                ],
            )
            return
        evidence = service.inspect(identifier)
        report = voice_matrix.summarize(evidence)
        passed = report["checked_transfer_and_playback"]
        self.ledger.append(run["id"], case["id"], {"voice_comparison": report})
        case.update(
            status="completed",
            assessment="pass" if passed else "inconclusive",
            cleanup_verified=True,
            measurements={
                "reference_id": case["reference_id"],
                "checked_transfer_and_playback": passed,
                "comparison_matches": report["comparisons"],
                "physical_listening": "pending",
            },
            assertions=[
                {
                    "code": "exact_encoded_readback_and_two_matched_controls",
                    "outcome": "pass" if passed else "inconclusive",
                }
            ],
        )

    async def matrix_fault_child(self, run, case, request, host):
        for binding in run["physical_bindings"].values():
            host.adapter.current(binding)
        service = host.lab_trials
        started = await service.start(request, _procedure_id=run["id"])
        identifier, task = started["id"], service.task
        try:
            case.setdefault("trial_ids", []).append(identifier)
            self.ledger.save(run)
            await asyncio.shield(task)
        finally:
            if not task.done():
                await service.stop(identifier)
            record = service.get(identifier)
            children = {stage: host.radio.get(i) for stage, i in record["children"].items()}
            clean = all(
                (entry.get("cleanup") or {}).get("confirmed") for entry in children.values()
            )
            self.ledger.append(
                run["id"],
                case["id"],
                {
                    "trial_id": identifier,
                    "children": record["children"],
                    "child_wire_sha256": {
                        stage: entry["wire_sha256"] for stage, entry in children.items()
                    },
                    "status": record["status"],
                    "outcome": record["outcome"],
                    "reason": record["reason"],
                    "checks": record["checks"],
                    "cleanup_confirmed": clean,
                    "evidence": f"/api/lab-trials/{identifier}",
                },
            )
        if not clean:
            raise ValueError("Nested lab trial cleanup is unconfirmed")
        return record

    async def matrix_fault_case(self, run, case, spec, host):
        radio, adapter = host.radio, host.adapter
        outcomes = []
        for ordinal in range(case["message_count"]):
            request = fault_matrices.selected_request(spec, case, ordinal)
            if isinstance(request, LabRadioRunRequest):
                trial = await self.matrix_fault_child(run, case, request, host)
                outcomes.append(trial["outcome"])
            else:
                child = await self.matrix_radio_child(run, case, request, radio, adapter, "intact")
                outcomes.append("pass" if self.verified_link_child(child) else "inconclusive")
        verdict = (
            "fail"
            if "fail" in outcomes
            else "inconclusive"
            if "inconclusive" in outcomes
            else "pass"
        )
        case.update(
            status="completed",
            assessment=verdict,
            cleanup_verified=True,
            measurements={"message_outcomes": outcomes, "target_ordinal": case["target_ordinal"]},
            assertions=[{"code": "complete_matched_series", "outcome": verdict}],
        )

    async def matrix_model_case(self, run, case, spec, radio, adapter):
        reference = model_series.reference_result(case)
        numerical = case["driver"] == "model_reference"
        if numerical:
            measurements = reference
            complete = reference["passed"]
        else:
            rows = []
            for ordinal in range(case["message_count"]):
                result = await self.matrix_radio_child(
                    run,
                    case,
                    model_series.link_request(spec, case, ordinal),
                    radio,
                    adapter,
                    "isolated_frame",
                )
                sample = rf_sweeps.observation(result)
                if (
                    sample is None
                    or sample["frame_bytes"] != case["expected_frame_bytes"]
                    or not all(
                        settings["radio"]["ldro_enabled"] == reference["reference_ldro"]
                        for settings in result["applied_settings"].values()
                    )
                ):
                    continue
                row = {
                    "child_run_id": result["id"],
                    **sample,
                    "duration_minus_prediction_us": sample["tx_command_to_done_us"]
                    - sample["predicted_airtime_us"],
                }
                rows.append(row)
                self.ledger.append(run["id"], case["id"], {"frame_observation": row})
            measurements = model_series.observed_result(reference, rows, case["message_count"])
            complete = reference["passed"] and len(rows) == case["message_count"]
        self.ledger.append(run["id"], case["id"], {"model_comparison": measurements})
        outcome = "pass" if complete else "fail" if not reference["passed"] else "inconclusive"
        case.update(
            status="completed",
            assessment=outcome,
            measurements=measurements,
            cleanup_verified=True,
            assertions=[
                {
                    "code": "independent_reference_match"
                    if numerical
                    else "matched_frame_observations",
                    "outcome": outcome,
                }
            ],
        )

    async def matrix_model_message_case(self, run, case, spec, radio, adapter):
        rows = []
        for ordinal in range(case["message_count"]):
            request = model_series.message_request(spec, case, ordinal)
            result = await self.matrix_radio_child(
                run, case, request, radio, adapter, "delivery_model"
            )
            sample = model_series.message_observation(result, request)
            if sample is not None:
                rows.append(sample)
                self.ledger.append(run["id"], case["id"], {"message_observation": sample})
        complete = len(rows) == case["message_count"]
        contained = complete and all(row["within_expanded_budget"] for row in rows)
        case.update(
            status="completed",
            assessment="pass" if contained else "inconclusive",
            measurements={
                "requested_messages": case["message_count"],
                "matched_measurements": len(rows),
                "contained_in_budget": sum(row["within_expanded_budget"] for row in rows),
                "physical_agreement_assessed": False,
            },
            cleanup_verified=True,
            assertions=[
                {
                    "code": "matched_message_evidence_and_budget_containment",
                    "outcome": "pass" if contained else "inconclusive",
                }
            ],
        )

    @staticmethod
    def resource_control_request(case):
        return RadioRunRequest(direction=case["direction"], security=case["security"])

    async def matrix_resource_refusal(self, run, case, radio, adapter):
        control = self.resource_control_request(case)
        probe = PrepareLimitCheck(**control.model_dump(), attempted_bytes=case["message_bytes"])
        refusal = await self.matrix_radio_child(
            run, case, probe, radio, adapter, "device_prepare_resource_refusal"
        )
        recovery = await self.matrix_radio_child(
            run, case, control, radio, adapter, "intact_after_resource_refusal"
        )
        resource_refused = (
            refusal["status"] == "completed"
            and (refusal.get("resource_refusal") or {})
            .get("reply", {})
            .get("error", {})
            .get("code")
            == "RESOURCE_LIMIT"
        )
        recovered = self.verified_link_child(recovery)
        case.update(
            status="completed",
            assessment="pass" if resource_refused and recovered else "fail",
            cleanup_verified=True,
            measurements=refusal.get("resource_refusal"),
            assertions=[
                {
                    "code": "device_refused_max_plus_one_before_arming",
                    "outcome": "pass" if resource_refused else "fail",
                },
                {
                    "code": "recovered_small_known_data_workload",
                    "outcome": "pass" if recovered else "fail",
                },
            ],
        )

    async def matrix_paired_memory_audio(self, run, case, host):
        observations, voice = host.observations, host.voice
        window = case["observation_ms"]
        bindings = run["physical_bindings"]
        claims, reports, errors = {}, {}, {}
        child = None

        try:
            for role in ("A", "B"):
                host.adapter.current(bindings[role])
                observer = asyncio.create_task(observations.start_memory(role, window + 120000))
                try:
                    started = await asyncio.shield(observer)
                except asyncio.CancelledError:
                    claims[role] = (await observer)["observation_id"]
                    raise
                claims[role] = started["observation_id"]
                case["observation_ids"] = dict(claims)
                self.ledger.save(run)
            await asyncio.sleep(2 * memory_observation_v2.PERIOD_US / 1_000_000)
            started = await voice.start(memory_matrix.paired_audio_request(case))
            identifier, task = started["id"], voice.task
            try:
                case["voice_run_id"] = identifier
                self.ledger.save(run)
                await asyncio.shield(task)
            finally:
                if not task.done():
                    await voice.stop(identifier)
                child = voice.get(identifier)
                self.ledger.append(
                    run["id"],
                    case["id"],
                    {
                        "voice_run_id": child["id"],
                        "radio_run_id": child["radio_run_id"],
                        "audio_jobs": child["jobs"],
                        "status": child["status"],
                        "error": child["error"],
                        "cleanup": child["cleanup"],
                    },
                )
            await asyncio.sleep(window / 1000)
        finally:
            for role, identifier in claims.items():
                try:
                    host.adapter.current(bindings[role])
                    record = await observations.collect_memory(role, identifier, stop=True)
                    result = memory_matrix.paired_audio_summary(
                        child, host.audio, role, record, window, case["variant"]
                    )
                    result["observer_stopped"] = not record["evidence"]["memory"]["status"][
                        "active"
                    ]
                    reports[role] = result
                    self.ledger.append(run["id"], case["id"], {"role": role, "memory": result})
                except (OSError, ValueError) as exc:
                    errors[role] = str(exc)
            if errors:
                self.ledger.append(run["id"], case["id"], {"memory_collection_errors": errors})
            case["cleanup_verified"] = bool(
                child
                and child["cleanup"]["confirmed"]
                and len(reports) == 2
                and all(report["observer_stopped"] for report in reports.values())
            )
        if not case["cleanup_verified"]:
            raise ValueError("Paired audio and memory cleanup is unconfirmed")
        completed = child["status"] == "completed" and child["delivery_verified"]
        playback_ok = child["playback_completed"] == (case["variant"] == "integrated_voice")
        verdict = (
            "pass"
            if completed and playback_ok and all(report["passed"] for report in reports.values())
            else "inconclusive"
        )
        case.update(
            status="completed",
            assessment=verdict,
            measurements=reports,
            assertions=[{"code": "bound_voice_reassembly_and_idle_recovery", "outcome": verdict}],
        )

    async def matrix_local_memory_audio(self, run, case, host):
        role, window = case["role"], case["observation_ms"]
        binding = run["physical_bindings"][role]
        observations = host.observations
        started = child = report = None
        restored = False

        def emit(document):
            nonlocal restored
            if identifier := document.get("audio_operation_id"):
                case["audio_operation_id"] = identifier
                self.ledger.save(run)
            if "audio_artifacts_restored" in document:
                restored = document["audio_artifacts_restored"]
            self.ledger.append(run["id"], case["id"], document)

        observer = asyncio.create_task(observations.start_memory(role, window + 45000))
        try:
            try:
                started = await asyncio.shield(observer)
            except asyncio.CancelledError:
                started = await observer
                raise
            case["observation_ids"] = {role: started["observation_id"]}
            self.ledger.save(run)
            await asyncio.sleep(2 * memory_observation_v2.PERIOD_US / 1_000_000)
            child = await memory_matrix.execute_local_audio(host, case, binding, emit)
            await asyncio.sleep(window / 1000)
        finally:
            if started:
                try:
                    host.adapter.current(binding)
                    record = await observations.collect_memory(
                        role, started["observation_id"], stop=True
                    )
                    report = memory_matrix.local_audio_summary(
                        record, window, child, case["variant"]
                    )
                    stopped = not record["evidence"]["memory"]["status"]["active"]
                    case["cleanup_verified"] = bool(restored and stopped)
                    emit({"role": role, "memory": report, "observer_stopped": stopped})
                except (OSError, ValueError) as exc:
                    emit({"memory_collection_error": str(exc)})
        if not case.get("cleanup_verified"):
            raise ValueError("Memory audio cleanup or readback is unconfirmed")
        verdict = "pass" if report["passed"] else "inconclusive"
        case.update(
            status="completed",
            assessment=verdict,
            measurements={role: report},
            assertions=[{"code": "bound_audio_stage_and_idle_recovery", "outcome": verdict}],
        )

    async def matrix_memory_case(self, run, case, spec, host):
        adapter, observations = host.adapter, host.observations
        recovery = case["driver"] == "memory_recovery"
        request = (
            memory_matrix.recovery_request(case)
            if recovery
            else memory_matrix.link_request(spec, case)
            if case["driver"] == "memory_link"
            else None
        )
        roles = ("A", "B") if request else (case["role"],)
        window = case["observation_ms"]
        duration = request.timeout_ms + window + 20000 if request else window
        claims, reports, errors = {}, {}, {}
        cleanup_uptimes = {}
        result = None

        def claim(role, started):
            claims[role] = started["observation_id"]
            case["observation_ids"] = dict(claims)
            self.ledger.save(run)

        if recovery:
            self.ledger.append(
                run["id"], case["id"], {"declared_recovery_band_bytes": case["recovery_band_bytes"]}
            )

        try:
            for role in roles:
                binding = run["physical_bindings"][role]
                adapter.current(binding)
                started = asyncio.create_task(observations.start_memory(role, duration))
                try:
                    claim(role, await asyncio.shield(started))
                except asyncio.CancelledError:
                    claim(role, await started)
                    raise
            if request:
                if recovery:
                    await asyncio.sleep(2 * memory_observation_v2.PERIOD_US / 1_000_000)
                result = await self.matrix_radio_child(
                    run,
                    case,
                    request,
                    host.radio,
                    adapter,
                    case["variant"] if recovery else "sampled_known_data",
                )
                if recovery:
                    for role in roles:
                        status = await adapter.request(run["physical_bindings"][role], "status.get")
                        if status["state"] != "idle" or status["run_id"] is not None:
                            raise ValueError(f"Node {role} is not idle after controlled cleanup")
                        cleanup_uptimes[role] = status["uptime_us"]
                await asyncio.sleep(window / 1000)
            else:
                await memory_matrix.wait_for_idle_observation(
                    adapter, run["physical_bindings"][roles[0]], claims[roles[0]], window
                )
        finally:
            for role, identifier in claims.items():
                try:
                    adapter.current(run["physical_bindings"][role])
                    record = await observations.collect_memory(role, identifier, stop=True)
                    linked = case["run_ids"][0] if case["run_ids"] else None
                    if recovery and linked:
                        report = memory_matrix.recovery_summary(
                            record,
                            window,
                            linked,
                            case["recovery_band_bytes"],
                            cleanup_uptimes.get(role),
                        )
                    else:
                        report = memory_matrix.summary(record, window, linked)
                    report["cleanup_confirmed"] = not record["evidence"]["memory"]["status"][
                        "active"
                    ]
                    reports[role] = report
                    self.ledger.append(run["id"], case["id"], {"role": role, "memory": report})
                except Exception as exc:
                    errors[role] = str(exc) or type(exc).__name__
            if errors:
                self.ledger.append(run["id"], case["id"], {"memory_collection_errors": errors})
            case["cleanup_verified"] = len(reports) == len(roles) and all(
                report["cleanup_confirmed"] for report in reports.values()
            )
        if not case["cleanup_verified"]:
            raise ValueError("Memory observation cleanup or readback is unconfirmed")
        if recovery:
            await self.finish_memory_recovery(run, case, host, request, result, reports)
            return
        passed = all(report["passed"] for report in reports.values()) and (
            not request or self.verified_link_child(result)
        )
        case.update(
            status="completed",
            assessment="pass" if passed else "inconclusive",
            measurements=reports,
            assertions=[
                {
                    "code": "linked_stage_samples_and_idle_recovery" if request else "idle_samples",
                    "outcome": "pass" if passed else "inconclusive",
                }
            ],
        )

    async def finish_memory_recovery(self, run, case, host, request, child, reports):
        if case["variant"] == "cancel_and_recover":
            control = child.get("prepared_cancellation")
            if control:
                case["controlled_cancel"] = control
                self.ledger.append(run["id"], case["id"], control)
            forced = bool(control and set(control["stop_replies"]) == {"A", "B"})
            disruption = "pass" if forced and child["status"] == "cancelled" else "inconclusive"
        else:
            expected = known_data(request.source_seed, 1, request.message_bytes)
            fault = fault_accounting.assess(child, expected)
            self.ledger.append(run["id"], case["id"], {"failed_workload_evidence": fault})
            disruption = fault["outcome"]

        recovery = await self.matrix_radio_child(
            run,
            case,
            RadioRunRequest(direction=request.direction),
            host.radio,
            host.adapter,
            "intact_after_memory_recovery",
        )
        complete = all(report.get("recovery") is not None for report in reports.values())
        recovered = (
            all(report["recovery"]["passed"] for report in reports.values()) if complete else False
        )
        band = "pass" if recovered else "fail" if complete else "inconclusive"
        delivery = "pass" if self.verified_link_child(recovery) else "inconclusive"
        assertions = [
            {"code": "controlled_workload_interruption", "outcome": disruption},
            {"code": "sampled_idle_memory_within_declared_band", "outcome": band},
            {"code": "fresh_small_known_data_delivered", "outcome": delivery},
        ]
        outcomes = {row["outcome"] for row in assertions}
        case.update(
            status="completed",
            assessment="fail"
            if "fail" in outcomes
            else "pass"
            if outcomes == {"pass"}
            else "inconclusive",
            measurements=reports,
            assertions=assertions,
        )

    async def matrix_campaign_case(self, run, case, spec, host):
        service = host.physical_campaigns
        for binding in run["physical_bindings"].values():
            host.adapter.current(binding)
        plan = host.campaign_plans.create(campaign_intent(spec, case))
        group = case["group"]
        launched = await service.start(
            plan["id"], _procedure_id=run["id"], _reject_configuration=group == "C4"
        )
        identifier, task = launched["id"], service.task
        pause_record = None
        concurrent_start_rejected = False
        try:
            case.setdefault("campaign_ids", []).append(identifier)
            self.ledger.save(run)
            if group in ("C2", "C3", "C8"):
                async with asyncio.timeout(75):
                    while service.current and service.current["active_case_id"] is None:
                        await asyncio.sleep(0.01)
                    if not service.current:
                        raise ValueError("Campaign finished before its control case was exercised")
                    if group == "C2":
                        service.pause(identifier)
                        while service.current and service.current["status"] != "paused":
                            await asyncio.sleep(0.01)
                        pause_record = service.get(identifier)
                        if pause_record["status"] != "paused":
                            raise ValueError("Campaign did not settle at a case boundary")
                        service.resume(identifier)
                    elif group == "C3":
                        await service.cancel(identifier, "Controlled procedure cancellation")
                    else:
                        try:
                            await host.start_radio(RadioRunRequest())
                        except RuntimeError as exc:
                            concurrent_start_rejected = "owns the bench" in str(exc)
            await asyncio.shield(task)
        finally:
            if not task.done():
                await service.cancel(identifier, "Matrix stopped")
            result = service.get(identifier)
            self.ledger.append(
                run["id"],
                case["id"],
                {
                    "campaign_id": identifier,
                    "plan_sha256": plan["plan_sha256"],
                    "status": result["status"],
                    "case_counts": result["case_counts"],
                    "cleanup": result["cleanup"],
                    "paused_case_counts": pause_record["case_counts"] if pause_record else None,
                    "export": f"/api/physical-campaigns/executions/{identifier}/export",
                },
            )
        observed = self.campaign_radio_children(host, result)
        expected_plans = {c["id"]: c["case"]["request"] for c in plan["cases"]}
        linked_ids = [c["case_id"] for c in result["cases"] if c["child"]]
        matched_plans = all(
            child["plan"]
            == RadioRunRequest.model_validate(expected_plans[case_id]).plan().model_dump()
            for case_id, child in zip(linked_ids, observed, strict=True)
        )
        verified = sum(bool(self.verified_link_child(child)) for child in observed)
        expected_count = spec.messages_per_case * 6
        linked = (
            len(result["cases"]) == expected_count
            and [c["case_id"] for c in result["cases"]] == [c["id"] for c in plan["cases"]]
            and len({c["session_id"] for c in observed}) == len(observed)
            and matched_plans
        )
        if group in ("C3", "C4"):
            accepted = (
                result["status"] == ("cancelled" if group == "C3" else "failed")
                and len(observed) == 1
                and result["case_counts"].get("skipped", 0) == expected_count - 1
            )
            if accepted and group == "C4":
                rejected = observed[0]
                accepted = (
                    rejected["failure_stage"] == "configuring"
                    and rejected.get("configuration_check") == "peer_mismatch"
                    and not rejected["prepared"]
                    and not rejected["events"]
                )
        else:
            accepted = result["status"] == "completed" and verified == expected_count
            if group == "C2":
                accepted = (
                    accepted
                    and pause_record is not None
                    and pause_record["case_counts"].get("completed") == 1
                    and pause_record["case_counts"].get("pending") == expected_count - 1
                    and result["pause_count"] == result["resume_count"] == 1
                )
        clean = bool(result["cleanup"]["confirmed"])
        if accepted and linked and clean:
            if group == "C7":
                accepted = await self.matrix_campaign_rerun(run, case, host, result, observed)
            if group == "C8":
                exported = await host.campaign_exports.export(identifier)
                verified_export = await asyncio.to_thread(verify_campaign_bundle, exported)
                transfer_ids = {i for child in observed for i in child["transfers"].values()}
                self.ledger.append(
                    run["id"],
                    case["id"],
                    {
                        "verified_export": verified_export,
                        "concurrent_start_rejected": concurrent_start_rejected,
                    },
                )
                accepted = (
                    concurrent_start_rejected
                    and verified_export["case_count"] == expected_count
                    and verified_export["child_count"] == expected_count + len(transfer_ids)
                )
        passed = bool(accepted and linked and clean)
        case.update(
            status="completed",
            assessment="pass" if passed else "inconclusive",
            cleanup_verified=clean,
            measurements={"verified_messages": verified, "planned_messages": expected_count},
            assertions=[{"code": case["variant"], "outcome": "pass" if passed else "inconclusive"}],
        )
        if not clean:
            raise ValueError("Nested campaign cleanup is unconfirmed")

    @staticmethod
    def campaign_radio_children(host, execution):
        return [
            host.radio.get(c["child"]["id"])
            for c in execution["cases"]
            if c["child"] and c["child"]["service"] == "radio"
        ]

    async def matrix_campaign_rerun(self, run, case, host, original, sources):
        service = host.physical_campaigns
        indexes = (0, len(original["cases"]) - 1)
        selected = [original["cases"][i]["case_id"] for i in indexes]
        launched = await service.rerun(original["id"], selected, _procedure_id=run["id"])
        identifier, task = launched["id"], service.task
        try:
            case["campaign_ids"].append(identifier)
            self.ledger.save(run)
            await asyncio.shield(task)
        finally:
            if not task.done():
                await service.cancel(identifier, "Matrix stopped")
            result = service.get(identifier)
            self.ledger.append(
                run["id"],
                case["id"],
                {
                    "rerun_id": identifier,
                    "parent_id": original["id"],
                    "selected_case_ids": selected,
                    "status": result["status"],
                    "cleanup": result["cleanup"],
                    "export": f"/api/physical-campaigns/executions/{identifier}/export",
                },
            )
        if not result["cleanup"]["confirmed"]:
            raise ValueError("Selected rerun cleanup is unconfirmed")
        children = self.campaign_radio_children(host, result)
        return (
            result["status"] == "completed"
            and result["parent_execution_id"] == original["id"]
            and result["plan_sha256"] == original["plan_sha256"]
            and [c["case_id"] for c in result["cases"]] == selected
            and len(children) == len(selected)
            and all(
                self.verified_link_child(child)
                and child["plan"] == sources[index]["plan"]
                and child["session_id"] != sources[index]["session_id"]
                for child, index in zip(children, indexes, strict=True)
            )
        )

    async def run(self, run, spec, host):
        radio, adapter = host.radio, host.adapter
        try:
            for case in run["cases"]:
                if not case["ready"]:
                    case.update(
                        status="blocked",
                        assessment="inconclusive",
                        reason="; ".join(case["blockers"]),
                    )
                    self.ledger.save(run)
                    continue
                run["active_case"] = case["id"]
                case["status"] = "running"
                self.ledger.save(run)
                if case["driver"] == "serial_matrix":
                    await self.matrix_serial_case(run, case, adapter)
                elif case["driver"] == "campaign_matrix":
                    await self.matrix_campaign_case(run, case, spec, host)
                elif case["driver"] == "peer_mismatch":
                    await self.matrix_mismatch_case(run, case, spec, radio, adapter)
                elif case["driver"] == "content_negative":
                    await self.matrix_security_case(run, case, spec, radio, adapter)
                elif case["driver"] == "echo_batch":
                    await self.matrix_echo_case(run, case, spec, radio, adapter)
                elif case["driver"] == "echo_timeout_fixture":
                    await self.matrix_echo_timeout(run, case, spec, radio, adapter)
                elif case["driver"] == "local_crypto":
                    await self.matrix_crypto_case(run, case, host)
                elif case["driver"] == "resource_refusal":
                    await self.matrix_resource_refusal(run, case, radio, adapter)
                elif case["driver"] == "memory_audio_pair":
                    await self.matrix_paired_memory_audio(run, case, host)
                elif case["driver"] == "memory_audio_local":
                    await self.matrix_local_memory_audio(run, case, host)
                elif case["driver"] in ("memory_idle", "memory_link", "memory_recovery"):
                    await self.matrix_memory_case(run, case, spec, host)
                elif case["driver"] in ("model_reference", "model_frame"):
                    await self.matrix_model_case(run, case, spec, radio, adapter)
                elif case["driver"] == "model_message":
                    await self.matrix_model_message_case(run, case, spec, radio, adapter)
                elif case["driver"] == "fault_series":
                    await self.matrix_fault_case(run, case, spec, host)
                elif case["driver"] in ("voice_reference", "sustained_voice"):
                    await self.matrix_voice_case(run, case, host)
                elif case["driver"] == "local_voice_reference":
                    await self.matrix_local_voice_case(run, case, host)
                elif case["driver"] == "ops_campaign":
                    await self.matrix_ops_case(run, case, spec, host)
                else:
                    await self.matrix_link_case(run, case, spec, radio, adapter)
                self.ledger.save(run)
            assessments = {case["assessment"] for case in run["cases"]}
            outcome = (
                "fail"
                if "fail" in assessments
                else "pass"
                if assessments == {"pass"}
                else "inconclusive"
            )
            run.update(status="completed", assessment=outcome)
        except asyncio.CancelledError:
            run.update(
                status="interrupted" if run["reason"] == "Host shutdown" else "cancelled",
                assessment="inconclusive",
            )
        except Exception as exc:
            run.update(status="failed", assessment="inconclusive", reason=str(exc))
        finally:
            for case in run["cases"]:
                if case["status"] in ("pending", "running"):
                    case.update(
                        status=run["status"] if case["status"] == "running" else "skipped",
                        assessment="inconclusive",
                        reason=run["reason"],
                    )
            if spec.catalog_id in rf_sweeps.FACTORS:
                run["sweep_comparison"] = rf_sweeps.compare_saved_cases(run)
            if spec.catalog_id == "MODEL-01":
                comparison = model_series.observed_comparison(
                    run, self.ledger.all_evidence(run["id"])
                )
                if comparison["points"]:
                    run["model_comparison"] = comparison
            run.update(active_case=None, finished_at=utc_now())
            self.ledger.save(run)
