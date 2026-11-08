"""One physical bench owner shared by the dashboard and CLI."""

import asyncio
from pathlib import Path

from . import __version__
from .catalog import catalog, required_nodes
from .nodes import NodeSession, discover_ports
from .procedure_runs import ProcedureService
from .run_records_v2 import RunRecords
from .storage import Store


class Host:
    def __init__(self, data_dir: Path):
        self.store = Store(data_dir)
        self.lock = asyncio.Lock()
        self.mode = "hardware"
        self.physical = {role: NodeSession(role, self.store.append_node_event) for role in "AB"}
        self.records = RunRecords(self.store)  # Retain access to historical evidence.
        self.procedures = ProcedureService(self.store, self.physical)

    @property
    def busy(self) -> bool:
        return self.procedures.busy or any(
            n.active_operation is not None for n in self.physical.values()
        )

    def snapshot(self) -> dict:
        nodes = [node.snapshot() for node in self.physical.values()]
        return {
            "version": __version__,
            "mode": "hardware",
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
            status = await node.request("status.get")
            if status["state"] != "idle" or status["node_role"] != role:
                raise ValueError("Node must be owned and idle")
            if not 1 <= iterations <= limits.get("diag_max_iterations", 0):
                raise ValueError("Iterations exceed the node's negotiated limit")
            if not 1 <= payload_bytes <= limits.get("diag_max_payload_bytes", 0):
                raise ValueError("Payload exceeds the node's negotiated limit")
            return await node.request(
                "diag.run",
                {"kind": "memory_probe", "iterations": iterations, "payload_bytes": payload_bytes},
                on_record=lambda record: self.store.append_node_event(role, record),
            )

    async def stop_node_operation(self, role, operation_id):
        async with self.lock:
            if self.procedures.busy:
                raise RuntimeError("Stop the procedure through its own controls")
            node = self.physical[role]
            if node.wire_profile != "node_control":
                raise ValueError("Matching main-node control firmware is required")
            return await node.request(
                "operation.stop",
                {"operation_id": operation_id},
                on_record=lambda record: self.store.append_node_event(role, record),
            )

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

    async def stop(self):
        async with self.lock:
            return await self.procedures.stop()

    async def close(self):
        await self.procedures.stop(shutdown=True)
        for node in self.physical.values():
            await node.close()
        self.store.close()
