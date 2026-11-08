"""Compatibility checks and the interface for future physical execution adapters."""

import asyncio
from typing import Protocol
from uuid import uuid4

from . import control_v2, v2


class NodeAdapter(Protocol):
    async def discover(self) -> list[dict]: ...
    async def connect(self) -> None: ...
    async def request(self, role: str, command: v2.Command) -> v2.Reply: ...
    async def next_event(self) -> dict: ...
    def snapshot(self) -> list[dict]: ...
    async def close(self) -> None: ...


class NodeFailure(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def require_compatible(identity, schema_sha256, provenance):
    """Validate wire/schema compatibility and required provenance for a node session."""
    if 2 not in identity["supported_wire_versions"]:
        raise NodeFailure("UNSUPPORTED_VERSION", "Firmware does not support wire version 2")
    if identity["contract_version"].split(".")[:2] != v2.CONTRACT_VERSION.split(".")[:2]:
        raise NodeFailure("UNSUPPORTED_VERSION", "Firmware contract major/minor mismatch")
    if identity["schema_sha256"] != schema_sha256:
        raise NodeFailure("UNSUPPORTED_VERSION", "Firmware schema mismatch")
    if identity["provenance"] != provenance:
        raise NodeFailure("UNSUPPORTED_VERSION", "Firmware provenance mismatch")


def require_control_compatible(identity):
    """Select a supported control surface by its exact generated schema digest."""
    profiles = {v2.schema_digest(): "diagnostic", control_v2.schema_digest(): "node_control"}
    digest = identity["schema_sha256"]
    if digest not in profiles:
        raise NodeFailure("UNSUPPORTED_VERSION", "Firmware schema mismatch")
    require_compatible(identity, digest, "hardware")
    return profiles[digest]


def health_freshness(age_s):
    if age_s is None:
        return "awaiting"
    return "unresponsive" if age_s > 5 else "stale" if age_s > 3 else "fresh"


class NodeClient:
    def __init__(self, adapter: NodeAdapter, result_models=None):
        self.adapter = adapter
        self.result_models = result_models or {}
        self.client_id = str(uuid4())
        self.identities: dict[str, dict] = {}
        self.sequences = dict.fromkeys("AB", 0)
        self.locks = {role: asyncio.Lock() for role in "AB"}

    def make_command(self, role, name, args=None, run_id=None):
        self.sequences[role] += 1
        return v2.Command(
            command_id=str(uuid4()),
            client_id=self.client_id,
            command_seq=self.sequences[role],
            target_boot_id=self.identities.get(role, {}).get("boot_id"),
            run_id=run_id,
            name=name,
            args=args or {},
        )

    async def request(self, role, name, args=None, run_id=None):
        async with self.locks[role]:
            command = self.make_command(role, name, args, run_id)
            for retry in range(3):
                try:
                    async with asyncio.timeout(2):
                        reply = await self.adapter.request(role, command)
                    break
                except TimeoutError:
                    if retry == 2:
                        raise NodeFailure("TIMEOUT", f"{role} did not reply to {name}") from None
                    if name in (
                        "hello",
                        "status.get",
                        "run.summary",
                        "artifact.list",
                        "artifact.get",
                    ):
                        self.sequences[role] += 1
                        command = command.model_copy(
                            update={"command_id": str(uuid4()), "command_seq": self.sequences[role]}
                        )
            if (reply.command_id, reply.command_seq) != (command.command_id, command.command_seq):
                raise NodeFailure("COMMAND_CONFLICT", "Reply correlation mismatch")
            if name != "hello":
                expected = self.identities[role]
                if (reply.device_id, reply.boot_id) != (expected["device_id"], expected["boot_id"]):
                    raise NodeFailure("STALE_BOOT", "Reply belongs to another device or boot")
            if not reply.ok:
                raise NodeFailure(reply.error.code, reply.error.message)
            if name in self.result_models:
                reply.result = self.result_models[name].model_validate(reply.result).model_dump()
            if name == "hello":
                identity = v2.Hello.model_validate(reply.result)
                self.identities[role] = identity.model_dump()
            return reply.result
