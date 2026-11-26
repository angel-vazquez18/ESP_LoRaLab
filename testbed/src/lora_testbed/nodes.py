"""Independent physical node sessions; all serial I/O stays outside the event loop."""

import asyncio
import hashlib
from collections import deque
from contextlib import suppress
from time import monotonic
from uuid import uuid4

import serial
from pydantic import ValidationError
from serial.tools.list_ports import comports

from . import (
    artifact_contract_v2,
    audio_contract_v2,
    codec_contract_v2,
    control_v2,
    crypto_benchmark_v2,
    memory_observation_v2,
    oled_status_v2,
    physical_wire_v2,
    ptt_contract_v2,
    run_protocol_v2,
    serial_framing,
    serial_replies,
    v2,
)
from .adapters import (
    health_freshness,
    require_artifact_compatible,
    require_control_compatible,
    require_execution_compatible,
)
from .session_keys import require_public_metadata, setup_facts, setup_reply


def discover_ports() -> list[dict]:
    return [
        {
            "device": p.device,
            "description": p.description,
            "serial_number": p.serial_number,
            "vid": p.vid,
            "pid": p.pid,
        }
        for p in comports()
    ]


def open_serial(port):
    connection = serial.Serial(
        port=None, baudrate=115200, timeout=0.1, write_timeout=1, exclusive=True
    )
    connection.dtr = False
    connection.rts = False
    connection.port = port
    connection.open()
    return connection


class NodeSession:
    def __init__(self, role: str, on_event, opener=open_serial):
        self.role, self.on_event, self.opener = role, on_event, opener
        self.port = None
        self.serial = None
        self.identity: v2.Hello | None = None
        self.health: v2.Health | None = None
        self.client_id = str(uuid4())
        self.sequence = 0
        self.event_seq = 0
        self.event_gaps = 0
        self.framing_errors = 0
        self.startup_records = 0
        self.last_health = None
        self.connected = False
        self.connection_state = "disconnected"
        self.connection_id = None
        self.active_operation = None
        self.error = None
        self.samples = deque(maxlen=90)
        self.diagnostics = deque(maxlen=100)
        self.tasks = []
        self.pending = {}
        self._reply_probe = None
        self.command_lock = asyncio.Lock()
        self.control_cycle_active = False
        self.rf_run_id = None
        self.rf_runs = deque(maxlen=8)
        self.wire_profile = None
        self.active_operation = None
        self.operation_results = deque(maxlen=16)
        self.memory_samples = deque(maxlen=512)
        self.memory_retention_drops = 0
        self.last_memory = None

    def accept_health(self, data):
        self.health = v2.Health.model_validate(data)
        self.last_health = monotonic()
        if (
            self.active_operation
            and self.health.uptime_us >= self.active_operation["accepted_at_us"]
            and self.health.operation_id is None
        ):
            self.active_operation = None

    def note(self, code, message):
        self.diagnostics.append({"at": monotonic(), "code": code, "message": message})

    def audio_availability(self):
        commands, blocked, limits = [], {}, None
        for name in audio_contract_v2.ARGUMENTS:
            try:
                if (
                    not self.connected
                    or self.connection_state != "connected"
                    or self.last_health is None
                    or health_freshness(monotonic() - self.last_health) in ("stale", "unresponsive")
                ) or self.wire_profile != "node_control":
                    raise ValueError("Connect a node with fresh audio health")
                limits = audio_contract_v2.require_capability(
                    self.identity.capabilities if self.identity else None,
                    self.health.capability_availability if self.health else None,
                    name,
                ).model_dump()
                commands.append(name)
            except ValueError as exc:
                blocked[name] = str(exc)
        return {"commands": commands, "blocked": blocked, "limits": limits}

    def display_observation(self):
        value = (
            self.health.capability_availability.resource_limits.get("oled") if self.health else None
        )
        if value is None:
            return {"configured": False, "state": "not_advertised", "ready": False}
        try:
            observed = oled_status_v2.Status.model_validate(value)
            if observed.schema_sha256 != oled_status_v2.schema_digest():
                raise ValueError("OLED observation fingerprint does not match")
            fresh = (
                self.connected
                and self.connection_state == "connected"
                and self.last_health is not None
                and health_freshness(monotonic() - self.last_health)
                not in ("stale", "unresponsive")
            )
            return {
                **observed.model_dump(),
                "configured": True,
                "fresh": fresh,
                "ready": fresh and observed.state == "ready",
            }
        except ValueError as exc:
            return {"configured": True, "state": "incompatible", "ready": False, "error": str(exc)}

    def ptt_availability(self):
        try:
            audio = self.audio_availability()
            if "audio.capture" not in audio["commands"]:
                raise ValueError(audio["blocked"].get("audio.capture", "Capture is unavailable"))
            limits = ptt_contract_v2.require_capability(
                self.identity.capabilities, self.health.capability_availability
            )
            return {
                "commands": ["ptt.arm"],
                "limits": {
                    **limits.model_dump(),
                    **ptt_contract_v2.POLICY,
                },
                "blocked": {},
            }
        except ValueError as exc:
            return {"commands": [], "limits": None, "blocked": {"ptt.arm": str(exc)}}

    def memory_availability(self):
        try:
            if (
                not self.connected
                or self.connection_state != "connected"
                or self.wire_profile != "node_control"
                or self.last_health is None
                or health_freshness(monotonic() - self.last_health) in ("stale", "unresponsive")
            ):
                raise ValueError("Connect a node with fresh memory observation health")
            limits = memory_observation_v2.require_capability(
                self.identity.capabilities if self.identity else None,
                self.health.capability_availability if self.health else None,
            )
            return {
                "commands": list(memory_observation_v2.ARGUMENTS),
                "limits": {**limits.model_dump(), **memory_observation_v2.POLICY},
                "blocked": {},
            }
        except ValueError as exc:
            return {
                "commands": [],
                "limits": None,
                "blocked": {name: str(exc) for name in memory_observation_v2.ARGUMENTS},
            }

    def memory_observation(self):
        return {
            "fresh": bool(
                self.memory_availability()["commands"]
                and self.last_memory is not None
                and monotonic() - self.last_memory <= 1
            ),
            "last_sample": self.memory_samples[-1] if self.memory_samples else None,
            "retained_samples": len(self.memory_samples),
            "retained_limit": self.memory_samples.maxlen,
            "retention_drops": self.memory_retention_drops,
        }

    def codec_availability(self):
        commands, blocked, limits = [], {}, None
        for name in codec_contract_v2.ARGUMENTS:
            try:
                if (
                    not self.connected
                    or self.connection_state != "connected"
                    or self.last_health is None
                    or health_freshness(monotonic() - self.last_health) in ("stale", "unresponsive")
                    or self.wire_profile != "node_control"
                ):
                    raise ValueError("Connect a node with fresh codec health")
                limits = codec_contract_v2.require_capability(
                    self.identity.capabilities if self.identity else None,
                    self.health.capability_availability if self.health else None,
                    name,
                ).model_dump()
                commands.append(name)
            except ValueError as exc:
                blocked[name] = str(exc)
        return {"commands": commands, "blocked": blocked, "limits": limits}

    def artifact_availability(self):
        commands, blocked, limits = [], {}, None
        for name in artifact_contract_v2.ARGUMENTS:
            try:
                if not self.connected or self.identity is None:
                    raise ValueError("Connect the node to use its files")
                value = require_artifact_compatible(
                    self.identity.model_dump(),
                    name,
                    self.health.capability_availability.model_dump() if self.health else None,
                )
                commands.append(name)
                limits = value.model_dump()
            except ValueError as exc:
                blocked[name] = str(exc)
        return {"commands": commands, "blocked": blocked, "limits": limits}

    def snapshot(self):
        age = monotonic() - self.last_health if self.last_health is not None else None
        return {
            "id": self.role,
            "wire_profile": self.wire_profile,
            "artifact_support": self.artifact_availability(),
            "audio_support": self.audio_availability(),
            "ptt_support": self.ptt_availability(),
            "memory_support": self.memory_availability(),
            "memory_observation": self.memory_observation(),
            "display": self.display_observation(),
            "codec_support": self.codec_availability(),
            "active_operation": self.active_operation,
            "operation_results": list(self.operation_results),
            "connected": self.connected,
            "connection_id": self.connection_id,
            "port": self.port,
            "connection_state": health_freshness(age)
            if self.connected and health_freshness(age) in ("stale", "unresponsive")
            else self.connection_state,
            "identity": self.identity.model_dump() if self.identity else None,
            "health": self.health.model_dump() if self.health else None,
            "last_seen_age_s": round(age, 1) if age is not None else None,
            "error": self.error,
            "event_gaps": self.event_gaps,
            "framing_errors": self.framing_errors,
            "startup_records": self.startup_records,
            "samples": list(self.samples),
            "diagnostics": list(self.diagnostics),
        }

    async def connect(self, port):
        await self.close()
        self.port, self.error = port, None
        self.identity, self.health = None, None
        self.last_health = None
        self.event_seq = self.event_gaps = self.framing_errors = 0
        self.startup_records = 0
        self.rf_run_id = None
        self.rf_runs = deque(maxlen=8)
        self.wire_profile = None
        self.active_operation = None
        self.operation_results.clear()
        self.memory_samples.clear()
        self.memory_retention_drops = 0
        self.last_memory = None
        self.samples.clear()
        self.diagnostics.clear()
        self.connection_state = "connecting"
        self.connection_id = str(uuid4())
        try:
            self.serial = await asyncio.to_thread(self.opener, port)
            self.connected = True
            self.tasks = [asyncio.create_task(self.read_loop())]
            hello = await self.request("hello")
            self.identity = v2.Hello.model_validate(hello)
            self.wire_profile = require_control_compatible(self.identity.model_dump())
            await self.request("control.claim", {"node_role": self.role})
            self.health = v2.Health.model_validate(await self.request("status.get"))
            self.last_health = monotonic()
            self.connection_state = "connected"
            self.note("connected", f"Identified {self.identity.device_id}")
            self.tasks.append(asyncio.create_task(self.keepalive_loop()))
        except Exception as exc:
            await self.close(release=False)
            self.connection_state = "error"
            self.error = str(exc)
            raise ValueError(f"Node {self.role}: {exc}") from exc

    async def write_wire(self, wire):
        task = asyncio.create_task(asyncio.to_thread(self.serial.write, wire))
        cancelled = False
        while True:
            try:
                written = await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
                cancelled = True  # Keep the command lock until the bounded write finishes.
        if cancelled:
            raise asyncio.CancelledError
        return written

    def _next_command(self, name, args=None, run_id=None):
        self.sequence += 1
        return v2.Command(
            command_id=str(uuid4()),
            client_id=self.client_id,
            command_seq=self.sequence,
            target_boot_id=self.identity.boot_id if self.identity else None,
            name=name,
            run_id=run_id,
            args=args or {},
        )

    async def request(
        self,
        name,
        args=None,
        timeout=2.0,
        retries=2,
        on_record=None,
        run_id=None,
        key_set_id=None,
        *,
        _reply_probe=None,
    ):
        async with self.command_lock:
            if _reply_probe is not None and name != "diag.run":
                raise ValueError("Reply perturbation is limited to the fixed diagnostic case")
            if not self.connected or self.serial is None:
                raise ValueError("Node is disconnected")
            execution_command = name in run_protocol_v2.EXECUTION_COMMANDS
            if execution_command:
                if self.identity is None or self.health is None:
                    raise ValueError("MISSING_CAPABILITY: Execution identity/health unavailable")
                if name not in run_protocol_v2.CLEANUP_COMMANDS and (
                    self.last_health is None or monotonic() - self.last_health > 3
                ):
                    raise ValueError("MISSING_CAPABILITY: Execution needs fresh health")
                require_execution_compatible(
                    self.identity.model_dump(),
                    name,
                    self.health.capability_availability.model_dump(),
                )
                try:
                    args = run_protocol_v2.ARGUMENTS[name].model_validate(args or {}).model_dump()
                except ValidationError:
                    if name == "session.open":
                        # Pydantic errors can echo rejected key values.
                        raise ValueError(
                            "INVALID_ARGUMENT: Invalid session.open arguments"
                        ) from None
                    raise
                if name == "session.open" and args["security"] != "none":
                    if not all(
                        caps.security_gcm
                        for caps in (
                            self.identity.capabilities,
                            self.health.capability_availability,
                        )
                    ):
                        raise ValueError(
                            "MISSING_CAPABILITY: Protected node support is unavailable"
                        )
                    key_set_id = key_set_id or str(uuid4())
                    try:
                        from uuid import UUID

                        if str(UUID(key_set_id)) != key_set_id:
                            raise ValueError()
                    except (ValueError, TypeError, AttributeError):
                        raise ValueError("Invalid key set identity") from None
                if name.startswith(("run.", "session.", "fault.")) and run_id is None:
                    raise ValueError("INVALID_ARGUMENT: Execution requires run_id")
            if name in memory_observation_v2.ARGUMENTS:
                available = self.memory_availability()
                if name not in available["commands"]:
                    raise ValueError(available["blocked"][name])
                if run_id is not None:
                    raise ValueError("Memory observation commands require null run_id")
                args = memory_observation_v2.ARGUMENTS[name].model_validate(args or {}).model_dump()
            if name in codec_contract_v2.ARGUMENTS:
                availability = self.codec_availability()
                if name not in availability["commands"]:
                    raise ValueError(
                        availability["blocked"].get(name, "Codec command is unavailable")
                    )
                args = codec_contract_v2.ARGUMENTS[name].model_validate(args).model_dump()
            artifact_limits = None
            if name in artifact_contract_v2.ARGUMENTS:
                if self.identity is None:
                    raise ValueError("MISSING_CAPABILITY: Artifact identity is not available")
                availability = (
                    self.health.capability_availability.model_dump() if self.health else None
                )
                artifact_limits = require_artifact_compatible(
                    self.identity.model_dump(), name, availability
                )
                args = artifact_contract_v2.validate_arguments(
                    name, {} if args is None else args, artifact_limits
                ).model_dump()
            if name in ptt_contract_v2.ARGUMENTS:
                availability = self.ptt_availability()
                if name not in availability["commands"]:
                    raise ValueError(availability["blocked"][name])
                args = ptt_contract_v2.ARGUMENTS[name].model_validate(args or {}).model_dump()
            if name in audio_contract_v2.ARGUMENTS:
                if (
                    self.wire_profile != "node_control"
                    or self.identity is None
                    or self.health is None
                ):
                    raise ValueError(
                        "MISSING_CAPABILITY: Audio control identity/health is unavailable"
                    )
                audio_contract_v2.require_capability(
                    self.identity.capabilities, self.health.capability_availability, name
                )
                args = audio_contract_v2.ARGUMENTS[name].model_validate(args or {}).model_dump()
            if name == "diag.run" and (args or {}).get("kind") == "crypto_benchmark":
                if self.wire_profile != "node_control" or not self.identity or not self.health:
                    raise ValueError("Matching main-node benchmark identity and health required")
                crypto_benchmark_v2.require_capability(
                    self.identity.capabilities, self.health.capability_availability
                )
                args = crypto_benchmark_v2.Arguments.model_validate(args).model_dump()
            protected_setup = (
                name == "session.open" and (args or {}).get("security") == "aes128_gcm"
            )
            command = self._next_command(name, args, run_id)
            if execution_command:
                run_protocol_v2.Command.model_validate(command.model_dump())
            if name == "session.open":
                if self.rf_run_id and self.rf_run_id != run_id:
                    raise ValueError("Close the existing RF session before opening another")
                # Track attempted ownership before writing; a lost reply may still mean open.
                self.rf_run_id = run_id
                self.rf_runs.append(run_id)
            future = asyncio.get_running_loop().create_future()
            self.pending[command.command_id] = (command.command_seq, future)
            if _reply_probe:
                self._reply_probe = (command.command_id, _reply_probe)
            try:
                for attempt in range(retries + 1):
                    wire = v2.encode(command)
                    if on_record:
                        snapshot = (
                            setup_facts(command, self.role, key_set_id)
                            if protected_setup
                            else command.model_dump()
                        )
                        require_public_metadata(snapshot)
                        on_record({"direction": "host_to_node", "record": snapshot})
                    try:
                        written = await self.write_wire(wire)
                    except Exception:
                        if protected_setup:
                            raise ValueError(
                                "Protected session write failed; cleanup is required"
                            ) from None
                        raise
                    if written != len(wire):
                        raise ValueError("Incomplete serial write")
                    try:
                        reply = await asyncio.wait_for(asyncio.shield(future), timeout)
                        safe_reply = (
                            setup_reply(command, reply, self.role, key_set_id)
                            if protected_setup
                            else reply.model_dump()
                        )
                        if on_record:
                            require_public_metadata(safe_reply)
                            on_record({"direction": "node_to_host", "record": safe_reply})
                        if not reply.ok:
                            if protected_setup:
                                raise ValueError(
                                    f"{safe_reply['error']['code']}: "
                                    "Protected session setup rejected"
                                ) from None
                            raise ValueError(f"{reply.error.code}: {reply.error.message}")
                        if name == "status.get":
                            self.accept_health(reply.result)
                        if (
                            name == "diag.run"
                            or name in audio_contract_v2.ARGUMENTS
                            or name in ptt_contract_v2.ARGUMENTS
                            or name in codec_contract_v2.ARGUMENTS
                        ):
                            operation = control_v2.AcceptedOperation.model_validate(
                                reply.result
                            ).model_dump()
                            if not any(
                                r["operation_id"] == operation.get("operation_id")
                                for r in self.operation_results
                            ):
                                self.active_operation = {
                                    **operation,
                                    "accepted_at_us": reply.uptime_us,
                                    "physical_binding": {
                                        "role": self.role,
                                        "device_id": self.identity.device_id,
                                        "boot_id": self.identity.boot_id,
                                        "connection_id": self.connection_id,
                                    },
                                }
                        elif name == "operation.stop":
                            self.active_operation = None
                        if artifact_limits is not None:
                            return artifact_contract_v2.validate_result(
                                name, command.args, reply.result, artifact_limits
                            ).model_dump()
                        if name == "session.close":
                            self.rf_run_id = None
                        if name in memory_observation_v2.RESULTS:
                            return (
                                memory_observation_v2.RESULTS[name]
                                .model_validate(reply.result)
                                .model_dump()
                            )
                        if execution_command:
                            return (
                                run_protocol_v2.RESULTS[name]
                                .model_validate(reply.result)
                                .model_dump()
                            )
                        return reply.result
                    except TimeoutError:
                        if attempt == retries:
                            raise ValueError(
                                f"No v2 reply to {name}; compatible firmware is required"
                            ) from None
                        if name in (
                            "hello",
                            "status.get",
                            "run.summary",
                            "run.source",
                            "fault.status",
                            "artifact.list",
                            "artifact.get",
                        ):
                            self.pending.pop(command.command_id, None)
                            future.cancel()
                            self.sequence += 1
                            command = command.model_copy(
                                update={"command_id": str(uuid4()), "command_seq": self.sequence}
                            )
                            future = asyncio.get_running_loop().create_future()
                            self.pending[command.command_id] = (command.command_seq, future)
            finally:
                if _reply_probe:
                    self._reply_probe = None
                    _reply_probe.close()
                self.pending.pop(command.command_id, None)
                if not future.done():
                    future.cancel()

    async def read_loop(self):
        decoder = v2.Decoder(adapter=physical_wire_v2.ADAPTER)
        try:
            while self.connected:
                data = await asyncio.to_thread(self.serial.read, 1024)
                records, errors = decoder.feed(data)
                if self.identity:
                    self.framing_errors += len(errors)
                else:
                    self.startup_records += len(errors)
                    if errors and not self.diagnostics:
                        self.note(
                            "startup_input", "Startup text discarded before identity handshake"
                        )
                if (
                    self.identity
                    and errors
                    and (not self.diagnostics or self.diagnostics[-1]["code"] != "framing")
                ):
                    self.note("framing", "Non-protocol or malformed serial input discarded")
                for record in records:
                    if isinstance(record, v2.Command):
                        self.note(
                            "unexpected_command", "Node sent a command instead of a reply/event"
                        )
                        continue
                    if self.identity and (
                        record.boot_id != self.identity.boot_id
                        or record.device_id != self.identity.device_id
                    ):
                        raise ValueError(
                            "Device reset or identity changed; reconnect for a new session"
                        )
                    if isinstance(record, v2.Reply):
                        entry = self.pending.get(record.command_id)
                        if entry and entry[0] == record.command_seq and not entry[1].done():
                            if self._reply_probe and self._reply_probe[0] == record.command_id:
                                if self._reply_probe[1].intercept(record, entry[1]):
                                    continue
                            entry[1].set_result(record)
                    elif self.identity:
                        if record.name == "memory.sample":
                            if self.wire_profile != "node_control" or not self.health:
                                raise ValueError(
                                    "Memory observation outside negotiated main profile"
                                )
                            memory_observation_v2.require_capability(
                                self.identity.capabilities, self.health.capability_availability
                            )
                        elif record.name == "crypto.benchmark":
                            if self.wire_profile != "node_control" or not self.health:
                                raise ValueError("Benchmark event outside negotiated main profile")
                            crypto_benchmark_v2.require_capability(
                                self.identity.capabilities, self.health.capability_availability
                            )
                        elif record.name not in ("health", "diagnostic", "operation.result"):
                            require_execution_compatible(
                                self.identity.model_dump(),
                                "fault.status"
                                if record.name.startswith("fault.")
                                else "run.summary",
                                self.health.capability_availability.model_dump()
                                if self.health
                                else None,
                            )
                            if record.run_id not in self.rf_runs:
                                raise ValueError("RF event belongs to another run")
                        if (
                            record.name == "operation.result"
                            and self.wire_profile != "node_control"
                        ):
                            raise ValueError("Operation event outside negotiated diagnostic schema")
                        if record.event_seq <= self.event_seq:
                            continue
                        if self.event_seq:
                            self.event_gaps += record.event_seq - self.event_seq - 1
                        self.event_seq = record.event_seq
                        if record.name == "memory.sample":
                            if len(self.memory_samples) == self.memory_samples.maxlen:
                                self.memory_retention_drops += 1
                            self.memory_samples.append(record.data.model_dump())
                            self.last_memory = monotonic()
                        elif record.name == "health":
                            self.accept_health(record.data)
                            self.samples.append(
                                {
                                    "uptime_us": self.health.uptime_us,
                                    **self.health.memory.internal.model_dump(),
                                }
                            )
                        elif record.name == "operation.result":
                            self.operation_results.append(record.model_dump()["data"])
                            if (
                                self.active_operation
                                and self.active_operation["operation_id"]
                                == record.data["operation_id"]
                            ):
                                self.active_operation = None
                        self.on_event(self.role, record.model_dump())
        except Exception as exc:
            self.fail(str(exc))
        finally:
            if not self.connected and self.serial:
                await asyncio.to_thread(self.serial.close)

    def fail(self, reason):
        self.error = reason
        self.connection_state = "error"
        self.connected = False
        self.note("connection_lost", reason)
        self.active_operation = None
        for _, future in self.pending.values():
            if not future.done():
                future.set_exception(ValueError(reason))

    async def exercise_serial_framing(self, variant, on_record):
        if variant not in serial_framing.VARIANTS:
            raise ValueError("Unknown serial framing case")
        async with self.command_lock:
            if not self.connected or not self.identity or self.wire_profile != "node_control":
                raise ValueError("Framing cases require a compatible connected node")
            commands = [
                self._next_command("status.get")
                for _ in range(serial_framing.STATUS_COUNTS.get(variant, 1))
            ]
            batches = serial_framing.batches(variant, [v2.encode(cmd) for cmd in commands])
            start = 0
            replies = []
            for chunks, count in batches:
                selected = commands[start : start + count]
                for reply in await self._fixed_serial_exchange(chunks, selected, on_record):
                    if not reply.ok:
                        raise ValueError(f"{reply.error.code}: {reply.error.message}")
                    replies.append(reply)
                start += count
        result = replies[-1].result
        if variant == "split_every_boundary":
            checked = await asyncio.to_thread(serial_framing.exercise_decoder, replies[-1])
            on_record({"direction": "host_fixture", "framing_boundaries": checked})
        else:
            checked = None
        return result, checked

    def configuration_probe_blocker(self):
        if not self.connected or not self.identity or not self.health:
            return "Configuration rejection needs a connected radio node"
        try:
            require_execution_compatible(
                self.identity.model_dump(),
                "config.set",
                self.health.capability_availability.model_dump(),
            )
        except ValueError as exc:
            return str(exc)
        return None

    async def exercise_configuration_rejection(self, on_record):
        async with self.command_lock:
            if blocker := self.configuration_probe_blocker():
                raise ValueError(blocker)
            args = run_protocol_v2.Configuration(
                radio=run_protocol_v2.Radio(), link=run_protocol_v2.Link()
            ).model_dump()
            # The procedure sends only this fixed, out-of-band frequency.
            args["radio"]["frequency_hz"] = 0
            command = self._next_command("config.set", args)
            [reply] = await self._fixed_serial_exchange([v2.encode(command)], [command], on_record)
        return reply

    async def _fixed_serial_exchange(self, chunks, commands, on_record):
        futures = [asyncio.get_running_loop().create_future() for _ in commands]
        for cmd, future in zip(commands, futures, strict=True):
            self.pending[cmd.command_id] = (cmd.command_seq, future)
        replies = []
        try:
            on_record(
                {
                    "direction": "host_fixture",
                    "serial_writes": [
                        {"bytes": len(chunk), "sha256": hashlib.sha256(chunk).hexdigest()}
                        for chunk in chunks
                    ],
                }
            )
            for cmd in commands:
                on_record({"direction": "host_to_node", "record": cmd.model_dump()})
            try:
                for chunk in chunks:
                    if await self.write_wire(chunk) != len(chunk):
                        raise ValueError("Incomplete serial procedure write")
                    if not chunk.endswith(b"\n"):
                        await asyncio.sleep(0.03)
            except (Exception, asyncio.CancelledError):
                # Interrupted multi-write input may leave the receiver inside a record.
                await self.close(release=False)
                raise
            async with asyncio.timeout(2):
                for command, future in zip(commands, futures, strict=True):
                    reply = await asyncio.shield(future)
                    data = reply.model_dump()
                    require_public_metadata(data)
                    on_record({"direction": "node_to_host", "record": data})
                    if reply.ok and command.name == "status.get":
                        self.accept_health(reply.result)
                    replies.append(reply)
        finally:
            for cmd, future in zip(commands, futures, strict=True):
                self.pending.pop(cmd.command_id, None)
                if future.done() and not future.cancelled():
                    future.exception()
                else:
                    future.cancel()
        return replies

    async def exercise_reply_recovery(self, variant, on_record):
        if variant not in serial_replies.VARIANTS:
            raise ValueError("Unknown reply perturbation case")
        probe = serial_replies.ReplyProbe(variant, on_record)
        before = {result["operation_id"] for result in self.operation_results}
        accepted = None
        timed_out = False
        try:
            accepted = await self.request(
                "diag.run",
                {"kind": "memory_probe", "iterations": 1, "payload_bytes": 512},
                timeout=serial_replies.REPLY_TIMEOUT_S,
                retries=probe.retries,
                on_record=probe.record_exchange,
                _reply_probe=probe,
            )
        except ValueError as exc:
            if probe.retries or not str(exc).startswith("No v2 reply to diag.run;"):
                raise
            timed_out = True
        if not probe.first or not probe.first.ok:
            raise ValueError("The fixture did not observe an accepted diagnostic reply")
        operation = control_v2.AcceptedOperation.model_validate(probe.first.result)
        async with asyncio.timeout(2):
            while not any(
                r["operation_id"] == operation.operation_id for r in self.operation_results
            ):
                await asyncio.sleep(0.01)
        results = [r for r in self.operation_results if r["operation_id"] not in before]
        single_result = (
            len(results) == 1
            and results[0]["operation_id"] == operation.operation_id
            and results[0]["status"] == "completed"
            and results[0]["result"]["iterations_completed"] == 1
        )
        same_wire = (
            len(probe.write_sha256) == probe.retries + 1 and len(set(probe.write_sha256)) == 1
        )
        expected_reply = timed_out if probe.retries == 0 else accepted == probe.first.result
        passed = (
            single_result
            and same_wire
            and expected_reply
            and (variant != "delayed_reply" or probe.delivered_delayed)
        )
        return {
            "direction": "host_assessment",
            "reply_recovery": variant,
            "timed_out": timed_out,
            "delayed_reply_delivered": probe.delivered_delayed,
            "write_sha256": probe.write_sha256,
            "operation_id": operation.operation_id,
            "operation_results": results,
            "outcome": "pass" if passed else "fail",
        }

    async def exercise_reply_conflict(self, on_record):
        async with self.command_lock:
            command = self._next_command("control.keepalive")
            [prior] = await self._fixed_serial_exchange([v2.encode(command)], [command], on_record)
            if not prior.ok:
                raise ValueError(f"Original keepalive failed: {prior.error.code}")
            changed = command.model_copy(update={"args": {"unrecognized_parameter": True}})
            [reply] = await self._fixed_serial_exchange([v2.encode(changed)], [changed], on_record)
        if reply.ok or reply.error.code != "COMMAND_CONFLICT":
            raise ValueError(
                "Reused command identity with changed bytes did not return COMMAND_CONFLICT"
            )

    async def exercise_competing_claim(self, on_record):
        async with self.command_lock:
            command = self._next_command("control.claim", {"node_role": self.role}).model_copy(
                update={"client_id": str(uuid4()), "command_seq": 1}
            )
            [reply] = await self._fixed_serial_exchange([v2.encode(command)], [command], on_record)
            if reply.ok:
                await self.close(release=False)
                raise ValueError("The competing client unexpectedly acquired ownership")
            if reply.error.code != "BUSY":
                raise ValueError(f"Unexpected competing claim reply: {reply.error.code}")

    async def exercise_lease_recovery(self, on_record):
        if self.control_cycle_active or not self.identity or not self.connected:
            raise ValueError("A connected node with exclusive control is required")
        identity = (self.connection_id, self.identity.device_id, self.identity.boot_id)
        options = {"on_record": on_record, "timeout": 0.75, "retries": 0}
        self.control_cycle_active = True
        try:
            lease = await self.request("control.keepalive", **options)
            expiry = run_protocol_v2.Lease.model_validate(lease).lease_expires_us
            async with asyncio.timeout(7):
                while self.connected:
                    observed = self.health
                    if observed.uptime_us >= expiry and observed.node_role is None:
                        break
                    await asyncio.sleep(0.025)
                else:
                    raise ValueError("Connection closed before lease expiry was observed")
            if observed.state != "idle" or observed.run_id or observed.operation_id:
                raise ValueError("Lease expiry did not leave the node idle")
            on_record(
                {
                    "direction": "host_assessment",
                    "lease_expires_us": expiry,
                    "expired_health": observed.model_dump(),
                    "observed_after_us": observed.uptime_us - expiry,
                }
            )
            try:
                await self.request("status.get", **options)
            except ValueError as exc:
                if not str(exc).startswith("NOT_OWNER:"):
                    raise
            else:
                raise ValueError("The expired claim remained usable")
            await self.request("control.claim", {"node_role": self.role}, **options)
        except (Exception, asyncio.CancelledError):
            await self._recover_control_after_probe(identity)
            raise
        finally:
            self.control_cycle_active = False

    async def _recover_control_after_probe(self, identity):
        if (
            self.connected
            and self.identity
            and (self.connection_id, self.identity.device_id, self.identity.boot_id) == identity
        ):
            try:
                await self.request(
                    "control.claim", {"node_role": self.role}, timeout=0.5, retries=0
                )
            except (OSError, ValueError, TimeoutError):
                await self.close(release=False)

    async def exercise_control_cycle(self, on_record):
        if self.control_cycle_active or not self.identity or not self.connected:
            raise ValueError("A connected node with exclusive control is required")
        identity = (self.connection_id, self.identity.device_id, self.identity.boot_id)
        options = {"on_record": on_record, "timeout": 0.75, "retries": 0}
        self.control_cycle_active = True
        try:
            hello = v2.Hello.model_validate(await self.request("hello", **options))
            require_control_compatible(hello.model_dump())
            if (hello.device_id, hello.boot_id) != identity[1:]:
                raise ValueError("Node identity changed during the control cycle")
            before = await self.request("status.get", **options)
            if before["node_role"] != self.role or before["state"] != "idle":
                raise ValueError("Control cycle requires an owned idle node")
            await self.request("control.keepalive", **options)
            await self.request("control.release", **options)
            try:
                await self.request("status.get", **options)
            except ValueError as exc:
                if not str(exc).startswith("NOT_OWNER:"):
                    raise
            else:
                raise ValueError("Status unexpectedly remained available to the released client")
            await self.request("control.claim", {"node_role": self.role}, **options)
            after = await self.request("status.get", **options)
            if (
                not self.identity
                or (self.connection_id, self.identity.device_id, self.identity.boot_id) != identity
                or after["node_role"] != self.role
                or after["state"] != "idle"
                or after["uptime_us"] <= before["uptime_us"]
                or after["telemetry_drops"] != before["telemetry_drops"]
            ):
                raise ValueError("Control cycle did not restore the same healthy idle node")
        except (Exception, asyncio.CancelledError):
            await self._recover_control_after_probe(identity)
            raise
        finally:
            self.control_cycle_active = False

    async def keepalive_loop(self):
        try:
            while self.connected:
                await asyncio.sleep(1)
                if self.control_cycle_active:
                    continue
                if (
                    self.last_health is not None
                    and health_freshness(monotonic() - self.last_health) == "unresponsive"
                ):
                    raise ValueError("Node health telemetry timed out; reconnect to recover")
                await self.request("control.keepalive")
        except (OSError, ValueError) as exc:
            self.fail(str(exc))

    async def close(self, release=True):
        if release and self.connected and self.identity:
            if self.rf_run_id:
                with suppress(OSError, ValueError):
                    await self.request(
                        "run.stop",
                        {"reason": "host_shutdown"},
                        run_id=self.rf_run_id,
                        timeout=0.5,
                        retries=0,
                    )
                with suppress(OSError, ValueError):
                    await self.request(
                        "session.close", run_id=self.rf_run_id, timeout=0.5, retries=0
                    )
            if self.active_operation:
                with suppress(OSError, ValueError):
                    await self.request(
                        "operation.stop",
                        {"operation_id": self.active_operation["operation_id"]},
                        timeout=0.5,
                        retries=0,
                    )
            with suppress(OSError, ValueError):
                await self.request("control.release", timeout=0.5, retries=0)
        self.connected = False
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with suppress(asyncio.CancelledError):
                await task
        self.tasks.clear()
        if self.serial:
            await asyncio.to_thread(self.serial.close)
            self.serial = None
        self.pending.clear()
        self.connection_state = "disconnected"
        self.active_operation = None
