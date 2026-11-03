"""Portable campaign evidence with configuration, raw events and content hashes."""

import csv
import hashlib
import html
import io
import json
import zipfile

from .comparison import campaign_summary


def campaign_csv(campaign: dict, runs: list[dict]) -> str:
    output = io.StringIO(newline="")
    fields = [
        "campaign_id",
        "case_index",
        "repetition",
        "axis",
        "axis_value",
        "direction",
        "status",
        "run_id",
        "mode",
        "sent",
        "received",
        "pdr",
        "throughput_bps",
        "timing_basis",
        "spec_json",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    by_id = {run["id"]: run for run in runs}
    for case in campaign["cases"]:
        run = by_id.get(case["run_id"])
        metrics = run["metrics"] if run else {}
        writer.writerow(
            {
                "campaign_id": campaign["id"],
                "case_index": case["index"],
                "repetition": case["repetition"],
                "axis": campaign["spec"]["axis"],
                "axis_value": case["axis_value"],
                "direction": case["spec"]["direction"],
                "status": run["status"] if run else case["status"],
                "run_id": case["run_id"],
                "mode": campaign["mode"],
                **{
                    key: metrics.get(key)
                    for key in ("sent", "received", "pdr", "throughput_bps", "timing_basis")
                },
                "spec_json": json.dumps(case["spec"]),
            }
        )
    return output.getvalue()


def evidence_bundle(campaign: dict, runs: list[dict], events: dict, coverage: list) -> bytes:
    files = {}

    def save(name, value):
        files[name] = json.dumps(value, indent=2).encode()

    save("campaign.json", campaign)
    save("summary.json", campaign_summary(campaign, runs))
    save("coverage.json", coverage)
    files["cases.csv"] = campaign_csv(campaign, runs).encode()
    for run in runs:
        save(f"runs/{run['id']}.json", run)
        files[f"events/{run['id']}.jsonl"] = "".join(
            json.dumps(row) + "\n" for row in events[run["id"]]
        ).encode()

    def escape(value):
        return html.escape(str(value))

    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{escape(value)}</td>"
            for value in (
                case["index"] + 1,
                case["repetition"],
                case["spec"]["direction"],
                case["axis_value"],
                case["status"],
                case["run_id"] or "Not started",
            )
        )
        + "</tr>"
        for case in campaign["cases"]
    )
    files["report.html"] = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>{escape(campaign["spec"]["name"])}</title><style>
body{{font:15px system-ui;max-width:1100px;margin:40px auto;padding:0 24px;color:#17273c}}
table{{border-collapse:collapse;width:100%}}
th,td{{text-align:left;padding:10px;border:1px solid #ccd5df}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere}}@media print{{body{{margin:0}}}}
</style><h1>{escape(campaign["spec"]["name"])}</h1>
<p>{escape(campaign["id"])} · {escape(campaign["status"])} · {escape(campaign["mode"])}</p>
<p><strong>Simulation only. This report does not validate RF, security or audio.</strong></p>
<p>{escape(campaign["spec"]["notes"])}</p><p>{escape(campaign["duration_basis"])}</p>
<table><thead><tr><th>Case</th><th>Repetition</th><th>Direction</th><th>Axis value</th>
<th>Status</th><th>Run ID</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Reproducible configuration</h2><pre>{escape(json.dumps(campaign["spec"], indent=2))}</pre>
<p>See cases.csv for individual measurements, summary.json for per-run variability,
coverage.json for all CDR requirements, runs/ for applied settings and events/ for raw evidence.
manifest.json contains SHA-256 hashes of every included file.</p></html>""".encode()
    save(
        "manifest.json",
        {
            "bundle_version": 1,
            "campaign_id": campaign["id"],
            "sha256": {
                name: hashlib.sha256(content).hexdigest() for name, content in files.items()
            },
        },
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()
