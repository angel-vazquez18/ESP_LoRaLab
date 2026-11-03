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
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import rf_events_v2, run_protocol_v2, v2
from .audio import MAX_UPLOAD_BYTES, inspect_wav, save_wav
from .catalog import catalog
from .comparison import campaign_summary, compare
from .experiments_v2 import KnownDataPlan
from .experiments_v2 import preview as preview_known_data
from .host import Host
from .models import StrictModel
from .nodes import discover_ports
from .paths import TESTBED_ROOT
from .reports import campaign_csv, evidence_bundle
from .reports_v2 import campaign_summary as v2_campaign_summary
from .reports_v2 import compare_runs, event_rows, evidence_zip, run_csv
from .serial_validation import SerialValidationRequest, serial_plan


class PreflightRequest(StrictModel):
    roles: list[Literal["A", "B"]] | None = Field(default=None, min_length=1, max_length=2)
    workload: Literal["default", "local", "rf"] = "default"


class PhysicalRunRequest(PreflightRequest):
    catalog_id: str = Field(default="IF-02", min_length=1, max_length=32)


class HardwareConnectionRequest(StrictModel):
    port: str | None = None


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
