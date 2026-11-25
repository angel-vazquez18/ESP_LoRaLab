"""CLI client; the running backend remains the only serial-port owner."""

import base64
import json
from pathlib import Path
from typing import Annotated
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import typer

app = typer.Typer(no_args_is_help=True, help="Control the local LoRa laboratory.")
BASE_URL = "http://127.0.0.1:8000"


def request(path: str, body: dict | None = None, method: str | None = None, timeout: float = 20):
    req = Request(
        BASE_URL + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        typer.echo(exc.read().decode(), err=True)
        raise typer.Exit(1) from exc
    except URLError as exc:
        typer.echo("Backend unavailable. Start it with: lora-testbed serve", err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(result, indent=2))


@app.command()
def serve(data_dir: Path = Path("data"), port: int = 8000):
    """Serve the dashboard locally (one worker, loopback only)."""
    import uvicorn

    from .app import create_app

    uvicorn.run(create_app(data_dir=data_dir), host="127.0.0.1", port=port)


@app.command()
def status():
    """Show node readiness, active experiment, and saved runs."""
    request("/api/state")


@app.command()
def ports():
    """List available serial ports without opening them."""
    request("/api/ports")


@app.command()
def node(role: str, port: str | None = None):
    """Connect A/B to PORT, or disconnect that role when PORT is omitted."""
    request(f"/api/nodes/{role.upper()}/connection", {"port": port})


@app.command()
def stop():
    """Stop the active run, preserving partial evidence."""
    request("/api/runs/stop", {})


@app.command()
def preview_v2(plan: Path | None = None):
    """Calculate a v2 known-data budget from PLAN JSON, or the bring-up defaults."""
    try:
        body = json.loads(plan.read_text()) if plan else {}
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(f"Cannot read plan: {exc}") from exc
    if not isinstance(body, dict):
        raise typer.BadParameter("Plan must be a JSON object")
    request("/api/experiments/v2/known-data/preview", body)


@app.command()
def procedure_status(run_id: str):
    """Show a saved or active procedure run, including case assessments."""
    request(f"/api/procedures/runs/{run_id}")


@app.command()
def compare(run_ids: Annotated[list[str], typer.Argument()]):
    """Compare up to four stored runs, including settings differences."""
    request("/api/analysis/compare", {"run_ids": run_ids})


@app.command()
def serial_check(
    role: str | None = None,
    cycles: Annotated[int, typer.Option(min=1, max=10)] = 3,
    preview: bool = False,
):
    """Check one physical node, or A then B. This does not qualify all of IF-01."""
    if role is not None and role.lower() not in ("a", "b", "both"):
        raise typer.BadParameter("Role must be A, B or both; omit to use the connected node")
    roles = None if role is None else ["A", "B"] if role.lower() == "both" else [role.upper()]
    request(
        "/api/procedures/serial/preview" if preview else "/api/procedures/serial",
        {"roles": roles, "cycles": cycles},
    )


@app.command()
def preflight(experiment: str, role: str | None = None, workload: str = "default"):
    """Show a test's physical node requirements and missing capabilities."""
    if role is not None and role.lower() not in ("a", "b", "both"):
        raise typer.BadParameter("Role must be A, B or both")
    if workload not in ("default", "local", "rf"):
        raise typer.BadParameter("Workload must be default, local or rf")
    roles = None if role is None else ["A", "B"] if role.lower() == "both" else [role.upper()]
    request(
        f"/api/experiments/{experiment.upper()}/preflight", {"roles": roles, "workload": workload}
    )


@app.command()
def campaign_plan(path: Path, preview: bool = False):
    """Preview or save physical campaign intent; this command does not start work."""
    document = json.loads(path.read_text())
    request("/api/physical-campaigns/plans" + ("/preview" if preview else ""), document)


@app.command()
def campaign_plans():
    """List retained physical campaign plan summaries."""
    request("/api/physical-campaigns/plans")


@app.command()
def campaign_plan_result(plan_id: str):
    """Read the exact saved cases, seeded order, batches and readiness snapshot."""
    from pydantic import TypeAdapter

    from .control_v2 import UUID

    TypeAdapter(UUID).validate_python(plan_id)
    request(f"/api/physical-campaigns/plans/{plan_id}")


@app.command()
def campaign_execute(plan_id: str):
    """Execute a saved physical plan in its original order."""
    from pydantic import TypeAdapter

    from .control_v2 import UUID

    TypeAdapter(UUID).validate_python(plan_id)
    request("/api/physical-campaigns/executions", {"plan_id": plan_id})


@app.command()
def campaign_executions():
    """Show the active physical campaign and recent execution summaries."""
    request("/api/physical-campaigns/executions")


@app.command()
def campaign_result(identifier: str):
    """Read saved child links and outcomes for a physical campaign."""
    from pydantic import TypeAdapter

    from .control_v2 import UUID

    TypeAdapter(UUID).validate_python(identifier)
    request(f"/api/physical-campaigns/executions/{identifier}")


@app.command()
def campaign_pause(identifier: str):
    """Finish the current case, then pause while keeping bench ownership."""
    from pydantic import TypeAdapter

    from .control_v2 import UUID

    TypeAdapter(UUID).validate_python(identifier)
    request(f"/api/physical-campaigns/executions/{identifier}/pause", {})


@app.command()
def campaign_resume(identifier: str):
    """Resume the exact queued order on the original enrolled connections."""
    from pydantic import TypeAdapter

    from .control_v2 import UUID

    TypeAdapter(UUID).validate_python(identifier)
    request(f"/api/physical-campaigns/executions/{identifier}/resume", {})


@app.command()
def campaign_cancel(identifier: str, reason: str = "Stopped by operator"):
    """Stop the active child, retain partial evidence and reason-code skipped cases."""
    from pydantic import TypeAdapter

    from .control_v2 import UUID

    TypeAdapter(UUID).validate_python(identifier)
    request(
        f"/api/physical-campaigns/executions/{identifier}/cancel", {"reason": reason}, timeout=90
    )


@app.command()
def campaign_rerun(identifier: str, case_ids: Annotated[list[str], typer.Argument()]):
    """Create a linked execution for selected original case IDs in saved order."""
    from pydantic import TypeAdapter

    from .control_v2 import UUID

    for value in [identifier, *case_ids]:
        TypeAdapter(UUID).validate_python(value)
    request(f"/api/physical-campaigns/executions/{identifier}/rerun", {"case_ids": case_ids})


@app.command()
def campaign_export(identifier: str, output: Path):
    """Verify and save the complete campaign bundle without overwriting a file."""
    import hashlib

    from pydantic import TypeAdapter

    from .control_v2 import UUID
    from .physical_campaign_evidence import MAX_BYTES, verify_campaign_bundle

    TypeAdapter(UUID).validate_python(identifier)
    try:
        with urlopen(
            BASE_URL + f"/api/physical-campaigns/executions/{identifier}/export", timeout=90
        ) as response:
            data = response.read(MAX_BYTES + 1)
            expected = response.headers.get("X-Content-SHA256")
        if not expected or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Campaign download hash differs or is missing")
        checked = verify_campaign_bundle(data)
        with output.open("xb") as target:
            target.write(data)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps({"saved": str(output), **checked}, indent=2))


@app.command()
def campaign_verify(path: Path):
    """Verify a downloaded campaign archive offline, without opening node ports."""
    from .physical_campaign_evidence import MAX_BYTES, verify_campaign_bundle

    try:
        with path.open("rb") as stream:
            checked = verify_campaign_bundle(stream.read(MAX_BYTES + 1))
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(checked, indent=2))


@app.command()
def workload_assess(path: Path):
    """Save an assessment of an imported source/memory trace; never hardware qualification."""
    if path.stat().st_size > 12 * 1024 * 1024:
        raise typer.BadParameter("Trace exceeds 12 MiB")
    request("/api/workload-assessments", json.loads(path.read_text()))


@app.command()
def workload_assessments():
    """List retained observed-workload assessments."""
    request("/api/workload-assessments")


@app.command()
def workload_result(identifier: str):
    """Read a saved assessment and its exact raw evidence."""
    from pydantic import TypeAdapter

    from .control_v2 import UUID

    TypeAdapter(UUID).validate_python(identifier)
    request(f"/api/workload-assessments/{identifier}")


@app.command()
def memory_observe(
    role: str, duration_ms: Annotated[int, typer.Option(min=1000, max=300000)] = 30000
):
    """Start a finite observer alongside the selected node's workload."""
    if role.upper() not in ("A", "B"):
        raise typer.BadParameter("Role must be A or B")
    request(f"/api/nodes/{role.upper()}/memory-observation", {"duration_ms": duration_ms})


@app.command()
def memory_collect(role: str, observation_id: str, stop: bool = False):
    """Save actual observer status/events, optionally stopping that exact observer first."""
    from pydantic import TypeAdapter

    from .control_v2 import UUID

    TypeAdapter(UUID).validate_python(observation_id)
    if role.upper() not in ("A", "B"):
        raise typer.BadParameter("Role must be A or B")
    request(
        f"/api/nodes/{role.upper()}/memory-observation/{observation_id}/collect?stop={str(stop).lower()}",
        {},
    )


@app.command()
def source_collect(role: str, run_id: str):
    """Read terminal source pages before the owning RF runner closes its session."""
    from pydantic import TypeAdapter

    from .control_v2 import UUID

    TypeAdapter(UUID).validate_python(run_id)
    if role.upper() not in ("A", "B"):
        raise typer.BadParameter("Role must be A or B")
    request(f"/api/nodes/{role.upper()}/source-observation/{run_id}/collect", {}, timeout=60)


@app.command()
def memory_probe(
    role: str,
    iterations: Annotated[int, typer.Option(min=1, max=10000)] = 10,
    payload_bytes: Annotated[int, typer.Option(min=1, max=65536)] = 4096,
):
    """Start a bounded local memory operation on main-node control firmware."""
    if role.upper() not in ("A", "B"):
        raise typer.BadParameter("Role must be A or B")
    request(
        f"/api/nodes/{role.upper()}/memory-probe",
        {"iterations": iterations, "payload_bytes": payload_bytes},
    )


@app.command()
def crypto_benchmark(
    role: str,
    iterations: Annotated[int, typer.Option(min=1, max=10000)] = 1000,
    payload_bytes: int = 160,
):
    """Start a public-vector local benchmark, with USB/RF outside each timed call."""
    if role.upper() not in ("A", "B") or payload_bytes not in (16, 64, 160, 199):
        raise typer.BadParameter("Role must be A/B; payload must be 16, 64, 160 or 199")
    request(
        f"/api/nodes/{role.upper()}/crypto-benchmark",
        {"iterations": iterations, "payload_bytes": payload_bytes},
    )


@app.command()
def crypto_benchmark_result(role: str, operation_id: str, records: bool = False):
    """Read retained local measurements; incomplete evidence has no distribution."""
    if role.upper() not in ("A", "B"):
        raise typer.BadParameter("Role must be A or B")
    request(
        f"/api/nodes/{role.upper()}/crypto-benchmark/{operation_id}?include_records={str(records).lower()}"
    )


@app.command()
def operation_stop(role: str, operation_id: str):
    """Cancel the selected node operation without disconnecting the node."""
    if role.upper() not in ("A", "B"):
        raise typer.BadParameter("Role must be A or B")
    request(f"/api/nodes/{role.upper()}/operation/stop", {"operation_id": operation_id})


@app.command()
def artifact_list(role: str):
    """List node file manifests through the running backend."""
    request(f"/api/nodes/{role.upper()}/artifacts")


@app.command()
def artifact_upload(role: str, file: Path, format: str = "known_data"):
    """Upload a bounded raw file and verify its committed readback."""
    if not file.is_file() or not 1 <= file.stat().st_size <= 131072:
        raise typer.BadParameter("Choose a file of 1–131072 bytes")
    with file.open("rb") as source:
        data = source.read(131073)
    if not 1 <= len(data) <= 131072:
        raise typer.BadParameter("File changed size; choose 1–131072 bytes")
    request(
        f"/api/nodes/{role.upper()}/artifacts",
        {
            "data_b64": base64.b64encode(data).decode(),
            "format": format,
            "name": file.name,
        },
    )


@app.command()
def artifact_download(role: str, artifact_id: str):
    """Start a verified download; poll the returned transfer ID."""
    request(f"/api/nodes/{role.upper()}/artifacts/{artifact_id}/download", {})


@app.command()
def artifact_transfer(transfer_id: str):
    """Inspect progress, verification and retained errors."""
    request(f"/api/artifact-transfers/{transfer_id}")


@app.command()
def artifact_cancel(transfer_id: str):
    """Cancel a transfer while preserving partial evidence."""
    request(f"/api/artifact-transfers/{transfer_id}/cancel", {})


@app.command()
def artifact_delete(role: str, artifact_id: str):
    """Delete an unused node file through the shared backend."""
    request(f"/api/nodes/{role.upper()}/artifacts/{artifact_id}", method="DELETE")


@app.command()
def artifact_save(transfer_id: str, output: Path):
    """Save a verified host file; an existing destination is never overwritten."""
    try:
        with urlopen(
            BASE_URL + f"/api/artifact-transfers/{transfer_id}/content", timeout=20
        ) as response:
            data = response.read(131073)
        if len(data) > 131072:
            raise ValueError("Unexpected file size")
        with output.open("xb") as target:
            target.write(data)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def audio_capture(role: str, samples: Annotated[int, typer.Option(min=1, max=24000)] = 24000):
    """Capture exact PCM, independently retrieve it and retain a WAV."""
    request(f"/api/nodes/{role.upper()}/audio/capture", {"sample_count": samples})


@app.command()
def audio_ptt(role: str, samples: Annotated[int, typer.Option(min=1, max=24000)] = 24000):
    """Arm one finite capture; release then press the configured PTT within 30 seconds."""
    request(f"/api/nodes/{role.upper()}/audio/ptt", {"sample_count": samples})


@app.command()
def audio_play(role: str, artifact_id: str):
    """Play one committed PCM file on the physical node."""
    request(f"/api/nodes/{role.upper()}/audio/play", {"artifact_id": artifact_id})


@app.command()
def audio_retrieve(role: str, artifact_id: str):
    """Verify a committed PCM file and wrap unchanged samples as WAV."""
    request(f"/api/nodes/{role.upper()}/audio/retrieve", {"artifact_id": artifact_id})


@app.command()
def audio_codec(role: str, artifact_id: str):
    """Encode/decode one committed PCM file and retain all three verified files."""
    request(f"/api/nodes/{role.upper()}/audio/codec", {"artifact_id": artifact_id})


@app.command()
def audio_link_playback(identifier: str, operation_id: str, stage: str = "decoded"):
    """Link a completed source/decoded playback and its listening observations."""
    if stage not in ("source", "decoded"):
        raise typer.BadParameter("Use source or decoded")
    request(
        f"/api/audio/operations/{identifier}/playback",
        {"operation_id": operation_id, "stage": stage},
    )


@app.command()
def audio_codec_save(identifier: str, stage: str, output: Path, wav: bool = False):
    """Save a verified codec stage; optional WAV wrapping applies only to PCM."""
    if stage not in ("source", "encoded", "decoded") or (wav and stage == "encoded"):
        raise typer.BadParameter("Choose source/encoded/decoded; WAV needs source or decoded")
    try:
        suffix = "?as_wav=true" if wav else ""
        with urlopen(
            BASE_URL + f"/api/audio/operations/{identifier}/artifacts/{stage}{suffix}", timeout=20
        ) as response:
            data = response.read(48045)
        if not data or len(data) > 48044:
            raise ValueError("Unexpected codec artifact size")
        with output.open("xb") as target:
            target.write(data)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def audio_status(identifier: str):
    """Inspect audio progress, errors, gain and retained signal findings."""
    request(f"/api/audio/operations/{identifier}")


@app.command()
def audio_stop(identifier: str):
    """Stop the shared audio job and confirm bounded cleanup."""
    request(f"/api/audio/operations/{identifier}/stop", {})


@app.command()
def audio_listening(identifier: str, heard: str = "not_checked", notes: str = ""):
    """Record operator listening separately from driver completion."""
    if heard not in ("not_checked", "heard", "not_heard"):
        raise typer.BadParameter("Use not_checked, heard or not_heard")
    request(f"/api/audio/operations/{identifier}/listening", {"heard": heard, "notes": notes})


@app.command()
def audio_save(identifier: str, output: Path):
    """Save verified PCM as WAV without overwriting an existing file."""
    try:
        with urlopen(BASE_URL + f"/api/audio/operations/{identifier}/wav", timeout=20) as response:
            data = response.read(48045)
        if len(data) > 48044:
            raise ValueError("Unexpected WAV size")
        with output.open("xb") as target:
            target.write(data)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def voice_start(
    source: str = "microphone",
    reference_id: str | None = None,
    direction: str = "A_TO_B",
    samples: Annotated[int, typer.Option(min=1, max=24000)] = 24000,
    timeout_ms: Annotated[int, typer.Option(min=1000, max=3600000)] = 30000,
    comparisons: bool = True,
    check: bool = False,
    sf: Annotated[int, typer.Option(min=7, max=12)] = 7,
    bandwidth: int = 125000,
    coding_rate: int = 5,
    power: Annotated[int, typer.Option(min=2, max=20)] = 2,
    ack: str = "none",
    retries: int | None = None,
    guard_us: int = 50000,
):
    """Run a protected clip, or check readiness, with labelled data comparisons."""
    if source not in ("reference", "microphone"):
        raise typer.BadParameter("Use reference or microphone")
    if (source == "reference") != (reference_id is not None):
        raise typer.BadParameter("Select a reference ID only for a reference source")
    link = {"ack_mode": ack, "guard_us": guard_us}
    if retries is not None:
        link["max_retries"] = retries
    request(
        "/api/voice/preflight" if check else "/api/voice/runs",
        {
            "source": source,
            "reference_id": reference_id,
            "direction": direction,
            "sample_count": samples,
            "timeout_ms": timeout_ms,
            "include_comparisons": comparisons,
            "security": "aes128_gcm",
            "link": link,
            "radio": {
                "spreading_factor": sf,
                "bandwidth_hz": bandwidth,
                "coding_rate_denominator": coding_rate,
                "tx_power_dbm": power,
            },
        },
    )


@app.command()
def voice_status(identifier: str):
    """Inspect voice stages, verified files, comparison bases and observations."""
    request(f"/api/voice/runs/{identifier}")


@app.command()
def voice_stop(identifier: str):
    """Stop the whole voice job and retain bounded child cleanup."""
    request(f"/api/voice/runs/{identifier}/stop", {})


@app.command()
def voice_listening(identifier: str, heard: str = "not_checked", notes: str = ""):
    """Record receiver listening separately from delivery and driver completion."""
    if heard not in ("not_checked", "heard", "not_heard"):
        raise typer.BadParameter("Use not_checked, heard or not_heard")
    request(f"/api/voice/runs/{identifier}/listening", {"heard": heard, "notes": notes})


@app.command()
def voice_save(identifier: str, kind: str, output: Path, wav: bool = False):
    """Save a verified voice stage without overwriting an existing target."""
    if kind not in ("source", "encoded", "recovered", "decoded") or (
        wav and kind not in ("source", "decoded")
    ):
        raise typer.BadParameter(
            "Choose source/encoded/recovered/decoded; WAV needs source or decoded"
        )
    try:
        suffix = "?as_wav=true" if wav else ""
        with urlopen(
            BASE_URL + f"/api/voice/runs/{identifier}/artifacts/{kind}{suffix}", timeout=20
        ) as response:
            data = response.read(48045)
        if not data or len(data) > 48044:
            raise ValueError("Unexpected voice artifact size")
        with output.open("xb") as target:
            target.write(data)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def radio_start(
    direction: str = "A_TO_B",
    security: str = "none",
    message_bytes: Annotated[int, typer.Option(min=1, max=65536)] = 64,
    timeout_ms: Annotated[int, typer.Option(min=1000, max=3600000)] = 10000,
    config: Path | None = None,
    preview: bool = False,
):
    """Run one known-data message using the shared physical backend."""
    try:
        body = (
            json.loads(config.read_text())
            if config
            else {
                "direction": direction.upper(),
                "security": security,
                "message_bytes": message_bytes,
                "timeout_ms": timeout_ms,
            }
        )
        if not isinstance(body, dict):
            raise ValueError("Configuration must be a JSON object")
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    request("/api/radio/preflight" if preview else "/api/radio/runs", body)


@app.command()
def integration_matrix(config: Path, preview: bool = False):
    """Preview or start a selected physical integration matrix."""
    try:
        body = json.loads(config.read_text())
        if not isinstance(body, dict):
            raise ValueError("Matrix configuration must be a JSON object")
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    request("/api/procedures/matrix/preview" if preview else "/api/procedures/matrix", body)


@app.command()
def lab_start(config: Path, preview: bool = False):
    """Run one lab fault between verified intact controls."""
    try:
        body = json.loads(config.read_text())
        if not isinstance(body, dict):
            raise ValueError("Configuration must be a JSON object")
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    request("/api/lab/preflight" if preview else "/api/lab/trials", body)


@app.command()
def lab_status(identifier: str | None = None):
    """Inspect saved trial assertions and their linked radio records."""
    request("/api/lab/trials" + (f"/{identifier}" if identifier else ""))


@app.command()
def lab_stop(identifier: str):
    """Stop the active trial and clean up its current run."""
    request(f"/api/lab/trials/{identifier}/stop", {})


@app.command()
def echo_start(
    direction: str = "A_TO_B",
    security: str = "none",
    message_bytes: Annotated[int, typer.Option(min=1, max=215)] = 64,
    timeout_ms: Annotated[int, typer.Option(min=1000, max=3600000)] = 10000,
    config: Path | None = None,
    preview: bool = False,
):
    """Run one verified physical echo using the shared radio owner."""
    try:
        body = (
            json.loads(config.read_text())
            if config
            else {
                "direction": direction.upper(),
                "security": security,
                "message_bytes": message_bytes,
                "timeout_ms": timeout_ms,
            }
        )
        if not isinstance(body, dict):
            raise ValueError("Configuration must be a JSON object")
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    request("/api/echo/preflight" if preview else "/api/echo/runs", body)


@app.command()
def echo_distribution(identifiers: list[str]):
    """Reconcile selected saved echoes in separate device/boot/settings cohorts."""
    request("/api/echo/distribution", identifiers)


@app.command()
def radio_status(identifier: str | None = None):
    """Show active/saved physical bring-up and its byte/evidence findings."""
    request("/api/radio/runs" + (f"/{identifier}" if identifier else ""))


@app.command()
def radio_stop(identifier: str):
    """Stop the finite radio job and confirm both node sessions close."""
    request(f"/api/radio/runs/{identifier}/stop", {})


@app.command()
def radio_export(identifier: str, output: Path):
    """Save the hashed radio evidence bundle without overwriting a file."""
    try:
        with urlopen(BASE_URL + f"/api/radio/runs/{identifier}/export", timeout=20) as response:
            data = response.read(128 * 1024 * 1024 + 1)
        if len(data) > 128 * 1024 * 1024:
            raise ValueError("Radio export exceeds 128 MiB limit")
        with output.open("xb") as target:
            target.write(data)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
