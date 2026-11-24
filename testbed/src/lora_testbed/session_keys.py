"""Safe provisioning facts and persistence boundaries; private wire arguments stay local."""

import json
import re

from . import run_protocol_v2

ERROR_CODES = frozenset(
    """
INVALID_ARGUMENT UNSUPPORTED_VERSION UNSUPPORTED_COMMAND MISSING_CAPABILITY BUSY
NOT_OWNER STALE_BOOT COMMAND_CONFLICT COMMAND_EXPIRED INVALID_STATE UNKNOWN_RUN
CONFIG_MISMATCH KEY_NOT_READY SESSION_MISMATCH RESOURCE_LIMIT ALLOCATION_FAILED
ARTIFACT_NOT_FOUND OFFSET_MISMATCH CHECKSUM_MISMATCH TIMEOUT IO_ERROR RADIO_ERROR
AUDIO_ERROR CLOCK_INVALID INTERNAL_ERROR
""".split()
)
SECRET_FIELDS = frozenset(
    {"tx_key_hex", "rx_key_hex", "source_keys_hex", "session_keys", "private_keys"}
)


def setup_facts(command, role, key_set_id):
    """Build an allowlist directly; never dump the private command into a recorder."""
    return {
        "kind": "session.setup",
        "command_id": command.command_id,
        "command_seq": command.command_seq,
        "client_id": command.client_id,
        "target_boot_id": command.target_boot_id,
        "run_id": command.run_id,
        "session_id": command.args["session_id"],
        "source_role": role,
        "peer_device_id": command.args["peer_device_id"],
        "peer_boot_id": command.args["peer_boot_id"],
        "security": "aes128_gcm",
        "key_set_id": key_set_id,
        "keys_provided": True,
        "key_material_included": False,
        "replayable_command": False,
    }


def setup_reply(command, reply, role, key_set_id):
    code = reply.error.code if reply.error and reply.error.code in ERROR_CODES else "INTERNAL_ERROR"
    result = None
    if reply.ok:
        try:
            result = run_protocol_v2.SessionOpened.model_validate(reply.result).model_dump()
            if result["session_id"] != command.args["session_id"]:
                raise ValueError("Session mismatch")
        except ValueError:
            raise ValueError("Invalid protected session setup reply") from None
    return {
        "kind": "session.setup.result",
        "command_id": command.command_id,
        "command_seq": command.command_seq,
        "device_id": reply.device_id,
        "boot_id": reply.boot_id,
        "uptime_us": reply.uptime_us,
        "source_role": role,
        "run_id": command.run_id,
        "key_set_id": key_set_id,
        "ok": reply.ok,
        "result": result,
        "error": None
        if reply.ok
        else {"code": code, "message": "Protected session setup rejected"},
        "key_material_included": False,
    }


def require_public_metadata(value, _depth=0):
    """Reject secret-bearing metadata before serialization, callbacks or persistence."""
    if _depth > 32:
        raise ValueError("Metadata nesting exceeds the public record limit")
    if isinstance(value, dict):
        for key, child in value.items():
            if key in SECRET_FIELDS and child is not None:
                raise ValueError("Secret-bearing metadata cannot be recorded")
            require_public_metadata(child, _depth + 1)
    elif isinstance(value, (list, tuple)):
        for child in value:
            require_public_metadata(child, _depth + 1)
    elif isinstance(value, str):
        # Fence raw or repeatedly JSON-encoded commands without rejecting field-name prose.
        if value.lstrip().startswith(("{", "[", '"')):
            for line in value.splitlines():
                try:
                    nested = json.loads(line)
                except (ValueError, TypeError):
                    if any(
                        re.search(r'"' + key + r'"\s*:\s*(?!null\b)', line) for key in SECRET_FIELDS
                    ):
                        raise ValueError(
                            "Secret-bearing serialized metadata cannot be recorded"
                        ) from None
                    continue
                if nested != value:
                    require_public_metadata(nested, _depth + 1)
    elif isinstance(value, (bytes, bytearray)):
        raise ValueError("Binary buffers are not public metadata")


class EphemeralKeySet:
    """One RAM-only independent source pair. Safe facts have no key-derived values."""

    def __init__(self):
        import secrets
        from uuid import uuid4

        self._keys = {}
        self._closed = False
        self.key_set_id = None
        try:
            self.key_set_id = str(uuid4())
            self._keys["A"] = bytearray(secrets.token_bytes(16))
            if len(self._keys["A"]) != 16:
                raise ValueError()
            for _ in range(8):
                candidate = bytearray(secrets.token_bytes(16))
                if len(candidate) == 16 and candidate != self._keys["A"]:
                    self._keys["B"] = candidate
                    break
                for index in range(len(candidate)):
                    candidate[index] = 0
            else:
                raise ValueError()
        except Exception:
            self.close()
            raise ValueError("Failed to generate fresh ephemeral source keys") from None

    def __repr__(self):
        return f"EphemeralKeySet(key_set_id={self.key_set_id!r}, retired={self._closed})"

    def arguments(self, role, session_id, peer_device_id, peer_boot_id):
        if self._closed:
            raise ValueError("Ephemeral source keys have been retired")
        if role not in ("A", "B"):
            raise ValueError("Source role must be A or B")
        other = "B" if role == "A" else "A"
        return {
            "session_id": session_id,
            "peer_device_id": peer_device_id,
            "peer_boot_id": peer_boot_id,
            "security": "aes128_gcm",
            "tx_key_hex": self._keys[role].hex(),
            "rx_key_hex": self._keys[other].hex(),
        }

    def close(self):
        for key in self._keys.values():
            for index in range(len(key)):
                key[index] = 0
        self._keys.clear()
        self._closed = True
