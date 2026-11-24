"""Local HTTP interface. Run one worker so one process owns the bench."""

import asyncio
import csv
import io
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import (
    audio_contract_v2,
    control_v2,
    crypto_benchmark_v2,
    memory_observation_v2,
    rf_events_v2,
    run_protocol_v2,
    v2,
)
from .artifact_transfers import decode_upload
from .audio import MAX_UPLOAD_BYTES, inspect_wav, save_wav
from .campaign_plans import CampaignSpec
from .catalog import catalog
from .comparison import campaign_summary, compare
from .experiments_v2 import KnownDataPlan
from .experiments_v2 import preview as preview_known_data
from .host import Host
from .models import StrictModel
from .nodes import discover_ports
from .paths import TESTBED_ROOT
from .radio_runs import RadioRunRequest
from .reports import campaign_csv, evidence_bundle
from .reports_v2 import campaign_summary as v2_campaign_summary
from .reports_v2 import compare_runs, event_rows, evidence_zip, run_csv
from .serial_validation import SerialValidationRequest, serial_plan
from .session_keys import require_public_metadata
from .voice_runs import VoiceRunRequest
from .workload_assessment import AssessmentRequest


class PreflightRequest(StrictModel):
    roles: list[Literal["A", "B"]] | None = Field(default=None, min_length=1, max_length=2)
    workload: Literal["default", "local", "rf"] = "default"


class PhysicalRunRequest(PreflightRequest):
    catalog_id: str = Field(default="IF-02", min_length=1, max_length=32)


class HardwareConnectionRequest(StrictModel):
    port: str | None = None


class MemoryProbeRequest(StrictModel):
    iterations: int = Field(default=10, ge=1, le=10000)
    payload_bytes: int = Field(default=4096, ge=1, le=65536)


class StopOperationRequest(StrictModel):
    operation_id: str = Field(pattern=r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")


class ArtifactUploadRequest(StrictModel):
    data_b64: str = Field(min_length=1, max_length=174764)
    format: Literal["known_data", "pcm_s16le_8000_mono"] = "known_data"
    kind: Literal["source", "recovered"] = "source"
    name: str = Field(
        default="source.bin", min_length=1, max_length=128, pattern=r"^[^\x00-\x1f\x7f]+$"
    )


class CaptureRequest(StrictModel):
    sample_count: int = Field(default=24000, ge=1, le=24000)


class ListeningRequest(StrictModel):
    heard: Literal["not_checked", "heard", "not_heard"] = "not_checked"
    notes: str = Field(default="", max_length=1000)


class CodecPlaybackRequest(StrictModel):
    operation_id: control_v2.UUID
    stage: Literal["source", "decoded"] = "decoded"


class ComparisonRequest(StrictModel):
    run_ids: list[str] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def unique_ids(self):
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("Choose distinct runs")
        return self


def create_app(data_dir: Path | None = None, frontend_dir: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.host = Host(data_dir or Path(os.environ.get("LORA_DATA_DIR", "data")))
        yield
        await app.state.host.close()

    app = FastAPI(title="LoRa Testbed", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    def local_origin(origin: str | None, server_port: int | None) -> bool:
        if origin is None:
            return True  # Non-browser clients such as the CLI.
        try:
            url = urlsplit(origin)
            return (
                url.scheme == "http"
                and url.hostname in ("127.0.0.1", "localhost")
                and (url.port or 80) in (server_port or 80, 5173)
            )
        except ValueError:
            return False

    @app.middleware("http")
    async def check_origin(request: Request, call_next):
        if not local_origin(request.headers.get("origin"), request.url.port):
            return JSONResponse(status_code=403, content={"detail": "Local clients only"})
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def private_input_rejection(request: Request, exc: RequestValidationError):
        try:
            if isinstance(exc.body, (dict, list, str)):
                require_public_metadata(exc.body)
        except ValueError:
            return JSONResponse(
                status_code=422,
                content={"detail": "Session key material is not accepted by this API"},
            )
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(ValueError)
    async def invalid_request(request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(RuntimeError)
    async def conflict(request: Request, exc: RuntimeError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.get("/api/state")
    async def state():
        return app.state.host.snapshot()

    @app.get("/api/protocol/v2")
    async def protocol_v2():
        return {
            "version": 2,
            "contract_version": v2.CONTRACT_VERSION,
            "scope": "diagnostic identity/health; RF/audio commands unavailable",
            "schema_sha256": v2.schema_digest(),
            "schema": v2.schema(),
        }

    @app.get("/api/protocol/v2/control")
    async def control_protocol():
        return {
            "schema": control_v2.schema(),
            "schema_sha256": control_v2.schema_digest(),
            "hardware_validated": False,
        }

    @app.post("/api/voice/preflight")
    async def voice_preflight(body: VoiceRunRequest):
        return app.state.host.voice_preflight(body)

    @app.post("/api/voice/runs", status_code=202)
    async def voice_start(body: VoiceRunRequest):
        return await app.state.host.start_voice(body)

    @app.get("/api/voice/runs")
    async def voice_runs():
        return app.state.host.voice.snapshot()

    @app.get("/api/voice/runs/{identifier}")
    async def voice_run(identifier: str):
        return app.state.host.voice.get(identifier)

    @app.get("/api/voice/runs/{identifier}/inspection")
    async def voice_inspection(identifier: str):
        return app.state.host.voice.inspect(identifier)

    @app.post("/api/voice/runs/{identifier}/stop")
    async def voice_stop(identifier: str):
        return await app.state.host.voice.stop(identifier)

    @app.get("/api/voice/runs/{identifier}/artifacts/{kind}")
    async def voice_artifact(
        identifier: str,
        kind: Literal["source", "encoded", "recovered", "decoded"],
        as_wav: bool = False,
    ):
        extension = "wav" if as_wav else "pcm" if kind in ("source", "decoded") else "codec2"
        return Response(
            app.state.host.voice.content(identifier, kind, as_wav),
            media_type="audio/wav" if as_wav else "application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{identifier}-{kind}.{extension}"'
            },
        )

    @app.post("/api/voice/runs/{identifier}/listening")
    async def voice_listening(identifier: str, body: ListeningRequest):
        return app.state.host.voice.listening(identifier, body.heard, body.notes)

    @app.post("/api/radio/preflight")
    async def radio_preflight(body: RadioRunRequest):
        return app.state.host.radio_preflight(body)

    @app.post("/api/radio/runs", status_code=202)
    async def radio_start(body: RadioRunRequest):
        return await app.state.host.start_radio(body)

    @app.get("/api/radio/runs")
    async def radio_runs():
        return app.state.host.radio.snapshot()

    @app.get("/api/radio/runs/{identifier}")
    async def radio_run(identifier: str):
        return app.state.host.radio.get(identifier)

    @app.post("/api/radio/runs/{identifier}/stop")
    async def radio_stop(identifier: str):
        return await app.state.host.radio.stop(identifier)

    @app.get("/api/radio/runs/{identifier}/content/{kind}")
    async def radio_content(identifier: str, kind: Literal["source", "recovered", "wire"]):
        return FileResponse(
            app.state.host.radio.content(identifier, kind),
            media_type="application/x-ndjson" if kind == "wire" else "application/octet-stream",
        )

    @app.get("/api/radio/runs/{identifier}/export")
    async def radio_export(identifier: str):
        return Response(
            app.state.host.radio.export(identifier),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="radio-{identifier}.zip"'},
        )

    @app.post("/api/nodes/{role}/memory-probe")
    async def memory_probe(role: Literal["A", "B"], body: MemoryProbeRequest):
        return await app.state.host.memory_probe(role, body.iterations, body.payload_bytes)

    @app.post("/api/nodes/{role}/crypto-benchmark")
    async def crypto_benchmark(role: Literal["A", "B"], body: crypto_benchmark_v2.Request):
        return await app.state.host.crypto_benchmark(role, body.iterations, body.payload_bytes)

    @app.get("/api/nodes/{role}/crypto-benchmark/{operation_id}")
    async def crypto_benchmark_evidence(
        role: Literal["A", "B"], operation_id: control_v2.UUID, include_records: bool = False
    ):
        return app.state.host.crypto_benchmark_evidence(role, operation_id, include_records)

    @app.post("/api/workload-assessments", status_code=201)
    async def workload_assessment(body: AssessmentRequest):
        return app.state.host.observations.save(body)

    @app.get("/api/workload-assessments")
    async def workload_assessments(limit: int = Query(20, ge=1, le=100)):
        return app.state.host.observations.list(limit)

    @app.get("/api/workload-assessments/{identifier}")
    async def workload_assessment_get(identifier: control_v2.UUID):
        return app.state.host.observations.get(identifier)

    @app.post("/api/nodes/{role}/memory-observation")
    async def memory_observation_start(role: Literal["A", "B"], body: memory_observation_v2.Start):
        return await app.state.host.observations.start_memory(role, body.duration_ms)

    @app.post("/api/nodes/{role}/memory-observation/{observation_id}/collect", status_code=201)
    async def memory_observation_collect(
        role: Literal["A", "B"], observation_id: control_v2.UUID, stop: bool = False
    ):
        return await app.state.host.observations.collect_memory(role, observation_id, stop)

    @app.post("/api/nodes/{role}/source-observation/{run_id}/collect", status_code=201)
    async def source_observation_collect(role: Literal["A", "B"], run_id: control_v2.UUID):
        return await app.state.host.observations.collect_source(role, run_id)

    @app.post("/api/physical-campaigns/plans/preview")
    async def physical_campaign_preview(body: CampaignSpec):
        return app.state.host.campaign_plans.preview(body)

    @app.post("/api/physical-campaigns/plans", status_code=201)
    async def physical_campaign_save(body: CampaignSpec):
        return app.state.host.campaign_plans.create(body)

    @app.get("/api/physical-campaigns/plans")
    async def physical_campaign_plans(limit: int = Query(20, ge=1, le=100)):
        return app.state.host.campaign_plans.list(limit)

    @app.get("/api/physical-campaigns/plans/{plan_id}")
    async def physical_campaign_plan(plan_id: control_v2.UUID):
        return app.state.host.campaign_plans.get(plan_id)

    @app.get("/api/diagnostic-runs/{run_id}")
    async def diagnostic_run(run_id: control_v2.UUID):
        return app.state.host.diagnostics.get(run_id)

    @app.get("/api/diagnostic-runs/{run_id}/evidence")
    async def diagnostic_run_evidence(run_id: control_v2.UUID, include_records: bool = False):
        return app.state.host.diagnostics.evidence(run_id, include_records)

    @app.post("/api/nodes/{role}/operation/stop")
    async def stop_operation(role: Literal["A", "B"], body: StopOperationRequest):
        return await app.state.host.stop_node_operation(role, body.operation_id)

    @app.post("/api/nodes/{role}/audio/capture", status_code=202)
    async def audio_capture(role: Literal["A", "B"], body: CaptureRequest):
        return await app.state.host.audio_action(role, "capture", sample_count=body.sample_count)

    @app.post("/api/nodes/{role}/audio/ptt", status_code=202)
    async def audio_ptt(role: Literal["A", "B"], body: CaptureRequest):
        return await app.state.host.audio_action(
            role, "capture", sample_count=body.sample_count, wait_for_ptt=True
        )

    @app.post("/api/nodes/{role}/audio/play", status_code=202)
    async def audio_play(role: Literal["A", "B"], body: audio_contract_v2.Play):
        return await app.state.host.audio_action(role, "play", artifact_id=body.artifact_id)

    @app.post("/api/nodes/{role}/audio/retrieve", status_code=202)
    async def audio_retrieve(role: Literal["A", "B"], body: audio_contract_v2.Play):
        return await app.state.host.audio_action(role, "retrieve", artifact_id=body.artifact_id)

    @app.post("/api/nodes/{role}/audio/codec", status_code=202)
    async def audio_codec(role: Literal["A", "B"], body: audio_contract_v2.Play):
        return await app.state.host.audio_action(role, "codec", artifact_id=body.artifact_id)

    @app.get("/api/audio/operations/{identifier}/artifacts/{stage}")
    async def codec_artifact(
        identifier: str, stage: Literal["source", "encoded", "decoded"], as_wav: bool = False
    ):
        extension = "wav" if as_wav else "codec2" if stage == "encoded" else "pcm"
        return Response(
            app.state.host.audio.codec_content(identifier, stage, as_wav),
            media_type="audio/wav" if as_wav else "application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{identifier}-{stage}.{extension}"'
            },
        )

    @app.post("/api/audio/operations/{identifier}/playback")
    async def codec_playback(identifier: str, body: CodecPlaybackRequest):
        return app.state.host.audio.link_playback(identifier, body.operation_id, body.stage)

    @app.get("/api/audio/operations")
    async def audio_operations():
        return app.state.host.audio.snapshot()

    @app.get("/api/audio/operations/{identifier}")
    async def audio_operation(identifier: str):
        return app.state.host.audio.get(identifier)

    @app.post("/api/audio/operations/{identifier}/stop")
    async def audio_stop(identifier: str):
        return await app.state.host.audio.stop(identifier)

    @app.get("/api/audio/operations/{identifier}/wav")
    async def audio_wav(identifier: str):
        return Response(
            app.state.host.audio.wav(identifier),
            media_type="audio/wav",
            headers={"Content-Disposition": f'attachment; filename="{identifier}.wav"'},
        )

    @app.post("/api/audio/operations/{identifier}/listening")
    async def audio_listening(identifier: str, body: ListeningRequest):
        return app.state.host.audio.listening(identifier, body.heard, body.notes)

    @app.get("/api/nodes/{role}/artifacts")
    async def node_artifacts(role: Literal["A", "B"]):
        return await app.state.host.artifact_action("list", role)

    @app.post("/api/nodes/{role}/artifacts", status_code=202)
    async def artifact_upload(role: Literal["A", "B"], request: Request):
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > 196608:
                raise ValueError("File upload request exceeds the bounded JSON limit")
            data.extend(chunk)
        try:
            body = ArtifactUploadRequest.model_validate_json(bytes(data))
        except RecursionError as exc:
            raise ValueError("Invalid file upload JSON") from exc
        return await app.state.host.artifact_action(
            "start_upload",
            role,
            decode_upload(body.data_b64),
            format=body.format,
            kind=body.kind,
            name=body.name,
        )

    @app.delete("/api/nodes/{role}/artifacts/{artifact_id}")
    async def artifact_delete(role: Literal["A", "B"], artifact_id: str):
        return await app.state.host.artifact_action("delete", role, artifact_id)

    @app.post("/api/nodes/{role}/artifacts/{artifact_id}/download", status_code=202)
    async def artifact_download(role: Literal["A", "B"], artifact_id: str):
        return await app.state.host.artifact_action("start_download", role, artifact_id)

    @app.get("/api/artifact-transfers")
    async def artifact_transfers():
        return app.state.host.artifacts.snapshot()

    @app.get("/api/artifact-transfers/{transfer_id}")
    async def artifact_transfer(transfer_id: str):
        return app.state.host.artifacts.get(transfer_id)

    @app.post("/api/artifact-transfers/{transfer_id}/cancel")
    async def artifact_cancel(transfer_id: str):
        return await app.state.host.artifacts.cancel(transfer_id)

    @app.get("/api/artifact-transfers/{transfer_id}/content")
    async def artifact_content(transfer_id: str):
        path = app.state.host.artifacts.content(transfer_id)
        return FileResponse(
            path, media_type="application/octet-stream", filename=f"{transfer_id}.bin"
        )

    @app.get("/api/protocol/v2/known-data")
    async def known_data_protocol():
        return {
            "version": 2,
            "contract_version": v2.CONTRACT_VERSION,
            "scope": "numerical preparation only; physical RF execution pending",
            "execution_available": False,
            "plan_schema": KnownDataPlan.model_json_schema(),
            "event_schema": rf_events_v2.schema(),
            "event_schema_sha256": rf_events_v2.schema_digest(),
        }

    @app.post("/api/experiments/v2/known-data/preview")
    async def known_data_preview(plan: KnownDataPlan):
        return preview_known_data(plan)

    @app.get("/api/protocol/v2/execution")
    async def execution_protocol():
        return {
            "schema": run_protocol_v2.schema(),
            "schema_sha256": run_protocol_v2.schema_digest(),
            "execution_modes": [],
            "reason": "Physical RF execution adapter and firmware support pending",
            "hardware_validated": False,
        }

    @app.get("/api/v2/execution")
    async def execution_state():
        return app.state.host.snapshot()["v2_execution"]

    @app.get("/api/procedures")
    async def procedures():
        return app.state.host.procedures.snapshot()

    @app.post("/api/procedures/serial/preview")
    async def preview_serial(body: SerialValidationRequest):
        return serial_plan(body)

    @app.post("/api/procedures/serial", status_code=201)
    async def start_serial(body: SerialValidationRequest):
        return await app.state.host.start_serial(body)

    @app.post("/api/procedures/stop")
    async def stop_procedure():
        async with app.state.host.lock:
            return await app.state.host.procedures.stop()

    @app.post("/api/experiments/{catalog_id}/preflight")
    async def experiment_preflight(catalog_id: str, body: PreflightRequest):
        return app.state.host.preflight(catalog_id, body.roles, body.workload)

    def require_procedure(identity):
        run = app.state.host.procedures.get(identity)
        if run is None:
            raise HTTPException(404, "Procedure run not found")
        return run

    @app.get("/api/procedures/runs/{identity}")
    async def procedure_detail(identity: str):
        run = require_procedure(identity)
        return {
            **run,
            "matches_current_profile": run.get("profile_sha256")
            == app.state.host.procedures.profile_sha256,
        }

    @app.get("/api/procedures/runs/{identity}/evidence")
    async def procedure_evidence(
        identity: str,
        after: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
        case_id: str | None = None,
    ):
        run = require_procedure(identity)
        if case_id and not any(c["id"] == case_id for c in run["cases"]):
            raise HTTPException(404, "Procedure case not found")
        rows = app.state.host.procedures.evidence(identity, after, limit, case_id)
        return {"events": rows, "next_after": rows[-1]["id"] if rows else after}

    @app.get("/api/procedures/runs/{identity}/export/{format}")
    async def procedure_export(identity: str, format: str):
        run = require_procedure(identity)
        require_finished(run)
        service = app.state.host.procedures
        if format == "jsonl":
            return StreamingResponse(
                ((json.dumps(row) + "\n").encode() for row in service.all_evidence(identity)),
                media_type="application/x-ndjson",
            )
        if format == "json":
            content, media = json.dumps(run, indent=2), "application/json"
        elif format == "csv":
            content, media = service.csv(run), "text/csv"
        elif format == "zip":
            content, media = service.bundle(run), "application/zip"
        else:
            raise HTTPException(404, "Use json, csv, jsonl or zip")
        return Response(
            content,
            media_type=media,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{identity}-{run["catalog_id"]}.{format}"'
                )
            },
        )

    @app.post("/api/v2/stop")
    async def stop_v2():
        async with app.state.host.lock:
            return await app.state.host.procedures.stop()

    def require_v2_run(identity):
        record = app.state.host.records.run(identity)
        if record is None:
            raise HTTPException(404, "V2 run not found")
        return record

    def require_v2_campaign(identity):
        record = app.state.host.records.campaign(identity)
        if record is None:
            raise HTTPException(404, "V2 campaign not found")
        return record

    def require_finished(record):
        if not record.get("finished_at") or record["status"] in (
            "preparing",
            "running",
            "paused",
            "stopping",
        ):
            raise HTTPException(409, "Stop or finish before exporting")

    @app.get("/api/v2/runs/{run_id}")
    async def v2_run_detail(run_id: str):
        return require_v2_run(run_id)

    @app.get("/api/v2/runs/{run_id}/events")
    async def v2_run_events(
        run_id: str, after: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=1000)
    ):
        require_v2_run(run_id)
        rows = app.state.host.records.events(run_id, after=after, limit=limit)
        return {"events": rows, "next_after": rows[-1]["id"] if rows else after}

    @app.get("/api/v2/runs/{run_id}/artifacts/{digest}")
    async def v2_artifact(run_id: str, digest: str):
        run = require_v2_run(run_id)
        artifact = next((a for a in run["artifacts"] if a["sha256"] == digest), None)
        if artifact is None:
            raise HTTPException(404, "Artifact not found")
        content = (app.state.host.store.root / artifact["relative_path"]).read_bytes()
        import hashlib

        if hashlib.sha256(content).hexdigest() != digest:
            raise HTTPException(409, "Artifact failed integrity verification")
        return Response(content, media_type="application/octet-stream")

    @app.get("/api/v2/runs/{run_id}/export/{format}")
    async def v2_run_export(run_id: str, format: str):
        run = require_v2_run(run_id)
        require_finished(run)
        records = app.state.host.records
        if format == "json":
            content, media = json.dumps(run, indent=2), "application/json"
        elif format == "csv":
            content, media = run_csv(run), "text/csv"
        elif format == "jsonl":
            return StreamingResponse(
                ((json.dumps(row) + "\n").encode() for row in event_rows(records, run_id)),
                media_type="application/x-ndjson",
            )
        elif format == "zip":
            content, media = evidence_zip(records, [run]), "application/zip"
        else:
            raise HTTPException(404, "Use json, csv, jsonl or zip")
        return Response(
            content,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{run_id}.{format}"'},
        )

    @app.post("/api/v2/comparisons")
    async def v2_comparison(body: ComparisonRequest):
        return compare_runs([require_v2_run(identity) for identity in body.run_ids])

    @app.get("/api/v2/campaigns/{campaign_id}")
    async def v2_campaign_detail(campaign_id: str):
        record = require_v2_campaign(campaign_id)
        return {**record, "summary": v2_campaign_summary(record, app.state.host.records)}

    @app.get("/api/v2/campaigns/{campaign_id}/export/zip")
    async def v2_campaign_export(campaign_id: str):
        record = require_v2_campaign(campaign_id)
        require_finished(record)
        runs = [require_v2_run(c["run_id"]) for c in record["cases"] if c["run_id"]]
        return Response(
            evidence_zip(app.state.host.records, runs, record),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{campaign_id}-v2.zip"'},
        )

    @app.post("/api/bench/mode")
    @app.post("/api/nodes/connection")
    @app.post("/api/v2/runs")
    @app.post("/api/v2/campaigns")
    @app.post("/api/v2/campaigns/preview")
    @app.post("/api/v2/campaigns/{identity}/rerun")
    @app.post("/api/v2/campaigns/{identity}/pause")
    @app.post("/api/procedures/integration")
    @app.post("/api/procedures/integration/preview")
    @app.post("/api/campaigns")
    @app.post("/api/campaigns/preview")
    @app.post("/api/campaigns/{identity}/rerun")
    @app.post("/api/campaigns/{identity}/pause")
    async def removed_execution():
        raise HTTPException(
            410,
            "Simulated execution was removed. Connect physical nodes individually. "
            "RF/campaign execution requires a physical adapter and supporting firmware.",
        )

    @app.post("/api/nodes/{role}/connection")
    async def node_connection(role: Literal["A", "B"], body: HardwareConnectionRequest):
        return await app.state.host.connect_node(role, body.port)

    @app.get("/api/ports")
    async def ports():
        found = await asyncio.to_thread(discover_ports)
        return {
            "ports": found,
            "hardware_connection_supported": True,
            "reason": "Requires matching v2 diagnostic firmware",
        }

    @app.post("/api/runs", status_code=201)
    async def start(spec: PhysicalRunRequest):
        return await app.state.host.start(spec)

    @app.post("/api/runs/stop")
    async def stop():
        return await app.state.host.stop()

    def require_run(run_id: str) -> dict:
        run = app.state.host.store.run(run_id)
        if run is None:
            raise HTTPException(404, "Run not found")
        return run

    @app.post("/api/analysis/compare")
    async def comparison(body: ComparisonRequest):
        return compare([require_run(run_id) for run_id in body.run_ids])

    def require_campaign(campaign_id: str) -> dict:
        campaign = app.state.host.store.campaign(campaign_id)
        if campaign is None:
            raise HTTPException(404, "Campaign not found")
        return campaign

    def campaign_runs(campaign: dict) -> list[dict]:
        return [require_run(case["run_id"]) for case in campaign["cases"] if case["run_id"]]

    @app.get("/api/campaigns/{campaign_id}")
    async def campaign_detail(campaign_id: str):
        campaign = require_campaign(campaign_id)
        runs = campaign_runs(campaign)
        return {**campaign, "runs": runs, "summary": campaign_summary(campaign, runs)}

    @app.get("/api/campaigns/{campaign_id}/export/{format}")
    async def campaign_export(campaign_id: str, format: str):
        campaign = require_campaign(campaign_id)
        if campaign["status"] in ("running", "paused", "stopping"):
            raise HTTPException(409, "Stop or finish the campaign before exporting")
        runs = campaign_runs(campaign)
        if format == "json":
            content = json.dumps(
                {"campaign": campaign, "runs": runs, "summary": campaign_summary(campaign, runs)},
                indent=2,
            )
            media = "application/json"
        elif format == "csv":
            content, media = campaign_csv(campaign, runs), "text/csv"
        elif format == "zip":
            content = evidence_bundle(
                campaign,
                runs,
                {run["id"]: app.state.host.store.events(run["id"]) for run in runs},
                catalog(),
            )
            media = "application/zip"
        else:
            raise HTTPException(404, "Use json, csv, or zip")
        return Response(
            content,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="campaign-{campaign_id}.{format}"'
            },
        )

    @app.get("/api/runs/{run_id}")
    async def run_detail(run_id: str):
        return require_run(run_id)

    @app.get("/api/runs/{run_id}/export/{format}")
    async def export(run_id: str, format: str):
        run = require_run(run_id)
        if format == "json":
            content, media = json.dumps(run, indent=2), "application/json"
        elif format == "jsonl":
            content = "".join(json.dumps(row) + "\n" for row in app.state.host.store.events(run_id))
            media = "application/x-ndjson"
        elif format == "csv":
            output = io.StringIO(newline="")
            flat = {
                "run_id": run_id,
                "mode": run["mode"],
                "status": run["status"],
                "created_at": run["created_at"],
                "spec_json": json.dumps(run["spec"]),
                **run["metrics"],
            }
            writer = csv.DictWriter(output, fieldnames=list(flat))
            writer.writeheader()
            writer.writerow(flat)
            content, media = output.getvalue(), "text/csv"
        else:
            raise HTTPException(404, "Use json, jsonl, or csv")
        return Response(
            content,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{run_id}.{format}"'},
        )

    @app.post("/api/audio/references", status_code=201)
    async def upload_reference(request: Request, name: str = "reference.wav"):
        if len(name) > 128:
            raise HTTPException(400, "Filename must be at most 128 characters")
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "WAV upload exceeds 1 MiB")
        reference = inspect_wav(bytes(chunks), name)
        host = app.state.host
        save_wav(host.store.root, reference, bytes(chunks))
        host.store.save_reference(reference)
        return reference

    @app.get("/api/audio/references/{reference_id}/wav")
    async def reference_wav(reference_id: str):
        reference = next(
            (item for item in app.state.host.store.references() if item["id"] == reference_id), None
        )
        if reference is None:
            raise HTTPException(404, "Reference not found")
        return FileResponse(
            app.state.host.store.root / "audio" / f"{reference_id}.wav", media_type="audio/wav"
        )

    @app.websocket("/api/live")
    async def live(websocket: WebSocket):
        if not local_origin(websocket.headers.get("origin"), websocket.url.port):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(app.state.host.snapshot())
                await asyncio.sleep(0.3)
        except (WebSocketDisconnect, OSError):
            pass

    dist = frontend_dir or TESTBED_ROOT / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
    else:

        @app.get("/")
        async def build_instructions():
            return {
                "message": "Build the dashboard: cd frontend && npm install && npm run build",
                "api": "/docs",
            }

    return app
