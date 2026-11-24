"""One physical bench owner shared by the dashboard and CLI."""

import asyncio
from pathlib import Path

from . import __version__, crypto_benchmark_v2
from .artifact_transfers import ArtifactTransfers
from .campaign_plans import CampaignPlans
from .catalog import catalog, required_nodes
from .diagnostic_jobs import DiagnosticJobs
from .node_audio import NodeAudio
from .nodes import NodeSession, discover_ports
from .physical_adapter import PhysicalAdapter
from .procedure_runs import ProcedureService
from .radio_runs import RadioRuns
from .run_records_v2 import RunRecords
from .storage import Store
from .voice_runs import VoiceRuns
from .workload_observations import WorkloadObservations


class Host:
    def __init__(self, data_dir: Path):
        self.store = Store(data_dir)
        self.lock = asyncio.Lock()
        self.mode = "hardware"
        self.physical = {role: NodeSession(role, self.node_event) for role in "AB"}
        self.adapter = PhysicalAdapter(self.physical)
        self.diagnostics = DiagnosticJobs(self.store, self.physical, self.adapter)
        self.records = RunRecords(self.store)  # Retain access to historical evidence.
        self.procedures = ProcedureService(self.store, self.physical)
        self.artifacts = ArtifactTransfers(self.store, self.physical, self.adapter)
        self.audio = NodeAudio(self.store, self.physical, self.artifacts, self.adapter)
        self.radio = RadioRuns(self.store, self.physical, self.artifacts, self.adapter)
        self.voice = VoiceRuns(self.store, self.physical, self.artifacts, self.audio, self.radio)
        self.campaign_plans = CampaignPlans(self.store, self.campaign_case_preflight)
        self.observations = WorkloadObservations(self.store, self.adapter)

    def node_event(self, role, event):
        self.store.append_node_event(role, event)
        self.audio.observe(role, event)
        self.radio.observe(role, event)

    @property
    def busy(self) -> bool:
        return (
            self.procedures.busy
            or self.diagnostics.busy
            or self.voice.busy
            or self.radio.busy
            or self.audio.busy
            or self.artifacts.busy
            or any(n.active_operation is not None for n in self.physical.values())
        )

    def snapshot(self) -> dict:
        nodes = [node.snapshot() for node in self.physical.values()]
        return {
            "version": __version__,
            "mode": "hardware",
            "bench_busy": self.busy,
            "nodes": nodes,
            "hardware_nodes": nodes,
            "connected_node_count": sum(node.connected for node in self.physical.values()),
            "procedures": self.procedures.snapshot(),
            "v2_execution": {
                "active_run": None,
                "active_campaign": None,
                "runs": self.records.runs(),
                "campaigns": self.records.campaigns(),
            },
            "active_run": self.procedures.current if self.busy else None,
            "active_campaign": None,
            "campaigns": self.store.campaigns(),
            "runs": self.store.runs(),
            "catalog": [dict(entry, preflight=self.preflight(entry["id"])) for entry in catalog()],
            "references": self.store.references(),
            "artifact_transfers": self.artifacts.snapshot(),
            "audio_operations": self.audio.snapshot(),
            "radio_runs": self.radio.snapshot(),
            "diagnostic_runs": self.diagnostics.snapshot(),
            "voice_runs": self.voice.snapshot(),
        }

    def preflight(self, code: str, roles=None, workload="default") -> dict:
        count = required_nodes(code, workload)
        entry = next(item for item in catalog() if item["id"] == code)
        if roles is None:
            connected = [r for r, n in self.physical.items() if n.connected]
            ready = [
                r
                for r in connected
                if (
                    self.physical[r].snapshot()["connection_state"] == "connected"
                    and self.physical[r].health is not None
                    and self.physical[r].health.state == "idle"
                    and self.physical[r].health.node_role == r
                )
            ]
            roles = (ready or connected)[:1] if count == 1 else ["A", "B"]
        if len(roles) != len(set(roles)) or any(r not in self.physical for r in roles):
            raise ValueError("Choose distinct node roles A and/or B")
        blockers = []
        if len(roles) < count:
            blockers.append(
                f"{code} requires {count} physical node(s); select/connect the required nodes"
            )
        identities = set()
        for role in roles:
            node = self.physical[role]
            snapshot = node.snapshot()
            if not node.connected or node.identity is None:
                blockers.append(f"Node {role} is disconnected")
                continue
            if snapshot["connection_state"] != "connected":
                blockers.append(f"Node {role} health is not fresh")
            identity = node.identity
            if identity.provenance != "hardware":
                blockers.append(f"Node {role} is not physical hardware")
            if identity.device_id in identities:
                blockers.append("Each role must identify a different physical device")
            identities.add(identity.device_id)
            if (
                node.health is None
                or node.health.node_role != role
                or node.health.state != "idle"
                or node.health.run_id is not None
            ):
                blockers.append(f"Node {role} must be owned by this role and idle")
            capabilities = entry["required_capabilities"]
            if count == 2 and "radio" not in capabilities:
                capabilities = [*capabilities, "radio"]
            for capability in capabilities:
                if not getattr(identity.capabilities, capability, False) or (
                    node.health is not None
                    and not getattr(node.health.capability_availability, capability, False)
                ):
                    blockers.append(f"Node {role} lacks {capability}")
        if entry["blocker"]:
            blockers.append(entry["blocker"])
        return {
            "catalog_id": code,
            "required_nodes": count,
            "roles": list(roles),
            "workload": workload,
            "ready": not blockers,
            "blockers": blockers,
            "scope": entry["scope"],
        }

    def campaign_case_preflight(self, case):
        selected = case["case"]
        if selected["kind"] == "procedure":
            result = self.preflight(selected["catalog_id"], selected["roles"], selected["workload"])
            result["blockers"].append(
                "Full procedure matrix execution is unavailable; plan reference retained"
            )
            result["ready"] = False
            result["scope"] = "required CDR procedure reference; no qualification claim"
            return result
        if selected["kind"] == "known_data":
            from .radio_runs import RadioRunRequest

            return self.radio.preflight(RadioRunRequest.model_validate(selected["request"]))
        if selected["kind"] == "voice":
            from .voice_runs import VoiceRunRequest

            return self.voice.preflight(VoiceRunRequest.model_validate(selected["request"]))
        if selected["kind"] == "serial_check":
            return self.preflight("IF-01", [selected["role"]], "local")
        node = self.physical[selected["role"]]
        blockers = []
        if not node.connected or node.identity is None:
            blockers.append(f"Node {selected['role']} is disconnected")
        else:
            if node.snapshot()["connection_state"] != "connected":
                blockers.append("Node health is not fresh")
            if (
                node.wire_profile != "node_control"
                or not node.health
                or node.health.state != "idle"
                or node.health.node_role != selected["role"]
            ):
                blockers.append("Matching owned idle main node is required")
            if selected["kind"] == "memory_probe":
                limits = node.identity.capabilities.resource_limits
                if "memory_probe" not in limits.get("diag_kinds", []):
                    blockers.append("Node memory probe is unavailable")
                if selected["iterations"] > limits.get("diag_max_iterations", 0) or selected[
                    "payload_bytes"
                ] > limits.get("diag_max_payload_bytes", 0):
                    blockers.append("Memory probe exceeds negotiated limits")
            elif selected["kind"] == "crypto_benchmark":
                try:
                    crypto_benchmark_v2.require_capability(
                        node.identity.capabilities,
                        node.health.capability_availability if node.health else None,
                    )
                except ValueError as exc:
                    blockers.append(str(exc))
            elif selected["kind"] == "audio":
                action = selected["action"]
                if action in ("codec", "decode"):
                    support = node.codec_availability()
                    needed = {"audio.decode"} | ({"audio.encode"} if action == "codec" else set())
                elif selected["wait_for_ptt"]:
                    support, needed = node.ptt_availability(), {"ptt.arm"}
                elif action == "retrieve":
                    support, needed = (
                        node.artifact_availability(),
                        {"artifact.list", "artifact.get"},
                    )
                else:
                    support, needed = node.audio_availability(), {f"audio.{action}"}
                if not needed <= set(support["commands"]):
                    blockers.append("Node lacks the required local audio/file commands")

        return {
            "ready": not blockers,
            "blockers": blockers,
            "required_nodes": 1,
            "scope": "local capability workflow; full procedure qualification remains separate",
        }

    async def connect_node(self, role: str, port: str | None):
        async with self.lock:
            if self.busy:
                raise RuntimeError("Stop the active check before changing node connections")
            if role not in self.physical:
                raise ValueError("Node role must be A or B")
            node = self.physical[role]
            if port is None:
                await node.close()
            else:
                ports = await asyncio.to_thread(discover_ports)
                if port not in {item["device"] for item in ports}:
                    raise ValueError("Selected serial port is no longer available; refresh ports")
                others = [n for r, n in self.physical.items() if r != role and n.connected]
                if any(n.port == port for n in others):
                    raise ValueError("This port is already assigned to the other node")
                await node.connect(port)
                if any(n.identity.device_id == node.identity.device_id for n in others):
                    await node.close()
                    raise ValueError("This physical device is already assigned to the other role")
            return node.snapshot()

    async def memory_probe(self, role, iterations, payload_bytes):
        async with self.lock:
            if self.busy:
                raise RuntimeError("Another check or operation already owns the bench")
            node = self.physical[role]
            if not node.connected or node.identity is None:
                raise ValueError("Connect the physical node first")
            limits = node.identity.capabilities.resource_limits
            if node.wire_profile != "node_control" or "memory_probe" not in limits.get(
                "diag_kinds", []
            ):
                raise ValueError("Matching main-node memory_probe firmware is required")
            binding = self.adapter.bind(role)
            status = await self.adapter.request(binding, "status.get")
            if status["state"] != "idle" or status["node_role"] != role:
                raise ValueError("Node must be owned and idle")
            if not 1 <= iterations <= limits.get("diag_max_iterations", 0):
                raise ValueError("Iterations exceed the node's negotiated limit")
            if not 1 <= payload_bytes <= limits.get("diag_max_payload_bytes", 0):
                raise ValueError("Payload exceeds the node's negotiated limit")
            return await self.diagnostics.start(
                role,
                binding,
                {"kind": "memory_probe", "iterations": iterations, "payload_bytes": payload_bytes},
            )

    async def crypto_benchmark(self, role, iterations, payload_bytes):
        async with self.lock:
            if self.busy:
                raise RuntimeError("Another check or operation already owns the bench")
            node = self.physical[role]
            if not node.connected or not node.identity or node.wire_profile != "node_control":
                raise ValueError("Connect matching main-node benchmark firmware first")
            binding = self.adapter.bind(role)
            await self.adapter.request(binding, "status.get")
            crypto_benchmark_v2.require_capability(
                node.identity.capabilities, node.health.capability_availability
            )
            if node.health.state != "idle" or node.health.node_role != role:
                raise ValueError("Node must be owned and idle")
            args = crypto_benchmark_v2.Arguments(iterations=iterations, payload_bytes=payload_bytes)
            return await self.diagnostics.start(role, binding, args.model_dump())

    def crypto_benchmark_evidence(self, role, operation_id, include_records=False):
        records = self.store.node_operation_records(role, operation_id)
        return {
            "operation_id": operation_id,
            "role": role,
            "assessment": crypto_benchmark_v2.assess(records),
            "records": records if include_records else None,
        }

    async def stop_node_operation(self, role, operation_id):
        async with self.lock:
            if self.procedures.busy or self.audio.busy or self.radio.busy:
                raise RuntimeError("Stop the active procedure/audio job through its own controls")
            if self.diagnostics.current and self.diagnostics.current["role"] == role:
                return await self.diagnostics.stop(operation_id)
            node = self.physical[role]
            if node.wire_profile != "node_control":
                raise ValueError("Matching main-node control firmware is required")
            active = node.active_operation or {}
            binding = active.get("physical_binding") or self.adapter.bind(role)
            original = result = None
            try:
                result = await self.adapter.request(
                    binding,
                    "operation.stop",
                    {"operation_id": operation_id},
                    on_record=lambda record: self.store.append_node_event(role, record),
                )
            except (OSError, ValueError, TimeoutError) as exc:
                original = exc
            cleanup = await self.adapter.cleanup(
                binding,
                operation_id=operation_id,
                on_record=lambda record: self.store.append_node_event(role, record),
            )
            self.store.append_node_event(
                role,
                {
                    "kind": "host_cleanup",
                    "operation_id": operation_id,
                    "physical_binding": binding,
                    "original_error": str(original) if original else None,
                    "cleanup": cleanup,
                },
            )
            if original:
                raise original
            if not cleanup["confirmed"]:
                raise ValueError(f"Operation cleanup unconfirmed: {cleanup['error']}")
            return {**result, "cleanup": cleanup}

    async def start_serial(self, request):
        async with self.lock:
            if self.busy:
                raise RuntimeError("Another check already owns the bench")
            readiness = self.preflight("IF-01", request.roles)
            if not readiness["ready"]:
                raise ValueError("; ".join(readiness["blockers"]))
            return await self.procedures.start_serial(request, readiness["roles"])

    async def start(self, spec):
        async with self.lock:
            if self.busy:
                raise RuntimeError("Another check already owns the bench")
            readiness = self.preflight(spec.catalog_id, spec.roles, spec.workload)
            if spec.catalog_id == "IF-01":
                raise ValueError("Use the IF-01 diagnostic check controls")
            raise ValueError("; ".join(readiness["blockers"]))

    def radio_preflight(self, request):
        result = self.radio.preflight(request)
        if self.busy:
            result["blockers"].append("Another check or operation owns the bench")
            result["ready"] = False
        return result

    async def start_radio(self, request):
        async with self.lock:
            if self.busy:
                raise RuntimeError("Another check or operation owns the bench")
            return await self.radio.start(request)

    def voice_preflight(self, request):
        ready = self.voice.preflight(request)
        if self.busy:
            ready["ready"] = False
            ready["blockers"].append("Another operation owns the bench")
        return ready

    async def start_voice(self, request):
        async with self.lock:
            if self.busy:
                raise RuntimeError("Another check or operation owns the bench")
            return await self.voice.start(request)

    async def stop(self):
        async with self.lock:
            if self.voice.busy:
                return await self.voice.stop()
            if self.radio.busy:
                return await self.radio.stop()
            if self.diagnostics.busy:
                return await self.diagnostics.stop()
            return await self.procedures.stop()

    async def artifact_action(self, action, role, *args, **kwargs):
        async with self.lock:
            if self.busy:
                raise RuntimeError("Another check, operation or file transfer owns the bench")
            return await getattr(self.artifacts, action)(role, *args, **kwargs)

    async def audio_action(self, role, action, **kwargs):
        async with self.lock:
            if self.busy:
                raise RuntimeError("Another check, file transfer or audio operation owns the bench")
            return await self.audio.start(role, action, **kwargs)

    async def close(self):
        await self.observations.close()
        await self.diagnostics.close()
        await self.voice.close()
        await self.radio.close()
        await self.audio.close()
        await self.artifacts.close()
        await self.procedures.stop(shutdown=True)
        for node in self.physical.values():
            await node.close()
        self.store.close()
