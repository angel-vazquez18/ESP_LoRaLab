"""One-shot hello fixtures for the IF-01 compatibility gate."""

from queue import Empty, Queue

from . import v2

INCOMPATIBILITIES = {
    "wire_version": ("supported_wire_versions", [1], "Firmware does not support wire version 2"),
    "contract_version": ("contract_version", "0.0.0", "Firmware contract major/minor mismatch"),
    "schema_digest": ("schema_sha256", "0" * 64, "Firmware schema mismatch"),
}


class IdentityFixture:
    """Answer only a bootstrap hello. This port has no claims or node operations."""

    def __init__(self, identity, variant):
        field, replacement, self.expected_error = INCOMPATIBILITIES[variant]
        self.field = field
        self.identity = identity.model_copy(update={field: replacement})
        self.commands = []
        self.reply = None
        self.ready = Queue(maxsize=1)
        self.buffer = b""
        self.closed = False

    def write(self, wire):
        command = v2.Command.model_validate_json(wire)
        self.commands.append(command.model_dump())
        if self.closed or command.name != "hello":
            raise OSError("The compatibility fixture only supports an initial hello")
        self.reply = v2.Reply(
            command_id=command.command_id,
            command_seq=command.command_seq,
            device_id=self.identity.device_id,
            boot_id=self.identity.boot_id,
            uptime_us=0,
            ok=True,
            result=self.identity.model_dump(),
            error=None,
        )
        self.ready.put_nowait(v2.encode(self.reply))
        return len(wire)

    def read(self, maximum):
        if self.closed:
            return b""
        if not self.buffer:
            try:
                self.buffer = self.ready.get(timeout=0.05)
            except Empty:
                return b""
        chunk, self.buffer = self.buffer[:maximum], self.buffer[maximum:]
        return chunk

    def close(self):
        self.closed = True
