"""Reproducible v2 exports, with streamed hashing of raw event records."""

import csv
import hashlib
import io
import json
import zipfile
from statistics import mean, stdev

from .comparison import flatten


def event_rows(records, run_id):
    after = 0
    while rows := records.events(run_id, after=after, limit=500):
        yield from rows
        after = rows[-1]["id"]


def compare_runs(runs):
    settings = [
        flatten(
            {"plan": r["plan"], "applied": r["applied_settings"], "simulation": r["simulation"]}
        )
        for r in runs
    ]
    fields = sorted(set().union(*(item.keys() for item in settings)))
    return {
        "runs": runs,
        "differences": [
            {"field": key, "values": [item.get(key) for item in settings]}
            for key in fields
            if any(item.get(key) != settings[0].get(key) for item in settings[1:])
        ],
        "provenance": "simulated",
        "hardware_validated": False,
        "warning": "Synthetic signal, memory and device timing; no physical RF performance claim",
    }


def campaign_summary(campaign, records):
    groups = {}
    for case in campaign["cases"]:
        run = records.run(case["run_id"]) if case["run_id"] else None
        if not run or run["status"] != "completed" or run["assessment"] != "pass":
            continue
        key = (case["axis_value"], run["plan"]["spec"]["direction"])
        groups.setdefault(key, []).append(run)
    result = []
    for (axis, direction), runs in groups.items():
        statistics = {}
        for key in ("pdr", "goodput_bps", "accepted_fragment_bps", "completion_ratio"):
            values = [r["metrics"][key] for r in runs if r["metrics"][key] is not None]
            statistics[key] = {
                "n": len(values),
                "mean": mean(values) if values else None,
                "sample_sd": stdev(values) if len(values) > 1 else None,
            }
        result.append(
            {
                "axis_value": axis,
                "direction": direction,
                "run_ids": [r["id"] for r in runs],
                "metrics": statistics,
            }
        )
    return {
        "groups": result,
        "basis": "Unweighted per-run statistics; completed passing cases only",
        "hardware_validated": False,
        "provenance": "simulated",
    }


def run_csv(run):
    row = {
        "run_id": run["id"],
        "mode": run["mode"],
        "protocol_version": 2,
        "status": run["status"],
        "assessment": run["assessment"],
        "direction": run["plan"]["spec"]["direction"],
        "plan_sha256": run["plan_sha256"],
        **run["metrics"],
        "plan_json": json.dumps(run["plan"]),
    }
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    return output.getvalue()


def evidence_zip(records, runs, campaign=None):
    output = io.BytesIO()
    hashes = {}
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:

        def save(name, content):
            archive.writestr(name, content)
            hashes[name] = hashlib.sha256(content).hexdigest()

        if campaign:
            save("campaign.json", json.dumps(campaign, indent=2).encode())
            save("summary.json", json.dumps(campaign_summary(campaign, records), indent=2).encode())
        save(
            "provenance.json",
            json.dumps(
                {
                    "protocol_version": 2,
                    "mode": "simulated",
                    "hardware_validated": False,
                    "note": "Byte-processing simulation, not measured RF/audio",
                }
            ).encode(),
        )
        for run in runs:
            save(f"runs/{run['id']}.json", json.dumps(run, indent=2).encode())
            save(f"runs/{run['id']}.csv", run_csv(run).encode())
            name = f"events/{run['id']}.jsonl"
            digest = hashlib.sha256()
            with archive.open(name, "w") as stream:
                for row in event_rows(records, run["id"]):
                    content = (json.dumps(row) + "\n").encode()
                    digest.update(content)
                    stream.write(content)
            hashes[name] = digest.hexdigest()
            for artifact in run["artifacts"]:
                content = (records.store.root / artifact["relative_path"]).read_bytes()
                if hashlib.sha256(content).hexdigest() != artifact["sha256"]:
                    raise ValueError("Saved artifact failed its integrity check")
                name = f"artifacts/{run['id']}/{artifact['sha256']}.bin"
                if name not in hashes:
                    save(name, content)
        archive.writestr(
            "manifest.json", json.dumps({"bundle_version": 2, "sha256": hashes}, indent=2)
        )
    return output.getvalue()
