"""Finite physical audio jobs shared by HTTP, CLI and dashboard."""

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from . import __version__, audio_contract_v2
from .artifact_contract_v2 import Manifest
from .audio import inspect_pcm, pcm_wav
from .storage import utc_now

OPERATION_WAIT_SECONDS = 35


class NodeAudio:
    def __init__(self, store, nodes, artifacts):
        self.store, self.nodes, self.artifacts = store, nodes, artifacts
        self.record = self.task = None
        self.shutting_down = False
        self.stop_lock = asyncio.Lock()
        self.directory = store.root / "node_audio"
        self.directory.mkdir(exist_ok=True)

    @property
    def busy(self):
        return self.record is not None

    def snapshot(self):
        return {
            "active_id": self.record["id"] if self.record else None,
            "operations": self.store.audio_operations(),
        }

    def save(self, record):
        record["updated_at"] = utc_now()
        self.store.save_audio(record)

    def wire(self, record, value):
        data = (
            json.dumps({"recorded_at": utc_now(), **value}, separators=(",", ":")) + "\n"
        ).encode()
        if record["wire_bytes"] + len(data) > 1048576:
            raise ValueError("Audio evidence exceeds 1 MiB limit")
        with (self.directory / f"{record['id']}.ndjson").open("ab") as output:
            output.write(data)
        record["wire_bytes"] += len(data)

    def observe(self, role, event):
        r = self.record
        if (
            r
            and r["role"] == role
            and event.get("name") == "operation.result"
            and event.get("boot_id") == r["identity"]["boot_id"]
        ):
            try:
                self.wire(r, {"direction": "node_event", "record": event})
            except (ValueError, OSError) as exc:
                r["evidence_error"] = str(exc)

    async def start(self, role, action, artifact_id=None, sample_count=24000):
        if self.busy:
            raise RuntimeError("Another audio operation owns the bench")
        if action not in ("capture", "play", "retrieve"):
            raise ValueError("Unknown audio action")
        command = f"audio.{action}"
        if action == "capture":
            args = audio_contract_v2.Capture(
                artifact_id=str(uuid4()), sample_count=sample_count
            ).model_dump()
        else:
            args = audio_contract_v2.Play(artifact_id=artifact_id).model_dump()
        node, _ = await self.artifacts.preflight(
            role, ["artifact.list", "artifact.get", "artifact.delete"]
        )
        if node.wire_profile != "node_control":
            raise ValueError("Matching main-node control firmware is required")
        if action != "retrieve":
            audio_contract_v2.require_capability(
                node.identity.capabilities, node.health.capability_availability, command
            )
        manifest = None
        if action != "capture":
            files = (await node.request("artifact.list"))["artifacts"]
            manifest = next((m for m in files if m["artifact_id"] == artifact_id), None)
            if (
                manifest is None
                or manifest["state"] != "committed"
                or manifest["format"] != "pcm_s16le_8000_mono"
                or manifest["in_use"]
            ):
                raise ValueError("Choose an unused committed PCM file")
            sample_count = manifest["sample_count"]
        record = {
            "id": str(uuid4()),
            "role": role,
            "action": action,
            "artifact_id": args["artifact_id"],
            "sample_count": sample_count,
            "status": "running",
            "stage": "starting",
            "created_at": utc_now(),
            "finished_at": None,
            "identity": node.identity.model_dump(),
            "audio_schema_sha256": audio_contract_v2.schema_digest(),
            "host_version": __version__,
            "host_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "configuration": node.health.capability_availability.resource_limits.get("audio_io"),
            "operation_id": None,
            "node_result": None,
            "transfer_id": None,
            "clip": None,
            "error": None,
            "cleanup": None,
            "wire_bytes": 0,
            "evidence_error": None,
            "listening": {"heard": "not_checked", "notes": "", "recorded_at": None},
            "hardware_qualified": False,
        }
        self.record = record
        self.save(record)
        self.task = asyncio.create_task(self.run(node, record, args, manifest))
        return record.copy()

    def same_boot(self, node, record):
        if (
            not node.connected
            or node.identity is None
            or node.identity.boot_id != record["identity"]["boot_id"]
        ):
            raise ValueError("Node disconnected or boot changed; no automatic audio resume")

    async def command(self, node, record, name, args=None):
        self.same_boot(node, record)
        return await node.request(name, args, on_record=lambda value: self.wire(record, value))

    async def wait_result(self, node, record):
        async with asyncio.timeout(OPERATION_WAIT_SECONDS):
            while True:
                self.same_boot(node, record)
                if record["evidence_error"]:
                    raise ValueError(record["evidence_error"])
                event = next(
                    (
                        r
                        for r in node.operation_results
                        if r["operation_id"] == record["operation_id"]
                    ),
                    None,
                )
                if event:
                    return event
                await asyncio.sleep(0.02)

    async def retrieve(self, node, record, manifest):
        record["stage"] = "retrieving"
        self.save(record)
        transfer = await self.artifacts.start_download(record["role"], record["artifact_id"])
        record["transfer_id"] = transfer["id"]
        self.save(record)
        while self.artifacts.busy:
            self.same_boot(node, record)
            await asyncio.sleep(0.02)
        transfer = self.artifacts.get(transfer["id"])
        if transfer["status"] != "completed":
            raise ValueError(f"PCM retrieval failed: {transfer['error']}")
        actual = Manifest.model_validate(transfer["manifest"]).model_dump()
        if actual != Manifest.model_validate(manifest).model_dump():
            raise ValueError("Retrieved PCM manifest differs from the completed capture/source")
        if (
            actual["format"] != "pcm_s16le_8000_mono"
            or actual["sample_count"] != record["sample_count"]
        ):
            raise ValueError("Retrieved PCM format/count is inconsistent")
        pcm = self.artifacts.content(transfer["id"]).read_bytes()
        record["clip"] = inspect_pcm(pcm, record["sample_count"])
        content = pcm_wav(pcm, record["sample_count"])
        (self.directory / f"{record['id']}.wav").write_bytes(content)
        record["wav_sha256"] = hashlib.sha256(content).hexdigest()

    async def cleanup(self, node, record):
        notes = []
        if record["transfer_id"] and self.artifacts.busy:
            await self.artifacts.cancel(record["transfer_id"])
        try:
            self.same_boot(node, record)
            status = await self.command(node, record, "status.get")
            if status["operation_id"]:
                await self.command(
                    node, record, "operation.stop", {"operation_id": status["operation_id"]}
                )
                notes.append("node operation stopped")
            if record["action"] == "capture":
                files = (await self.command(node, record, "artifact.list"))["artifacts"]
                if any(m["artifact_id"] == record["artifact_id"] for m in files):
                    await self.command(
                        node, record, "artifact.delete", {"artifact_id": record["artifact_id"]}
                    )
                notes.append("partial/new capture removed")
            record["cleanup"] = "; ".join(notes) or "no active node operation"
        except (ValueError, TimeoutError, OSError) as exc:
            record["cleanup"] = f"unconfirmed: {exc}; disconnecting ownership"
            await node.close()

    async def run(self, node, record, args, manifest):
        try:
            async with asyncio.timeout(220):
                if record["action"] != "retrieve":
                    record["stage"] = "capturing" if record["action"] == "capture" else "playing"
                    accepted = await self.command(node, record, f"audio.{record['action']}", args)
                    record["operation_id"] = accepted["operation_id"]
                    self.save(record)
                    terminal = await self.wait_result(node, record)
                    record["node_result"] = terminal
                    if terminal["status"] != "completed":
                        raise ValueError(
                            f"Node audio {terminal['status']}: {terminal.get('error')}"
                        )
                    result = terminal["result"]
                    if (
                        result.get("kind") != f"audio.{record['action']}"
                        or result.get("artifact_id") != record["artifact_id"]
                        or result.get("samples_requested") != record["sample_count"]
                        or result.get("samples_completed") != record["sample_count"]
                        or result.get("dma_completed") is not True
                        or result.get("underflows") != 0
                        or result.get("overflows", 0) != 0
                    ):
                        raise ValueError("Node audio completion/count/DMA evidence is inconsistent")
                    if record["action"] == "capture":
                        manifest = Manifest.model_validate(result["artifact"]).model_dump()
                        if (
                            manifest["artifact_id"] != record["artifact_id"]
                            or manifest["state"] != "committed"
                        ):
                            raise ValueError("Capture did not publish its requested committed file")
                if record["action"] in ("capture", "retrieve"):
                    await self.retrieve(node, record, manifest)
                if record["evidence_error"]:
                    raise ValueError(record["evidence_error"])
                record.update(
                    status="completed", stage="verified" if record["clip"] else "driver_completed"
                )
        except asyncio.CancelledError:
            record.update(
                status="interrupted" if self.shutting_down else "cancelled",
                error="Host stopped audio",
            )
        except Exception as exc:
            record.update(
                status="failed" if node.connected else "interrupted",
                error=str(exc) or type(exc).__name__,
            )
        finally:
            if record["status"] != "completed":
                (self.directory / f"{record['id']}.wav").unlink(missing_ok=True)
                record["clip"] = None
                try:
                    await asyncio.wait_for(self.cleanup(node, record), 15)
                except (Exception, asyncio.CancelledError) as exc:
                    record["cleanup"] = f"unconfirmed cleanup: {exc}"
                    await node.close()
            evidence = self.directory / f"{record['id']}.ndjson"
            if evidence.exists():
                record["evidence_sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
            record["finished_at"] = utc_now()
            self.save(record)
            self.record = self.task = None

    def get(self, identifier):
        value = self.store.audio_operation(identifier)
        if value is None:
            raise ValueError("Unknown audio operation")
        return value

    def wav(self, identifier):
        record = self.get(identifier)
        if record["status"] != "completed" or record["clip"] is None:
            raise ValueError("Audio has not passed PCM verification")
        pcm = self.artifacts.content(record["transfer_id"]).read_bytes()
        data = pcm_wav(pcm, record["sample_count"])
        path = self.directory / f"{record['id']}.wav"
        if (
            not path.exists()
            or path.read_bytes() != data
            or hashlib.sha256(data).hexdigest() != record["wav_sha256"]
        ):
            raise ValueError("Stored WAV failed integrity verification")
        return data

    def listening(self, identifier, heard, notes):
        record = self.get(identifier)
        if record["status"] == "running":
            raise RuntimeError("Record listening after the operation finishes")
        record["listening"] = {"heard": heard, "notes": notes, "recorded_at": utc_now()}
        self.save(record)
        return record

    async def stop(self, identifier):
        async with self.stop_lock:
            record = self.get(identifier)
            if self.record and self.record["id"] == identifier and self.task:
                task = self.task
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    record.update(
                        status="interrupted" if self.shutting_down else "cancelled",
                        error="Host stopped before audio start",
                        finished_at=utc_now(),
                    )
                    self.save(record)
                    self.record = self.task = None
            return self.get(identifier)

    async def close(self):
        self.shutting_down = True
        if self.record:
            await self.stop(self.record["id"])
