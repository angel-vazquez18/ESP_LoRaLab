"""Execute grouped integration cases through the shared physical services."""

import asyncio
import hashlib
from copy import deepcopy
from uuid import uuid4

from . import content_series, crypto_benchmark_v2, memory_matrix, rf_sweeps, timed_series
from .integration_matrices import campaign_intent, compile_matrix, link_request
from .paths import REPOSITORY_ROOT
from .physical_campaign_evidence import verify_campaign_bundle
from .radio_runs import (
    KeyMismatchRunRequest,
    PeerMismatchCheck,
    PeerProfileMismatchCheck,
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

    def preview(self, spec, radio):
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
            elif case["driver"] == "content_negative":
                if spec.catalog_id == "PKT-01" and limit is not None:
                    blockers = radio.preflight(RadioRunRequest(direction=case["direction"]))[
                        "blockers"
                    ]
                elif spec.catalog_id == "PKT-01":
                    blockers = ["Connect both nodes to establish the negotiated message limit"]
                else:
                    control = content_series.run_request(spec, case, 0)
                    request = (
                        KeyMismatchRunRequest(**control.model_dump())
                        if case["variant"] == "wrong_key"
                        else control
                    )
                    blockers = radio.preflight(request)["blockers"]
            elif case["driver"] == "memory_unavailable":
                blockers = [memory_matrix.BLOCKERS[case["group"]]]
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
                blockers = ["A controlled missing-reply fixture is required"]
            elif case["driver"] == "local_crypto":
                blockers = timed_series.crypto_blockers(self.ledger.nodes[case["role"]])
            elif case["driver"] == "serial_matrix":
                blockers = []
                node = self.ledger.nodes[case["role"]]
                if case["transport"] != "native_usb":
                    blockers.append("An identified UART transport is required")
                if case["variant"] not in ("valid_control_cycles", *SERIAL_ERROR_CASES):
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
        planned = self.preview(spec, radio)
        if expected_plan_sha256 is not None and planned["sha256"] != expected_plan_sha256:
            raise RuntimeError("The matrix plan changed. Preview the cases again.")
        if not planned["ready_case_count"]:
            raise ValueError("No selected matrix cases can run on this bench")
        ready_cases = [case for case in planned["cases"] if case["ready"]]
        local_drivers = {"serial_matrix", "local_crypto", "memory_idle"}
        required = (
            {case["role"] for case in ready_cases}
            if all(case["driver"] in local_drivers for case in ready_cases)
            else set(spec.roles)
        )
        run = {
            **planned,
            "id": str(uuid4()),
            "mode": "hardware",
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
                    "testbed/src/lora_testbed/workload_observations.py",
                    "testbed/src/lora_testbed/workload_assessment.py",
                    "testbed/src/lora_testbed/echo_accounting.py",
                    "testbed/src/lora_testbed/crypto_benchmark_v2.py",
                    "testbed/src/lora_testbed/procedure_runs.py",
                    "testbed/src/lora_testbed/radio_runs.py",
                    "testbed/src/lora_testbed/nodes.py",
                    "testbed/src/lora_testbed/campaign_plans.py",
                    "testbed/src/lora_testbed/physical_campaigns.py",
                )
            },
            "transport": "physical USB"
            if all(case["driver"] in local_drivers for case in ready_cases)
            else "physical USB and owned radio runs",
            "timing_basis": "per-child node-local and host-monotonic observations",
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
        binding = run["physical_bindings"][case["role"]]
        node = adapter.current(binding)
        before = node.snapshot()

        def record(document):
            self.ledger.append(run["id"], case["id"], document)

        async with asyncio.timeout(60):
            if case["variant"] == "valid_control_cycles":
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
        case.update(
            status="completed",
            assessment="pass",
            cleanup_verified=True,
            assertions=[{"code": case["variant"], "outcome": "pass"}],
        )

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

    async def matrix_oversize_case(self, run, case, spec, radio, adapter):
        rejected = False
        reason = None
        try:
            request = RadioRunRequest(
                direction=case["direction"],
                message_bytes=case["message_bytes"],
                timeout_ms=300000,
            )
        except ValueError:
            rejected = case["message_bytes"] > 65536
            reason = "Request exceeds the testbed's model limit"
        else:
            preflight = radio.preflight(request)
            rejected = any("max_message_bytes" in value for value in preflight["blockers"])
            reason = "; ".join(preflight["blockers"])
        self.ledger.append(
            run["id"],
            case["id"],
            {
                "source": "read-only host preflight",
                "requested_message_bytes": case["message_bytes"],
                "advertised_message_limit": self.message_limit(radio),
                "rejection_observed": rejected,
                "reason": reason,
            },
        )
        control = RadioRunRequest(direction=case["direction"], security=case["security"])
        recovered = await self.matrix_radio_child(
            run, case, control, radio, adapter, "intact_after_oversize_preflight"
        )
        passed = rejected and self.verified_link_child(recovered)
        case.update(
            status="completed",
            assessment="pass" if passed else "inconclusive",
            cleanup_verified=True,
            assertions=[
                {
                    "code": "host_oversize_rejection_and_recovery",
                    "outcome": "pass" if passed else "inconclusive",
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
        complete = verified == case["message_count"]
        if sweep:
            complete = complete and len(observations) == case["message_count"]
        case.update(
            status="completed",
            assessment="pass" if complete else "inconclusive",
            measurements={
                "verified_messages": verified,
                "requested_messages": case["message_count"],
                **(rf_sweeps.report(observations, case["message_count"]) if sweep else {}),
            },
            cleanup_verified=True,
            assertions=[
                {
                    "code": "complete_independent_readbacks",
                    "outcome": "pass" if complete else "inconclusive",
                }
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

    async def matrix_memory_case(self, run, case, spec, host):
        adapter, observations = host.adapter, host.observations
        is_link = case["driver"] == "memory_link"
        request = memory_matrix.link_request(spec, case) if is_link else None
        roles = ("A", "B") if is_link else (case["role"],)
        window = case["observation_ms"]
        duration = request.timeout_ms + window + 20000 if is_link else window
        claims, reports, errors = {}, {}, {}
        result = None

        def claim(role, started):
            claims[role] = started["observation_id"]
            case["observation_ids"] = dict(claims)
            self.ledger.save(run)

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
            if is_link:
                result = await self.matrix_radio_child(
                    run, case, request, host.radio, adapter, "sampled_known_data"
                )
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
                    report = memory_matrix.summary(
                        record, window, case["run_ids"][0] if case["run_ids"] else None
                    )
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
        passed = all(report["passed"] for report in reports.values()) and (
            not is_link or self.verified_link_child(result)
        )
        case.update(
            status="completed",
            assessment="pass" if passed else "inconclusive",
            measurements=reports,
            assertions=[
                {
                    "code": "linked_stage_samples_and_idle_recovery" if is_link else "idle_samples",
                    "outcome": "pass" if passed else "inconclusive",
                }
            ],
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
                    if spec.catalog_id == "SEC-01":
                        await self.matrix_security_case(run, case, spec, radio, adapter)
                    else:
                        await self.matrix_oversize_case(run, case, spec, radio, adapter)
                elif case["driver"] == "echo_batch":
                    await self.matrix_echo_case(run, case, spec, radio, adapter)
                elif case["driver"] == "local_crypto":
                    await self.matrix_crypto_case(run, case, host)
                elif case["driver"] in ("memory_idle", "memory_link"):
                    await self.matrix_memory_case(run, case, spec, host)
                else:
                    await self.matrix_link_case(run, case, spec, radio, adapter)
                self.ledger.save(run)
            run.update(
                status="completed",
                assessment="pass"
                if all(c["assessment"] == "pass" for c in run["cases"])
                else "inconclusive",
            )
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
            run.update(active_case=None, finished_at=utc_now())
            self.ledger.save(run)
