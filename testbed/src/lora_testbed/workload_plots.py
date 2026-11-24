"""Bounded views select real observations; full stored evidence remains independent."""

import math

from .campaign_plans import digest
from .source_protocol_v2 import POLICY as SOURCE_POLICY
from .workload_assessment import AssessmentRequest

MEMORY_METRICS = (
    "internal_free_bytes",
    "internal_largest_free_bytes",
    "internal_boot_minimum_bytes",
    "psram_free_bytes",
    "psram_largest_free_bytes",
    "psram_boot_minimum_bytes",
    "known_internal_bytes",
    "known_psram_bytes",
    "known_unknown_bytes",
    "observation_internal_minimum_bytes",
    "observation_psram_minimum_bytes",
)
SOURCE_METRICS = (
    "occupancy_bytes",
    "produced_bytes",
    "admitted_bytes",
    "overflow_dropped_bytes",
    "sent_bytes",
    "failed_bytes",
    "consumer_discarded_bytes",
    "queue_discarded_bytes",
    "partial_discarded_bytes",
    "admitted_messages",
    "dropped_messages",
    "sent_messages",
    "failed_messages",
)
PAGE = 32


def select_actual(points, metrics, limit):
    """Keep endpoints and per-bucket extrema as actual rows, never averages."""
    if len(points) <= limit:
        return points
    buckets = max(1, (limit - 2) // (2 * len(metrics)))
    selected = {0, len(points) - 1}
    for bucket in range(buckets):
        begin = math.floor(bucket * len(points) / buckets)
        end = math.floor((bucket + 1) * len(points) / buckets)
        for metric in metrics:
            candidates = [i for i in range(begin, end) if points[i]["values"][metric] is not None]
            if candidates:
                selected.add(min(candidates, key=lambda i: points[i]["values"][metric]))
                selected.add(max(candidates, key=lambda i: points[i]["values"][metric]))
    return [points[index] for index in sorted(selected)]


def page(rows, offset):
    selected = rows[offset : offset + PAGE]
    return {
        "total": len(rows),
        "offset": offset,
        "rows": selected,
        "next_offset": offset + len(selected) if offset + len(selected) < len(rows) else None,
    }


def series(points, metrics, limit, gaps):
    selected = select_actual(points, metrics, limit)
    segments = {point["segment"] for point in points}
    shown = {point["segment"] for point in selected}
    return {
        "points": selected,
        "total_samples": len(points),
        "plotted_samples": len(selected),
        "max_points": limit,
        "downsampled": len(selected) < len(points),
        "selection": "actual endpoints and per-bucket extrema; no interpolated observations",
        "segments": len(segments),
        "displayed_segments": len(shown),
        "gap_count": len(gaps),
        "gaps": page(gaps, 0),
        "bounds_us": [min(p["elapsed_us"] for p in points), max(p["elapsed_us"] for p in points)]
        if points
        else None,
        "omitted_segments": len(segments - shown),
    }


def memory_view(raw, summary, limit, buffer_offset, stage_offset):
    rows = raw["events"]
    origin = raw["status"]["started_us"]
    clocks = {
        (row["device_id"], row["boot_id"], row["node_role"], row["data"]["observation_id"])
        for row in rows
    }
    clock_reason = None
    if len(clocks) != 1 or origin is None:
        clock_reason = "One device/boot/role/observation clock is required for a memory timeline"
    elif any(event["data"]["taken_us"] < origin for event in rows):
        clock_reason = "A memory sample precedes the declared observation start"
    points, gaps = [], []
    previous, segment = None, 0
    if clock_reason is None:
        for event in rows:
            row = event["data"]
            reasons = []
            if previous is None and (row["sample_index"] != 0 or row["reason"] != "start"):
                reasons.append("Initial memory observation rows are not retained")
            if previous is not None:
                if row["sample_index"] != previous["sample_index"] + 1:
                    reasons.append("Missing, duplicate or reordered memory sample indices")
                if row["taken_us"] < previous["finished_us"]:
                    reasons.append("Memory timestamps overlap or move backwards")
                elif row["taken_us"] - previous["finished_us"] >= 200000:
                    reasons.append("At least two memory sample periods between retained rows")
                if (
                    row["missed_periods"] > previous["missed_periods"]
                    or row["samples_dropped"] > previous["samples_dropped"]
                ):
                    reasons.append("Firmware reported missed periods or dropped observations")
            if reasons:
                segment += 1
                gaps.append(
                    {
                        "before_index": row["sample_index"],
                        "from_us": previous["taken_us"] - origin if previous else 0,
                        "to_us": row["taken_us"] - origin,
                        "reasons": reasons,
                    }
                )
            internal, psram = row["memory"]["internal"], row["memory"]["psram"]
            values = {
                "internal_free_bytes": internal["free_bytes"],
                "internal_largest_free_bytes": internal["largest_free_bytes"],
                "internal_boot_minimum_bytes": internal["minimum_free_bytes"],
                "psram_free_bytes": psram["free_bytes"] if psram else None,
                "psram_largest_free_bytes": psram["largest_free_bytes"] if psram else None,
                "psram_boot_minimum_bytes": psram["minimum_free_bytes"] if psram else None,
                **{
                    f"known_{name}_bytes": row["known_requested_bytes"][name]
                    for name in ("internal", "psram", "unknown")
                },
                "observation_internal_minimum_bytes": row["measurement_minimum"][
                    "internal_free_bytes"
                ],
                "observation_psram_minimum_bytes": row["measurement_minimum"]["psram_free_bytes"],
            }
            points.append(
                {
                    "index": row["sample_index"],
                    "elapsed_us": row["taken_us"] - origin,
                    "segment": segment,
                    "stage": row["stage"],
                    "workload_id": row["workload_id"],
                    "inventory_truncated": row["inventory_truncated"],
                    "values": values,
                }
            )
            previous = row
    if rows and rows[-1]["data"]["sample_index"] + 1 < raw["status"]["samples_taken"]:
        last = rows[-1]["data"]["taken_us"] - (origin or 0)
        gaps.append(
            {
                "before_index": raw["status"]["samples_taken"] - 1,
                "from_us": last,
                "to_us": (raw["status"]["stopped_us"] - origin)
                if origin is not None and raw["status"]["stopped_us"] is not None
                else last,
                "reasons": ["Final rows counted by the observer were not retained"],
            }
        )
    result = series(points, MEMORY_METRICS, limit, gaps)
    result.update(
        summary={
            key: value
            for key, value in summary.items()
            if key not in ("stages", "buffer_lifetimes")
        },
        stages=page(summary["stages"], stage_offset),
        buffers=page(summary["buffer_lifetimes"], buffer_offset),
        clock={
            "basis": "elapsed from declared observation start in one node boot",
            "origin_us": origin,
            "identity": list(next(iter(clocks))) if len(clocks) == 1 else None,
            "unavailable_reason": clock_reason,
        },
        retained_rows=len(rows),
        total_samples=len(rows),
    )
    return result


def source_view(raw, summary, limit):
    points, gaps = [], []
    previous, segment = None, 0
    clock_reason = None
    if any(
        row["status"]["started_us"] != raw["status"]["started_us"] for row in raw["queue_samples"]
    ):
        clock_reason = "Queue audit clocks disagree with the declared sender origin"
    for row in [] if clock_reason else raw["queue_samples"]:
        reasons = []
        if previous is None and row["index"] != 0:
            reasons.append("Initial queue audit rows are not retained")
        if previous is not None:
            if (
                row["index"] != previous["index"] + 1
                or row["planned_elapsed_us"] != previous["planned_elapsed_us"] + 200000
            ):
                reasons.append("Missing, duplicate or reordered queue audit intervals")
            if (
                row["actual_elapsed_us"] - previous["actual_elapsed_us"] >= 400000
                or row["actual_elapsed_us"] < previous["actual_elapsed_us"]
            ):
                reasons.append("Delayed or backwards queue audit timestamps")
        if row["missed_intervals"]:
            reasons.append("Producer reported missed audit intervals")
        if not row["status"]["consistent"]:
            reasons.append("Concurrent queue snapshot was inconsistent")
        if reasons:
            segment += 1
            gaps.append(
                {
                    "before_index": row["index"],
                    "from_us": previous["actual_elapsed_us"]
                    if previous
                    else row["actual_elapsed_us"],
                    "to_us": row["actual_elapsed_us"],
                    "reasons": reasons,
                }
            )
        values = {
            name: row["status"][name] if row["status"]["consistent"] else None
            for name in SOURCE_METRICS
        }
        points.append(
            {
                "index": row["index"],
                "elapsed_us": row["actual_elapsed_us"],
                "segment": segment,
                "values": values,
            }
        )
        previous = row
    return {
        **series(points, SOURCE_METRICS, limit, gaps),
        "summary": summary,
        "total_samples": len(raw["queue_samples"]),
        "policy": SOURCE_POLICY,
        "clock": {
            "basis": "actual sender elapsed time; receiver clock remains independent",
            "origin_us": raw["status"]["started_us"],
            "unavailable_reason": clock_reason,
        },
        "retained_frames": len(raw["frames"]),
    }


def projection(record, max_points=480, buffer_offset=0, stage_offset=0):
    if record["policy"] != "observed_workload_assessment_v1" or record["schema_sha256"] != digest(
        AssessmentRequest.model_json_schema()
    ):
        raise ValueError(
            "This evidence schema is unavailable for plots; full record export remains available"
        )
    evidence, assessments = record["evidence"], record["assessments"]
    return {
        "profile": "observed_workload_plot_v1",
        "record": {
            key: record[key]
            for key in (
                "id",
                "created_at",
                "origin",
                "hardware_qualified",
                "document_sha256",
                "evidence_sha256",
            )
        },
        "source": source_view(evidence["source"], assessments["source"], max_points)
        if evidence["source"]
        else None,
        "memory": memory_view(
            evidence["memory"], assessments["memory"], max_points, buffer_offset, stage_offset
        )
        if evidence["memory"]
        else None,
        "export_path": f"/api/workload-assessments/{record['id']}/export",
    }
