"""CLI client; the running backend remains the only serial-port owner."""

import json
from pathlib import Path
from typing import Annotated
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import typer

app = typer.Typer(no_args_is_help=True, help="Control the local LoRa laboratory.")
BASE_URL = "http://127.0.0.1:8000"


def request(path: str, body: dict | None = None):
    req = Request(
        BASE_URL + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=20) as response:
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
def operation_stop(role: str, operation_id: str):
    """Cancel the selected node operation without disconnecting the node."""
    if role.upper() not in ("A", "B"):
        raise typer.BadParameter("Role must be A or B")
    request(f"/api/nodes/{role.upper()}/operation/stop", {"operation_id": operation_id})
