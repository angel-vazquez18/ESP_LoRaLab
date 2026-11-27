"""Finite secure clips composed from the shared audio, artifact and radio owners."""

import asyncio
import hashlib
import io
import json
import wave
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from . import __version__, audio_contract_v2, codec_contract_v2
from .artifact_contract_v2 import ArtifactID
from .audio import inspect_pcm
from .experiments_v2 import Link, Radio
from .models import StrictModel
from .radio_runs import EncodedRadioRunRequest, FixedRateRadioRunRequest, RadioRunRequest
from .session_keys import require_public_metadata
from .storage import utc_now


class VoiceRunRequest(StrictModel):
    source: Literal["reference", "microphone"]
    reference_id: ArtifactID | None = None
    sample_count: int = Field(default=24000, ge=1, le=24000)
    direction: Literal["A_TO_B", "B_TO_A"] = "A_TO_B"
    security: Literal["aes128_gcm"] = "aes128_gcm"
    timeout_ms: int = Field(default=30000, ge=1000, le=3600000)
    radio: Radio = Field(default_factory=lambda: Radio(tx_power_dbm=2))
    link: Link = Field(default_factory=Link)
    include_comparisons: bool = True

    @model_validator(mode="after")
    def reference_selection(self):
        if (self.source == "reference") != (self.reference_id is not None):
            raise ValueError("Reference sources require a reference ID; microphones do not")
        return self


class VoiceReassemblyRequest(VoiceRunRequest):
    """Internal encoded-transfer workload which ends at verified reassembly."""

    include_comparisons: Literal[False] = False


class SustainedVoiceRequest(VoiceReassemblyRequest):
    source: Literal["reference"] = "reference"
    sample_count: Literal[24000] = 24000
    timeout_ms: Literal[90000] = 90000


class VoiceRuns:
    def __init__(self, store, nodes, artifacts, audio, radio):
        self.store, self.nodes = store, nodes
        self.artifacts, self.audio, self.radio = artifacts, audio, radio
        self.current = self.task = None
        self.cleaning_up = self.shutting_down = False
        self.stop_lock = asyncio.Lock()
        self.directory = store.root / "voice_runs"
        self.directory.mkdir(exist_ok=True)
        store.db.execute(
            "CREATE TABLE IF NOT EXISTS voice_runs_v1 "
            "(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL)"
        )
        store.db.commit()
        for row in store.db.execute("SELECT document FROM voice_runs_v1").fetchall():
            record = json.loads(row[0])
            if record["status"] == "running":
                record.update(
                    status="interrupted",
                    finished_at=utc_now(),
                    error="Host restarted; voice work is not resumed",
                    cleanup={
                        "confirmed": False,
                        "reason": "Previous ownership/resources unconfirmed",
                    },
                )
                self.save(record)

    @property
    def busy(self):
        return self.current is not None

    def save(self, record):
        require_public_metadata(record)
        record["updated_at"] = utc_now()
        self.store.db.execute(
            "INSERT INTO voice_runs_v1 VALUES (?,?,?) ON CONFLICT(id) "
            "DO UPDATE SET document=excluded.document",
            (record["id"], record["created_at"], json.dumps(record)),
        )
        self.store.db.commit()

    def get(self, identifier):
        row = self.store.db.execute(
            "SELECT document FROM voice_runs_v1 WHERE id=?", (identifier,)
        ).fetchone()
        if not row:
            raise ValueError("Unknown voice run")
        return json.loads(row[0])

    def snapshot(self):
        fields = (
            "id",
            "created_at",
            "finished_at",
            "status",
            "stage",
            "sender",
            "receiver",
            "request",
            "sample_count",
            "radio_run_id",
            "jobs",
            "comparisons",
            "delivery_verified",
            "source_observation",
            "playback_completed",
            "listening",
            "hardware_qualified",
            "cleanup",
            "error",
        )
        rows = self.store.db.execute(
            "SELECT document FROM voice_runs_v1 ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        return {
            "active_id": self.current["id"] if self.current else None,
            "runs": [
                {key: record.get(key) for key in fields}
                for row in rows
                for record in [json.loads(row[0])]
            ],
        }

    def reference(self, request):
        if request.source != "reference":
            return None, None
        reference = next(
            (value for value in self.store.references() if value["id"] == request.reference_id),
            None,
        )
        if reference is None:
            raise ValueError("Choose an uploaded reference")
        path = self.store.root / "audio" / f"{reference['id']}.wav"
        try:
            with path.open("rb") as source:
                content = source.read(1048577)
            if len(content) > 1048576 or hashlib.sha256(content).hexdigest() != reference["sha256"]:
                raise ValueError("Saved reference failed integrity verification")
            with wave.open(io.BytesIO(content), "rb") as wav:
                if (
                    wav.getnchannels(),
                    wav.getsampwidth(),
                    wav.getframerate(),
                    wav.getnframes(),
                ) != (1, 2, 8000, reference["sample_count"]):
                    raise ValueError("Reference must retain its 8 kHz mono PCM format/count")
                pcm = wav.readframes(wav.getnframes())
            if len(pcm) != reference["sample_count"] * 2:
                raise ValueError("Reference PCM is truncated")
        except (OSError, wave.Error, EOFError) as exc:
            raise ValueError("Uploaded reference file is unavailable/invalid") from exc
        return reference, pcm

    @staticmethod
    def radio_request(request, artifact_id, samples, expected_sha256):
        selected = (
            FixedRateRadioRunRequest
            if isinstance(request, SustainedVoiceRequest)
            else EncodedRadioRunRequest
        )
        return selected(
            direction=request.direction,
            radio=request.radio,
            link=request.link,
            timeout_ms=request.timeout_ms,
            message_bytes=((samples + 159) // 160) * 8,
            source_artifact_id=artifact_id,
            sample_count=samples,
            expected_sha256=expected_sha256,
        )

    def preflight(self, request):
        blockers = []
        try:
            reference, _ = self.reference(request)
            samples = reference["sample_count"] if reference else request.sample_count
            transport = self.radio_request(
                request, "00000000-0000-0000-0000-000000000000", samples, "0" * 64
            )
            blockers.extend(self.radio.preflight(transport)["blockers"])
        except ValueError as exc:
            blockers.append(str(exc))
            samples = request.sample_count
        sender, receiver = ("A", "B") if request.direction == "A_TO_B" else ("B", "A")
        reassembly_only = isinstance(request, VoiceReassemblyRequest)
        targets = [(sender, ("audio.encode", "audio.decode"))]
        if not reassembly_only:
            targets.append((receiver, ("audio.decode",)))
        for role, commands in targets:
            node = self.nodes[role]
            try:
                for name in commands:
                    codec_contract_v2.require_capability(
                        node.identity.capabilities if node.identity else None,
                        node.health.capability_availability if node.health else None,
                        name,
                    )
                if role == receiver or request.source == "microphone":
                    audio_contract_v2.require_capability(
                        node.identity.capabilities,
                        node.health.capability_availability,
                        "audio.play" if role == receiver else "audio.capture",
                    )
            except (ValueError, AttributeError) as exc:
                purpose = (
                    "receiver decode/playback"
                    if role == receiver
                    else "source codec/capture"
                    if request.source == "microphone"
                    else "source codec"
                )
                blockers.append(f"Node {role} ({purpose}): {exc}")
        return {
            "ready": not blockers,
            "blockers": list(dict.fromkeys(blockers)),
            "sample_count": samples,
            "encoded_bytes": ((samples + 159) // 160) * 8,
            "hardware_qualified": False,
        }

    async def start(self, request):
        if self.busy:
            raise RuntimeError("Another voice job owns the bench")
        for node in self.nodes.values():
            if node.connected:
                await node.request("status.get")
        ready = self.preflight(request)
        if not ready["ready"]:
            raise ValueError("; ".join(ready["blockers"]))
        reference, pcm = self.reference(request)
        before = {
            role: [
                file["artifact_id"] for file in (await node.request("artifact.list"))["artifacts"]
            ]
            for role, node in self.nodes.items()
        }
        sender, receiver = ("A", "B") if request.direction == "A_TO_B" else ("B", "A")
        record = {
            "id": str(uuid4()),
            "created_at": utc_now(),
            "finished_at": None,
            "status": "running",
            "stage": "source",
            "request": request.model_dump(),
            "workload": "fixed_rate_encoded"
            if isinstance(request, SustainedVoiceRequest)
            else "encoded_reassembly"
            if isinstance(request, VoiceReassemblyRequest)
            else "voice_playback",
            "reference": reference,
            "sample_count": ready["sample_count"],
            "sender": sender,
            "receiver": receiver,
            "identities": {role: node.identity.model_dump() for role, node in self.nodes.items()},
            "before_artifacts": before,
            "owned": {role: {} for role in self.nodes},
            "host_version": __version__,
            "host_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "jobs": {},
            "radio_run_id": None,
            "comparisons": {},
            "delivery_verified": False,
            "playback_completed": False,
            "listening": {"heard": "not_checked", "notes": "", "recorded_at": None},
            "hardware_qualified": False,
            "cleanup": None,
            "error": None,
            "failure_stage": None,
            "wire_bytes": 0,
        }
        self.current = record
        self.cleaning_up = False
        self.save(record)
        self.task = asyncio.create_task(self.run(record, request, pcm))
        return record.copy()

    def same_boot(self, record, role):
        node, expected = self.nodes[role], record["identities"][role]
        if (
            not node.connected
            or node.identity is None
            or (node.identity.device_id, node.identity.boot_id)
            != (expected["device_id"], expected["boot_id"])
        ):
            raise ValueError(f"Node {role} disconnected/changed boot; voice work is not resumed")
        return node

    def wire(self, record, role, value):
        require_public_metadata(value)
        content = (
            json.dumps({"recorded_at": utc_now(), "role": role, **value}, separators=(",", ":"))
            + "\n"
        ).encode()
        if record["wire_bytes"] + len(content) > 1048576:
            raise ValueError("Voice control evidence exceeds 1 MiB")
        with (self.directory / f"{record['id']}.ndjson").open("ab") as output:
            output.write(content)
        record["wire_bytes"] += len(content)

    async def command(self, record, role, name, args=None):
        return await self.same_boot(record, role).request(
            name, args, on_record=lambda value: self.wire(record, role, value)
        )

    async def wait(self, record, service, identifier):
        while True:
            for role in self.nodes:
                self.same_boot(record, role)
            child = service.get(identifier)
            if child["status"] != "running" and not service.busy:
                if child["status"] != "completed":
                    raise ValueError(
                        f"Voice stage {record['stage']} {child['status']}: {child.get('error')}"
                    )
                return child
            await asyncio.sleep(0.01)

    def own(self, record, role, identifier, manifest=None):
        if identifier and identifier not in record["before_artifacts"][role]:
            entry = record["owned"][role].setdefault(
                identifier, {"manifest": None, "retired": False}
            )
            if manifest is not None:
                entry["manifest"] = manifest

    def collect(self, record):
        sender = record["sender"]
        for name, identifier in record["jobs"].items():
            if name == "source_upload":
                child = self.artifacts.get(identifier)
                self.own(record, sender, child["artifact_id"], child.get("manifest"))
                continue
            child = self.audio.get(identifier)
            role = child["role"]
            if child["action"] == "capture":
                self.own(
                    record,
                    role,
                    child["artifact_id"],
                    ((child.get("node_result") or {}).get("result") or {}).get("artifact"),
                )
            for entry in child.get("codec_artifacts", {}).values():
                self.own(record, role, entry["manifest"]["artifact_id"], entry["manifest"])
            for output_id in child.get("planned_output_ids", {}).values():
                self.own(record, role, output_id)
        radio_ids = [
            record["radio_run_id"],
            *(value["radio_run_id"] for value in record["comparisons"].values()),
        ]
        for identifier in filter(None, radio_ids):
            child = self.radio.get(identifier)
            for role, prepared in child["prepared"].items():
                self.own(record, role, prepared["artifact_id"])
            for role, manifest in child["readback_manifests"].items():
                self.own(record, role, manifest["artifact_id"], manifest)
        self.save(record)

    async def retire(self, record, role, identifiers=None):
        self.same_boot(record, role)
        files = (await self.command(record, role, "artifact.list"))["artifacts"]
        current = {file["artifact_id"]: file for file in files}
        for identifier, entry in record["owned"][role].items():
            if entry["retired"] or (identifiers is not None and identifier not in identifiers):
                continue
            actual, expected = current.get(identifier), entry["manifest"]
            if actual is not None:
                if actual["in_use"] or (
                    expected
                    and any(
                        actual[key] != expected[key] for key in ("sha256", "length_bytes", "format")
                    )
                ):
                    raise ValueError(
                        "Owned node artifact changed or is still in use; retirement is unconfirmed"
                    )
                await self.command(record, role, "artifact.delete", {"artifact_id": identifier})
            entry["retired"] = True
        self.save(record)

    async def cleanup(self, record):
        notes, confirmed = {}, True
        try:
            if self.radio.busy:
                await self.radio.stop()
            if self.audio.busy:
                await self.audio.stop(self.audio.snapshot()["active_id"])
            if self.artifacts.busy:
                await self.artifacts.cancel(self.artifacts.snapshot()["active_id"])
            self.collect(record)
        except Exception as exc:
            confirmed = False
            notes["children"] = str(exc)
        for role in self.nodes:
            try:
                status = await self.command(record, role, "status.get")
                if status["state"] != "idle" or status["security_ready"]:
                    raise ValueError("Node did not confirm idle with retired session keys")
                await self.retire(record, role)
                notes[role] = "idle; keys retired; job-owned artifacts retired"
            except (ValueError, TimeoutError, OSError) as exc:
                confirmed = False
                notes[role] = f"Unconfirmed: {exc}"
                await self.nodes[role].close(release=False)
        if confirmed:
            for name, identifier in record["jobs"].items():
                if name != "source_upload":
                    child = self.audio.get(identifier)
                    child["node_artifacts_retired"] = True
                    self.audio.save(child)
        return {"confirmed": confirmed, "nodes": notes}

    async def run(self, record, request, pcm):
        sender, receiver = record["sender"], record["receiver"]
        outcome = "failed"
        try:
            async with asyncio.timeout(
                request.timeout_ms / 1000 * (3 if request.include_comparisons else 1) + 300
            ):
                if request.source == "reference":
                    child = await self.artifacts.start_upload(
                        sender, pcm, format="pcm_s16le_8000_mono", name=record["reference"]["name"]
                    )
                    record["jobs"]["source_upload"] = child["id"]
                    self.save(record)
                    child = await self.wait(record, self.artifacts, child["id"])
                    source_id = child["artifact_id"]
                else:
                    child = await self.audio.start(
                        sender, "capture", sample_count=record["sample_count"]
                    )
                    record["jobs"]["source_audio"] = child["id"]
                    self.save(record)
                    child = await self.wait(record, self.audio, child["id"])
                    source_id = child["artifact_id"]
                record["stage"] = "encoding"
                child = await self.audio.start(sender, "codec", artifact_id=source_id)
                record["jobs"]["codec"] = child["id"]
                self.save(record)
                local = await self.wait(record, self.audio, child["id"])
                if not local["verified_roundtrip"]:
                    raise ValueError("Local codec files were not independently verified")
                self.collect(record)
                await self.retire(
                    record, sender, {local["codec_artifacts"]["decoded"]["manifest"]["artifact_id"]}
                )
                encoded = local["codec_artifacts"]["encoded"]["manifest"]
                record["stage"] = "transferring"
                for role in self.nodes:
                    await self.command(record, role, "status.get")
                child = await self.radio.start(
                    self.radio_request(
                        request, encoded["artifact_id"], encoded["sample_count"], encoded["sha256"]
                    )
                )
                record["radio_run_id"] = child["id"]
                self.save(record)
                transported = await self.wait(record, self.radio, child["id"])
                if isinstance(request, SustainedVoiceRequest):
                    record["source_observation"] = transported["source_observation"]
                    record["delivery_verified"] = (
                        record["source_observation"]["delivery"]["assessment"] == "verified"
                    )
                    self.collect(record)
                    outcome = "completed"
                    return
                if (
                    not transported["verification"]["bytes_equal"]
                    or transported["verification"]["sha256"] != encoded["sha256"]
                ):
                    raise ValueError(
                        "Complete encoded byte verification is required before decoding"
                    )
                record["delivery_verified"] = True
                self.collect(record)
                if not isinstance(request, VoiceReassemblyRequest):
                    record["stage"] = "decoding"
                    child = await self.audio.start(
                        receiver,
                        "decode",
                        artifact_id=transported["readback_manifests"][receiver]["artifact_id"],
                    )
                    record["jobs"]["decode"] = child["id"]
                    self.save(record)
                    decoded = await self.wait(record, self.audio, child["id"])
                    if not decoded["verified_codec_stage"]:
                        raise ValueError("Receiver PCM did not pass decode/readback verification")
                    record["stage"] = "playing"
                    child = await self.audio.start(
                        receiver, "play", artifact_id=decoded["artifact_id"]
                    )
                    record["jobs"]["playback"] = child["id"]
                    self.save(record)
                    await self.wait(record, self.audio, child["id"])
                    record["playback_completed"] = True
                    self.audio.link_playback(decoded["id"], child["id"])
                    self.collect(record)
                if request.include_comparisons:
                    record["stage"] = "comparisons"
                    for basis, length in (
                        ("equal_encoded_bytes", encoded["length_bytes"]),
                        ("standard_64_bytes", 64),
                    ):
                        for role in self.nodes:
                            await self.command(record, role, "status.get")
                        child = await self.radio.start(
                            RadioRunRequest(
                                security="aes128_gcm",
                                direction=request.direction,
                                message_bytes=length,
                                timeout_ms=request.timeout_ms,
                                radio=request.radio,
                                link=request.link,
                            )
                        )
                        record["comparisons"][basis] = {
                            "basis": basis,
                            "message_bytes": length,
                            "radio_run_id": child["id"],
                        }
                        self.save(record)
                        compared = await self.wait(record, self.radio, child["id"])
                        self.collect(record)
                        for role, manifest in compared["readback_manifests"].items():
                            await self.retire(record, role, {manifest["artifact_id"]})
                outcome = "completed"
        except asyncio.CancelledError:
            outcome = "interrupted" if self.shutting_down else "cancelled"
            record.update(
                error="Host stopped voice work",
                failure_stage=record["stage"],
            )
        except Exception as exc:
            interrupted = any(
                not node.connected
                or node.identity is None
                or node.identity.boot_id != record["identities"][role]["boot_id"]
                for role, node in self.nodes.items()
            )
            outcome = "interrupted" if interrupted else "failed"
            record.update(
                error=str(exc) or type(exc).__name__,
                failure_stage=record["stage"],
            )
        finally:
            self.cleaning_up = True
            try:
                record["cleanup"] = await asyncio.wait_for(self.cleanup(record), 30)
            except (Exception, asyncio.CancelledError) as exc:
                record["cleanup"] = {"confirmed": False, "reason": str(exc)}
                for node in self.nodes.values():
                    await node.close(release=False)
            record["status"] = outcome
            record["stage"] = "finished"
            if not record["cleanup"]["confirmed"] and record["status"] == "completed":
                record.update(
                    status="failed", error="Voice cleanup did not confirm resource retirement"
                )
            record["finished_at"] = utc_now()
            self.save(record)
            self.current = self.task = None
            self.cleaning_up = False

    def content(self, identifier, kind, as_wav=False):
        record = self.get(identifier)
        if kind in ("source", "encoded"):
            if "codec" not in record["jobs"]:
                raise ValueError("Voice source/encoded files are not verified")
            return self.audio.codec_content(record["jobs"]["codec"], kind, as_wav)
        if kind == "decoded":
            if "decode" not in record["jobs"]:
                raise ValueError("Receiver PCM is not verified")
            return self.audio.codec_content(record["jobs"]["decode"], "decoded", as_wav)
        if kind == "recovered" and not as_wav and record["radio_run_id"]:
            radio = self.radio.get(record["radio_run_id"])
            if not (radio.get("verification") or {}).get("bytes_equal"):
                raise ValueError("Recovered encoded content is not verified")
            data = self.radio.content(radio["id"], "recovered").read_bytes()
            if (
                len(data) != radio["verification"]["length_bytes"]
                or hashlib.sha256(data).hexdigest() != radio["verification"]["sha256"]
            ):
                raise ValueError("Saved recovered voice file failed integrity verification")
            return data
        raise ValueError(
            "Choose a verified source/encoded/recovered/decoded file; WAV requires PCM"
        )

    def inspect(self, identifier):
        record = self.get(identifier)
        files = {}
        for kind in ("source", "encoded", "recovered", "decoded"):
            try:
                content = self.content(identifier, kind)
                if kind == "recovered":
                    manifest = self.radio.get(record["radio_run_id"])["readback_manifests"][
                        record["receiver"]
                    ]
                else:
                    job = record["jobs"]["decode" if kind == "decoded" else "codec"]
                    manifest = self.audio.get(job)["codec_artifacts"][kind]["manifest"]
                files[kind] = {
                    "manifest": manifest,
                    "available": True,
                    "length_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "pcm": inspect_pcm(content, record["sample_count"])
                    if kind in ("source", "decoded")
                    else None,
                }
            except (ValueError, OSError) as exc:
                files[kind] = {"available": False, "error": str(exc)}

        stages = []
        for name, job, transform in (
            ("capture", "source_audio", None),
            ("encode", "codec", "encode"),
            ("sender_decode_check", "codec", "decode"),
            ("receiver_decode", "decode", "decode"),
            ("playback", "playback", None),
        ):
            child_id = record["jobs"].get(job)
            child = self.audio.get(child_id) if child_id else None
            terminal = (
                child.get("codec_operations", {}).get(transform)
                if transform and child
                else child.get("node_result")
                if child
                else None
            ) or {}
            result = terminal.get("result") or {}
            role = (
                child["role"]
                if child
                else (record["receiver"] if job in ("decode", "playback") else record["sender"])
            )
            identity = record["identities"][role]
            timed = "duration_us" in result
            status = (
                terminal.get("status") or child["status"]
                if child and (not transform or terminal)
                else "not_started"
            )
            stages.append(
                {
                    "name": name,
                    "job_id": child_id,
                    "status": status,
                    "error": child.get("error") if child and status != "completed" else None,
                    "result": result or None,
                    "timing": {
                        "basis": "node_monotonic_us" if timed else "unavailable",
                        "role": role,
                        "device_id": identity["device_id"],
                        "boot_id": identity["boot_id"],
                        "started_us": result.get("started_us"),
                        "finished_us": result.get("finished_us"),
                        "duration_us": result.get("duration_us"),
                        "components_us": {
                            key: result[key]
                            for key in ("setup_us", "conversion_us", "codec_us", "finalize_us")
                            if key in result
                        },
                    },
                    "host_created_at": child.get("created_at") if child else None,
                    "host_finished_at": child.get("finished_at") if child else None,
                }
            )

        def radio_view(run_id):
            if not run_id:
                return None
            run = self.radio.get(run_id)
            return {
                key: run.get(key)
                for key in (
                    "id",
                    "session_id",
                    "status",
                    "stage",
                    "plan",
                    "verification",
                    "accounting",
                    "security",
                    "summaries",
                    "signal",
                    "applied_settings",
                    "error",
                    "cleanup",
                    "rf_window_closed_at",
                )
            }

        return {
            "record": record,
            "files": files,
            "stages": stages,
            "radio": radio_view(record["radio_run_id"]),
            "comparisons": {
                basis: {**entry, "run": radio_view(entry["radio_run_id"])}
                for basis, entry in record["comparisons"].items()
            },
            "encoded_integrity": {
                "verified": bool(
                    record["delivery_verified"]
                    and files["encoded"]["available"]
                    and files["recovered"]["available"]
                    and files["encoded"]["sha256"] == files["recovered"]["sha256"]
                    and files["encoded"]["length_bytes"] == files["recovered"]["length_bytes"]
                ),
                "basis": "historical_exact_readback_and_current_saved_file_hashes",
            },
            "one_way_latency": {
                "valid": False,
                "value_us": None,
                "reason": "Valid cross-node clock calibration is not available for this workflow",
            },
        }

    def listening(self, identifier, heard, notes):
        record = self.get(identifier)
        if record["status"] == "running":
            raise RuntimeError("Record listening after voice work finishes")
        if not record["playback_completed"] or "playback" not in record["jobs"]:
            raise ValueError("There is no completed receiver playback to annotate")
        played = self.audio.listening(record["jobs"]["playback"], heard, notes)
        self.audio.link_playback(record["jobs"]["decode"], played["id"])
        record["listening"] = played["listening"]
        self.save(record)
        return record

    async def stop(self, identifier=None):
        async with self.stop_lock:
            if not self.busy:
                return self.get(identifier) if identifier else None
            if identifier is not None and identifier != self.current["id"]:
                raise ValueError("This voice run is not active")
            identifier, task = self.current["id"], self.task
            if not self.cleaning_up:
                task.cancel()
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.cancelled():
                    raise
                record = self.current
                if record:
                    record.update(
                        status="interrupted" if self.shutting_down else "cancelled",
                        error="Host stopped before voice start",
                        finished_at=utc_now(),
                        cleanup={"confirmed": True, "reason": "No child work started"},
                    )
                    self.save(record)
                    self.current = self.task = None
            return self.get(identifier)

    async def close(self):
        self.shutting_down = True
        if self.busy:
            await self.stop()
