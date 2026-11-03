"""Unprotected DATA framing checked by cross-language conformance fixtures."""

import struct

HEADER = struct.Struct(">2sBBBBBBQIIHHIHIH")
ROLES = {"A": 1, "B": 2}


def data_frame(session, sequence, message, index, count, total, source, destination, body):
    if source not in ROLES or destination not in ROLES or source == destination:
        raise ValueError("Invalid DATA direction")
    if not 1 <= int(session, 16) <= 2**64 - 1 or not 1 <= sequence <= 2**32 - 1:
        raise ValueError("Invalid DATA session or sequence")
    if not 1 <= message <= 2**32 - 1 or not 0 <= index < count <= 4096:
        raise ValueError("Invalid DATA message or fragment")
    if not 1 <= total <= 65536 or not 1 <= len(body) <= 215:
        raise ValueError("Invalid DATA length")
    return (
        HEADER.pack(
            b"LT",
            2,
            1,
            0,
            ROLES[source],
            ROLES[destination],
            0,
            int(session, 16),
            sequence,
            message,
            index,
            count,
            total,
            len(body),
            0,
            0,
        )
        + body
    )


def parse_data(wire: bytes, fragment_bytes: int) -> dict:
    if not HEADER.size < len(wire) <= 255:
        raise ValueError("Invalid DATA frame length")
    (
        magic,
        version,
        kind,
        flags,
        source,
        destination,
        content,
        session,
        sequence,
        message,
        index,
        count,
        total,
        body_length,
        reference,
        reserved,
    ) = HEADER.unpack(wire[:40])
    if (magic, version, kind, flags, content, reference, reserved) != (b"LT", 2, 1, 0, 0, 0, 0):
        raise ValueError("Invalid unprotected DATA header")
    if source not in (1, 2) or destination not in (1, 2) or source == destination:
        raise ValueError("Invalid DATA roles")
    if not session or not sequence or not message or not 0 <= index < count <= 4096:
        raise ValueError("Invalid DATA identity")
    if not 1 <= total <= 65536 or count != (total + fragment_bytes - 1) // fragment_bytes:
        raise ValueError("Inconsistent DATA fragment count")
    expected = fragment_bytes if index < count - 1 else total - fragment_bytes * (count - 1)
    if body_length != expected or len(wire) != 40 + body_length:
        raise ValueError("Inconsistent DATA body length")
    return {
        "session_id": f"{session:016x}",
        "frame_seq": sequence,
        "message_id": message,
        "fragment_index": index,
        "fragment_count": count,
        "message_bytes": total,
        "source_role": "A" if source == 1 else "B",
        "destination_role": "A" if destination == 1 else "B",
        "body": wire[40:],
    }
