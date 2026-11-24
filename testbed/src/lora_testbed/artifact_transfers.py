"""Bounded file workflows over the existing owned physical node sessions."""

import asyncio
import base64
import hashlib
import json
import zlib
from pathlib import Path
from uuid import uuid4

from . import __version__
from . import artifact_contract_v2 as contract
from .adapters import require_artifact_compatible
from .session_keys import require_public_metadata
from .storage import utc_now

MAX_REQUESTS = 4096
MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
TRANSFER_TIMEOUT = 180


def decode_upload(text: str) -> bytes:
    try:
        data = base64.b64decode(text, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("File must use standard Base64") from exc
    if not 1 <= len(data) <= contract.MAX_ARTIFACT_BYTES or base64.b64encode(data).decode() != text:
        raise ValueError("Use canonical Base64 for a file of 1–131072 bytes")
    return data


class ArtifactTransfers:
    def __init__(self, store, nodes):
        self.store, self.nodes = store, nodes
        self.active = None
        self.task = None
        self.shutting_down = False
        self.cancel_lock = asyncio.Lock()
        self.directory = store.root / "node_artifacts"
        self.directory.mkdir(exist_ok=True)

    @property
    def busy(self):
        return self.active is not None

    def snapshot(self):
        return {"active_id": self.active, "transfers": self.store.transfers()}

    async def preflight(self, role, commands):
        if role not in self.nodes:
            raise ValueError("Node role must be A or B")
        node = self.nodes[role]
        if not node.connected or node.identity is None:
            raise ValueError("Connect the physical node first")
        limits = None
        for name in commands:
            limits = require_artifact_compatible(
                node.identity.model_dump(),
                name,
                node.health.capability_availability.model_dump() if node.health else None,
            )
        health = await node.request("status.get")
        if health["state"] != "idle" or health["node_role"] != role:
            raise RuntimeError("Node must be owned and idle")
        for name in commands:
            limits = require_artifact_compatible(
                node.identity.model_dump(), name, node.health.capability_availability.model_dump()
            )
        return node, limits

    async def list(self, role):
        node, _ = await self.preflight(role, ["artifact.list"])
        return await node.request("artifact.list")

    async def delete(self, role, artifact_id):
        contract.ArtifactReference(artifact_id=artifact_id)
        node, _ = await self.preflight(role, ["artifact.delete"])
        return await node.request("artifact.delete", {"artifact_id": artifact_id})

    async def start_upload(self, role, data, format="known_data", kind="source", name="source.bin"):
        if format == "pcm_s16le_8000_mono" and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
            raise ValueError("Upload raw PCM; WAV containers must be imported as samples first")
        node, limits = await self.preflight(role, list(contract.ARGUMENTS))
        args = contract.Begin(
            artifact_id=str(uuid4()),
            kind=kind,
            format=format,
            length_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        ).model_dump()
        contract.validate_arguments("artifact.begin", args, limits)
        self.check_budget(len(data), limits.artifact_chunk_bytes, upload=True)
        return self.launch(node, role, "upload", args["artifact_id"], name, args, data)

    async def start_download(self, role, artifact_id):
        contract.ArtifactReference(artifact_id=artifact_id)
        node, _ = await self.preflight(role, ["artifact.list", "artifact.get"])
        return self.launch(node, role, "download", artifact_id, "node-file.bin", None, None)

    @staticmethod
    def check_budget(length, chunk, upload=False):
        count = (length + chunk - 1) // chunk
        if count * (2 if upload else 1) + 4 > MAX_REQUESTS:
            raise ValueError("Transfer exceeds the host's bounded request budget")

    def launch(self, node, role, direction, artifact_id, name, args, data):
        if self.busy:
            raise RuntimeError("Another file transfer owns the bench")
        transfer_id = str(uuid4())
        record = {
            "id": transfer_id,
            "role": role,
            "direction": direction,
            "artifact_id": artifact_id,
            "name": name,
            "status": "running",
            "stage": "starting",
            "created_at": utc_now(),
            "finished_at": None,
            "bytes_total": len(data) if data is not None else 0,
            "bytes_transferred": 0,
            "verification_bytes": 0,
            "wire_bytes": 0,
            "wire_records": 0,
            "expected_sha256": args["sha256"] if args else None,
            "actual_sha256": None,
            "manifest": None,
            "error": None,
            "cleanup": None,
            "identity": node.identity.model_dump(),
            "host_version": __version__,
            "artifact_schema_sha256": contract.schema_digest(),
            "host_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        self.store.save_transfer(record)
        self.active = transfer_id
        self.task = asyncio.create_task(self.run(node, record, args, data))
        return record.copy()

    def save(self, record):
        record["updated_at"] = utc_now()
        self.store.save_transfer(record)

    def wire(self, record, value):
        require_public_metadata(value)
        encoded = (
            json.dumps({"recorded_at": utc_now(), **value}, separators=(",", ":")) + "\n"
        ).encode()
        if (
            record["wire_records"] >= MAX_REQUESTS * 2
            or record["wire_bytes"] + len(encoded) > MAX_EVIDENCE_BYTES
        ):
            raise ValueError("Transfer evidence limit reached")
        with (self.directory / f"{record['id']}.ndjson").open("ab") as output:
            output.write(encoded)
        record["wire_bytes"] += len(encoded)
        record["wire_records"] += 1

    def cleanup_wire(self, record, value):
        try:
            self.wire(record, value)
        except (ValueError, OSError) as exc:
            record["cleanup_evidence_error"] = str(exc)

    async def command(self, node, record, name, args=None):
        if node.identity is None or node.identity.boot_id != record["identity"]["boot_id"]:
            raise ValueError("Node boot changed during file transfer")
        return await node.request(name, args, on_record=lambda value: self.wire(record, value))

    async def read(self, node, record, manifest, chunk):
        self.check_budget(manifest["length_bytes"], chunk)
        data = bytearray()
        record["stage"] = "verifying" if record["direction"] == "upload" else "downloading"
        while len(data) < manifest["length_bytes"]:
            result = await self.command(
                node,
                record,
                "artifact.get",
                {
                    "artifact_id": manifest["artifact_id"],
                    "offset": len(data),
                    "length_bytes": chunk,
                },
            )
            raw = contract.decoded_chunk(result["data_b64"], result["crc32"])
            end = len(data) + len(raw)
            if (
                not raw
                or end > manifest["length_bytes"]
                or result["eof"] != (end == manifest["length_bytes"])
            ):
                raise ValueError("Read does not match the committed file length/EOF")
            data.extend(raw)
            record["verification_bytes"] = len(data)
            if record["direction"] == "download":
                record["bytes_transferred"] = len(data)
            self.save(record)
        digest = hashlib.sha256(data).hexdigest()
        if digest != manifest["sha256"]:
            raise ValueError("Downloaded file SHA-256 does not match its committed manifest")
        record["actual_sha256"] = digest
        return bytes(data)

    async def run(self, node, record, args, source):
        path = self.directory / f"{record['id']}.bin"
        try:
            async with asyncio.timeout(TRANSFER_TIMEOUT):
                limits = require_artifact_compatible(
                    node.identity.model_dump(),
                    "artifact.get",
                    node.health.capability_availability.model_dump() if node.health else None,
                )
                if source is not None:
                    record["stage"] = "uploading"
                    await self.command(node, record, "artifact.begin", args)
                    for offset in range(0, len(source), limits.artifact_chunk_bytes):
                        data = source[offset : offset + limits.artifact_chunk_bytes]
                        await self.command(
                            node,
                            record,
                            "artifact.put",
                            {
                                "artifact_id": record["artifact_id"],
                                "offset": offset,
                                "data_b64": base64.b64encode(data).decode(),
                                "crc32": f"{zlib.crc32(data):08x}",
                            },
                        )
                        record["bytes_transferred"] = offset + len(data)
                        self.save(record)
                    record["stage"] = "committing"
                    manifest = await self.command(
                        node, record, "artifact.commit", {"artifact_id": record["artifact_id"]}
                    )
                    if any(manifest[key] != args[key] for key in args):
                        raise ValueError("Committed manifest differs from the uploaded source")
                else:
                    listing = await self.command(node, record, "artifact.list")
                    manifest = next(
                        (
                            v
                            for v in listing["artifacts"]
                            if v["artifact_id"] == record["artifact_id"]
                        ),
                        None,
                    )
                    if manifest is None or manifest["state"] != "committed":
                        raise ValueError("Choose an existing committed file")
                record["manifest"] = manifest
                record["bytes_total"] = manifest["length_bytes"]
                record["expected_sha256"] = manifest["sha256"]
                data = await self.read(node, record, manifest, limits.artifact_chunk_bytes)
                if source is not None and data != source:
                    raise ValueError("Readback bytes differ from the uploaded source")
                path.write_bytes(data)  # Only fully committed and independently verified bytes.
                record.update(status="completed", stage="verified")
        except asyncio.CancelledError:
            record.update(
                status="interrupted" if self.shutting_down else "cancelled",
                error="Host stopped the transfer",
            )
        except Exception as exc:
            record.update(
                status="failed" if node.connected else "interrupted",
                error=str(exc) or type(exc).__name__,
            )
        finally:
            if record["status"] != "completed":
                path.unlink(missing_ok=True)
                if source is not None:
                    try:
                        await asyncio.wait_for(
                            node.request(
                                "artifact.delete",
                                {"artifact_id": record["artifact_id"]},
                                on_record=lambda value: self.cleanup_wire(record, value),
                            ),
                            3,
                        )
                        record["cleanup"] = "node reservation deleted"
                    except (ValueError, TimeoutError, OSError) as exc:
                        record["cleanup"] = f"unconfirmed: {exc}; disconnected to release ownership"
                        await node.close()
            evidence = self.directory / f"{record['id']}.ndjson"
            if evidence.exists():
                record["evidence_sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
            record["finished_at"] = utc_now()
            try:
                self.save(record)
            finally:
                self.active = self.task = None

    def get(self, transfer_id):
        record = self.store.transfer(transfer_id)
        if record is None:
            raise ValueError("Unknown file transfer")
        return record

    def content(self, transfer_id):
        record = self.get(transfer_id)
        if record["status"] != "completed":
            raise ValueError("File transfer has not passed verification")
        path = self.directory / f"{record['id']}.bin"
        if not path.exists():
            raise ValueError("Verified host file is missing")
        data = path.read_bytes()
        if (
            len(data) != record["bytes_total"]
            or hashlib.sha256(data).hexdigest() != record["actual_sha256"]
        ):
            raise ValueError("Stored file failed its length/hash check")
        return path

    async def cancel(self, transfer_id):
        async with self.cancel_lock:
            record = self.get(transfer_id)
            if self.active == transfer_id and self.task:
                task = self.task
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    # A task cancelled before its first instruction has no finally block.
                    record.update(
                        status="interrupted" if self.shutting_down else "cancelled",
                        error="Host stopped before transfer start",
                        finished_at=utc_now(),
                    )
                    self.save(record)
                    self.active = self.task = None
            return self.get(transfer_id)

    async def close(self):
        self.shutting_down = True
        if self.active:
            await self.cancel(self.active)
