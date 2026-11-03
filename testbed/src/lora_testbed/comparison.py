"""Configuration differences and per-run results, without pooling unlike evidence."""

from statistics import mean, stdev

METRICS = ("pdr", "throughput_bps", "rssi_dbm", "snr_db")


def flatten(value: dict, prefix: str = "") -> dict:
    result = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            result.update(flatten(item, name))
        else:
            result[name] = item
    return result


def compare(runs: list[dict]) -> dict:
    records = []
    for run in runs:
        settings = flatten(
            {
                "requested": run["spec"],
                "applied": run["applied_settings"],
                "node": {node["id"]: node for node in run["nodes"]},
            }
        )
        settings.update(
            mode=run["mode"],
            timing_basis=run["metrics"]["timing_basis"],
            host_version=run["host_version"],
        )
        records.append(settings)
    keys = sorted(set().union(*(record.keys() for record in records)))
    differences = [
        {"field": key, "values": [record.get(key) for record in records]}
        for key in keys
        if any(record.get(key) != records[0].get(key) for record in records[1:])
    ]
    warnings = []
    if any(run["status"] != "completed" for run in runs):
        warnings.append("Partial or failed runs are included; inspect their termination reasons.")
    if any(run["mode"] == "simulated" for run in runs):
        warnings.append("Simulated measurements do not establish RF or audio performance.")
    if differences:
        warnings.append(
            "Settings or provenance differ. Review differences before attributing effects."
        )
    return {
        "analysis_version": 1,
        "runs": runs,
        "differences": differences,
        "warnings": warnings,
        "aggregation": "Individual runs only; no pooled or significance estimates",
    }


def campaign_summary(campaign: dict, runs: list[dict]) -> dict:
    """Group only completed cases sharing setting and direction; expose every repetition."""
    groups = {}
    for case in campaign["cases"]:
        run = next((r for r in runs if r["id"] == case["run_id"]), None)
        if not run or run["status"] != "completed":
            continue
        key = (case["axis_value"], run["spec"]["direction"])
        groups.setdefault(key, []).append(run)
    result = []
    for (value, direction), members in groups.items():
        metrics = {}
        for metric in METRICS:
            values = [r["metrics"][metric] for r in members if r["metrics"][metric] is not None]
            metrics[metric] = {
                "n": len(values),
                "mean": mean(values) if values else None,
                "sample_sd": stdev(values) if len(values) > 1 else None,
                "min": min(values) if values else None,
                "max": max(values) if values else None,
            }
        result.append(
            {
                "axis_value": value,
                "direction": direction,
                "run_ids": [r["id"] for r in members],
                "metrics": metrics,
            }
        )
    return {
        "groups": result,
        "basis": "Unweighted per-run statistics of completed cases; not pooled packet statistics",
        "excluded_run_ids": [run["id"] for run in runs if run["status"] != "completed"],
        "notes": "Sample SD requires two runs. No confidence interval or significance claim.",
    }
