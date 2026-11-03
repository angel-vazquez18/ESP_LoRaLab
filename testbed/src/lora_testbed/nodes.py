"""Independent physical node sessions; all serial I/O stays outside the event loop."""

import asyncio
from collections import deque
from contextlib import suppress
from time import monotonic
from uuid import uuid4

import serial
from serial.tools.list_ports import comports

from . import v2
from .adapters import health_freshness, require_compatible


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
        self.error = None
        self.samples = deque(maxlen=90)
        self.diagnostics = deque(maxlen=100)
        self.tasks = []
        self.pending = {}
        self.command_lock = asyncio.Lock()

    def note(self, code, message):
        self.diagnostics.append({"at": monotonic(), "code": code, "message": message})

    def snapshot(self):
        age = monotonic() - self.last_health if self.last_health is not None else None
        return {
            "id": self.role,
            "connected": self.connected,
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
        self.sequence = self.event_seq = self.event_gaps = self.framing_errors = 0
        self.startup_records = 0
        self.samples.clear()
        self.diagnostics.clear()
        self.connection_state = "connecting"
        try:
            self.serial = await asyncio.to_thread(self.opener, port)
            self.connected = True
            self.tasks = [asyncio.create_task(self.read_loop())]
            hello = await self.request("hello")
            self.identity = v2.Hello.model_validate(hello)
            require_compatible(self.identity.model_dump(), v2.schema_digest(), "hardware")
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

    async def request(self, name, args=None, timeout=2.0, retries=2, on_record=None):
        async with self.command_lock:
            if not self.connected or self.serial is None:
                raise ValueError("Node is disconnected")
            self.sequence += 1
            command = v2.Command(
                command_id=str(uuid4()),
                client_id=self.client_id,
                command_seq=self.sequence,
                target_boot_id=self.identity.boot_id if self.identity else None,
                name=name,
                args=args or {},
            )
            future = asyncio.get_running_loop().create_future()
            self.pending[command.command_id] = (command.command_seq, future)
            try:
                for attempt in range(retries + 1):
                    wire = v2.encode(command)
                    if on_record:
                        on_record({"direction": "host_to_node", "record": command.model_dump()})
                    written = await asyncio.to_thread(self.serial.write, wire)
                    if written != len(wire):
                        raise ValueError("Incomplete serial write")
                    try:
                        reply = await asyncio.wait_for(asyncio.shield(future), timeout)
                        if on_record:
                            on_record({"direction": "node_to_host", "record": reply.model_dump()})
                        if not reply.ok:
                            raise ValueError(f"{reply.error.code}: {reply.error.message}")
                        return reply.result
                    except TimeoutError:
                        if attempt == retries:
                            raise ValueError(
                                f"No v2 reply to {name}; compatible firmware is required"
                            ) from None
            finally:
                self.pending.pop(command.command_id, None)
                if not future.done():
                    future.cancel()

    async def read_loop(self):
        decoder = v2.Decoder()
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
                            entry[1].set_result(record)
                    elif self.identity:
                        if record.event_seq <= self.event_seq:
                            continue
                        if self.event_seq:
                            self.event_gaps += record.event_seq - self.event_seq - 1
                        self.event_seq = record.event_seq
                        if record.name == "health":
                            self.health = v2.Health.model_validate(record.data)
                            self.last_health = monotonic()
                            self.samples.append(
                                {
                                    "uptime_us": self.health.uptime_us,
                                    **self.health.memory.internal.model_dump(),
                                }
                            )
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
        for _, future in self.pending.values():
            if not future.done():
                future.set_exception(ValueError(reason))

    async def keepalive_loop(self):
        try:
            while self.connected:
                await asyncio.sleep(1)
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
