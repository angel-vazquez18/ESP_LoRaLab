"""Assess finite observed workloads without turning missing evidence into success."""

import base64
import hashlib
from typing import Literal

from pydantic import Field, model_validator

from . import memory_observation_v2 as memory
from . import source_protocol_v2 as source
from .control_v2 import UUID
from .models import StrictModel


class Delivery(StrictModel):
    message_ids: list[int] = Field(default_factory=list, max_length=20)
    reference_b64: str | None = Field(default=None, max_length=1600)
    archive_b64: str | None = Field(default=None, max_length=32000)
    archive_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def unique_ids(self):
        if len(set(self.message_ids)) != len(self.message_ids) or any(
            not 1 <= identifier <= 20 for identifier in self.message_ids
        ):
            raise ValueError("Delivered message IDs must be unique and within 1–20")
        return self


class SourceEvidence(StrictModel):
    status: source.Status
    frames: list[source.Frame] = Field(max_length=3000)
    queue_samples: list[source.Sample] = Field(max_length=451)
    execution_status: Literal["completed", "failed", "cancelled", "interrupted", "unavailable"] = (
        "completed"
    )
    telemetry_gaps: int = Field(default=0, ge=0)
    collection_errors: list[str] = Field(default_factory=list, max_length=16)
    delivery: Delivery | None = None


class MemoryEvidence(StrictModel):
    status: memory.Status
    events: list[memory.Event] = Field(max_length=12000)
    collection_errors: list[str] = Field(default_factory=list, max_length=16)


def counter_errors(s):
    errors = []
    checks = {
        "snapshot was not consistent": s.consistent,
        "terminal queue still owns payload bytes": s.phase not in (3, 4) or s.occupancy_bytes == 0,
        "partial discard exceeds one assembly": s.partial_discarded_bytes < 1200,
        "discarded message identities differ": s.discarded_message_mask.bit_count()
        == s.queue_discarded_messages
        + s.consumer_discarded_bytes // 1200
        + (1 if s.partial_discarded_bytes else 0),
        "overflow and discarded identities overlap": not (
            s.overflow_message_mask & s.discarded_message_mask
        ),
        "taken messages exceed admitted messages": s.taken_messages <= s.admitted_messages,
        "terminal admitted identities lack outcomes": s.phase not in (3, 4)
        or (
            (s.sent_message_mask | s.failed_message_mask | s.discarded_message_mask)
            & s.admitted_message_mask
            == s.admitted_message_mask
        ),
        "produced/admitted/overflow bytes differ": s.produced_bytes
        == s.admitted_bytes + s.overflow_dropped_bytes,
        "admitted byte destinations differ": s.admitted_bytes
        == s.sent_bytes
        + s.failed_bytes
        + s.consumer_discarded_bytes
        + s.queue_discarded_bytes
        + s.partial_discarded_bytes
        + s.occupancy_bytes,
        "frame/byte count differs": s.produced_bytes == 8 * s.frames_produced,
        "sent byte/message count differs": s.sent_bytes == 1200 * s.sent_messages,
        "failed byte/message count differs": s.failed_bytes == 1200 * s.failed_messages,
        "queue discard byte/message count differs": s.queue_discarded_bytes
        == 1200 * s.queue_discarded_messages,
        "consumer discard is not whole-message": s.consumer_discarded_bytes % 1200 == 0,
        "occupancy components differ": s.occupancy_bytes
        == 1200 * s.ready_messages + s.partial_bytes + s.active_bytes,
        "peak below current occupancy": s.peak_occupancy_bytes >= s.occupancy_bytes,
        "admitted message identities differ": s.admitted_messages
        == s.admitted_message_mask.bit_count(),
        "sent message identities differ": s.sent_messages == s.sent_message_mask.bit_count(),
        "failed message identities differ": s.failed_messages == s.failed_message_mask.bit_count(),
        "sent/failed identities overlap": not (s.sent_message_mask & s.failed_message_mask),
        "discarded and completed identities overlap": not (
            s.discarded_message_mask & (s.sent_message_mask | s.failed_message_mask)
        ),
        "completed identities were not admitted": not (
            (s.sent_message_mask | s.failed_message_mask) & ~s.admitted_message_mask
        ),
        "admission and overflow identities overlap": not (
            s.admitted_message_mask & s.overflow_message_mask
        ),
        "taken messages differ from consumer outcomes": s.taken_messages
        == s.sent_messages
        + s.failed_messages
        + s.consumer_discarded_bytes // 1200
        + (1 if s.active_bytes else 0),
    }
    errors.extend(reason for reason, passes in checks.items() if not passes)
    return errors


def assess_source(evidence: SourceEvidence):
    s = evidence.status
    errors = counter_errors(s)
    gaps = list(evidence.collection_errors)
    frames = evidence.frames
    if [row.index for row in frames] != list(range(s.trace_frames)):
        gaps.append("Frame trace is missing, duplicated or out of order")
    if any(
        row.planned_elapsed_us != row.index * 20000
        or row.produced != (row.actual_elapsed_us is not None)
        or (row.produced and row.actual_elapsed_us < row.planned_elapsed_us)
        for row in frames
    ):
        errors.append("Frame timing or produced flag is inconsistent")
    produced = [row for row in frames if row.produced]
    overflow = [row for row in produced if s.overflow_message_mask & (1 << (row.index // 150))]
    if not gaps and (
        len(produced) * 8 != s.produced_bytes or len(overflow) * 8 != s.overflow_dropped_bytes
    ):
        errors.append("Independent frame trace does not reconcile with byte totals")
    terminal = s.phase in (3, 4)
    if terminal and s.frames_produced + s.frames_missed + s.frames_cancelled != 3000:
        errors.append("Terminal frame outcomes do not account for all 3000 frames")
    complete_production = (
        s.frames_produced == 3000 and not s.frames_cancelled and not s.frames_missed
    )
    if complete_production and (
        (s.admitted_message_mask | s.overflow_message_mask) != (1 << 20) - 1
        or s.dropped_messages != s.overflow_message_mask.bit_count()
        or s.admitted_bytes != s.admitted_messages * 1200
        or s.overflow_dropped_bytes != s.dropped_messages * 1200
    ):
        errors.append("Whole-message admission/overflow totals do not partition the source")
    if (
        s.production_end_us - s.started_us != 60000000
        or not 0 <= s.drain_deadline_us - s.production_end_us <= 30000000
    ):
        errors.append("Source clock or drain budget differs from the selected policy")
    sample_errors = []
    samples = evidence.queue_samples
    if [row.index for row in samples] != list(range(len(samples))):
        sample_errors.append("Queue sample indices are missing, duplicated or out of order")
    previous = -200000
    for row in samples:
        if row.planned_elapsed_us != previous + 200000 or row.missed_intervals:
            sample_errors.append("Queue audit has missed intervals")
        if (
            row.actual_elapsed_us < row.planned_elapsed_us
            or row.actual_elapsed_us - row.planned_elapsed_us >= 200000
        ):
            sample_errors.append("Queue audit was delayed by at least one interval")
        if row.status.started_us != s.started_us or counter_errors(row.status):
            sample_errors.append("Queue audit has inconsistent counters or clock identity")
        previous = row.planned_elapsed_us + row.missed_intervals * 200000
    boundary = next((row for row in samples if row.planned_elapsed_us == 60000000), None)
    if boundary is None:
        sample_errors.append("Queue audit does not cover the end of production")
    if evidence.telemetry_gaps:
        gaps.append("RF telemetry loss/backpressure prevents an unqualified capacity attribution")
    late = [row for row in produced if row.actual_elapsed_us - row.planned_elapsed_us >= 20000]
    if (
        len(late) != s.late_frames
        or max((row.actual_elapsed_us - row.planned_elapsed_us for row in produced), default=0)
        != s.max_lateness_us
    ):
        errors.append("Trace lateness differs from source counters")
    intervals = {}
    for name, begin, end in (("startup", 0, 3000000), ("production", 3000000, 60000000)):
        selected = [row for row in produced if begin <= row.planned_elapsed_us < end]
        dropped = sum(bool(s.overflow_message_mask & (1 << (row.index // 150))) for row in selected)
        mask = sum(
            1 << (identifier - 1)
            for identifier in range(1, 21)
            if begin <= (identifier - 1) * 3000000 < end
        )
        complete_ids = {
            identifier
            for identifier in range(1, 21)
            if sum(row.index // 150 + 1 == identifier for row in selected) == 150
        }
        complete_mask = sum(1 << (identifier - 1) for identifier in complete_ids)
        intervals[name] = {
            "produced_complete_messages": len(complete_ids),
            "admitted_complete_messages": (s.admitted_message_mask & mask).bit_count(),
            "overflow_complete_messages": (s.overflow_message_mask & complete_mask).bit_count(),
            "eventual_sent_messages_for_cohort": (s.sent_message_mask & mask).bit_count(),
            "eventual_failed_messages_for_cohort": (s.failed_message_mask & mask).bit_count(),
            "nominal_interval_us": [begin, end],
            "end_exclusive": True,
            "produced_bytes": 8 * len(selected),
            "admitted_bytes": 8 * (len(selected) - dropped),
            "overflow_dropped_bytes": 8 * dropped,
            "actual_bytes_in_interval": 8
            * sum(begin <= row.actual_elapsed_us < end for row in produced),
            "assessment": "inconclusive" if errors or gaps else "consistent",
            "basis": "Nominal frame cohort; actual-time count is retained separately",
        }
    intervals["drain"] = {
        "nominal_interval_us": [60000000, s.drain_deadline_us - s.started_us],
        "produced_bytes": 0,
        "cutoff": s.drain_cutoff,
        "remaining_bytes": s.occupancy_bytes,
        "terminal": terminal,
        "sent_bytes_after_boundary": s.sent_bytes - boundary.status.sent_bytes
        if boundary
        else None,
        "basis": "Bounded cleanup/consumer interval; excluded from source-rate assessment",
    }
    production = intervals["production"]
    capacity_reasons = list(dict.fromkeys(errors + gaps + sample_errors))
    if not terminal or not complete_production:
        capacity_reasons.append("The prescribed finite source did not complete production")
    if late:
        capacity_reasons.append(
            "Source pacing missed nominal periods; RF-only rate inference is unavailable"
        )
    cohort_mask = ((1 << 20) - 1) ^ 1
    overflow_count = (s.overflow_message_mask & cohort_mask).bit_count()
    capacity = {
        "assessment": "inconclusive" if capacity_reasons else "consistent",
        "finding": "inconclusive"
        if capacity_reasons
        else ("unsustainable" if overflow_count else "no_overload_observed"),
        "reasons": capacity_reasons,
        "cohort_overflow_messages": overflow_count,
        "cohort_source_rate_bps": production["produced_bytes"] * 8 / 57 if not gaps else None,
        "queue_peak_reported_bytes": s.peak_occupancy_bytes,
        "queue_peak_sampled_bytes": max(
            (row.status.occupancy_bytes for row in samples), default=None
        ),
        "limit": "Finite 57-second cohort; sampled queue trajectories "
        "cannot resolve every transient",
    }
    # Whole queued messages, including the active borrow, exclude the normal partial assembly.
    first = next((row for row in samples if row.planned_elapsed_us == 3000000), None)
    capacity["whole_backlog_growth_bytes"] = (
        boundary.status.occupancy_bytes
        - boundary.status.partial_bytes
        - first.status.occupancy_bytes
        + first.status.partial_bytes
        if first and boundary
        else None
    )
    if not capacity_reasons and capacity["whole_backlog_growth_bytes"] > 1200:
        capacity["finding"] = "unsustainable"
        capacity["reasons"].append(
            "Whole-message backlog grew beyond one message at sampled boundaries"
        )
    delivery = assess_delivery(evidence.delivery, s)
    return {
        "kind": "fixed_rate_source",
        "execution_status": evidence.execution_status,
        "hardware_qualified": False,
        "accounting": {
            "status": "inconsistent" if errors else "inconclusive" if gaps else "consistent",
            "reasons": errors + gaps,
            "totals": s.model_dump(),
        },
        "intervals": intervals,
        "capacity": capacity,
        "delivery": delivery,
        "queue_audit": {
            "assessment": "inconclusive" if sample_errors else "consistent",
            "reasons": list(dict.fromkeys(sample_errors)),
            "samples": len(samples),
        },
    }


def assess_delivery(delivery, status):
    result = {
        "assessment": "unavailable",
        "reported_messages": None,
        "reported_bytes": None,
        "verified_messages": None,
        "verified_bytes": None,
        "rate_in_sender_window_bps": None,
        "clock_reason": "Receiver and sender clocks are independent; no calibrated delivery window",
        "reasons": [],
    }
    if delivery is None:
        result["reasons"].append("Receiver delivery/archive evidence was not collected")
        return result
    ids = delivery.message_ids
    result.update(reported_messages=len(ids), reported_bytes=len(ids) * 1200)
    result["cohort_reported_messages"] = sum(i >= 2 for i in ids)
    result["cohort_reported_bytes"] = 1200 * result["cohort_reported_messages"]
    if len(ids) > status.taken_messages or any(
        not status.admitted_message_mask & (1 << (i - 1)) for i in ids
    ):
        result["assessment"] = "inconsistent"
        result["reasons"].append(
            "Reported deliveries exceed consumer-taken messages or include unadmitted identities"
        )
        return result
    if (
        delivery.reference_b64 is None
        or delivery.archive_b64 is None
        or delivery.archive_sha256 is None
    ):
        result["assessment"] = "inconclusive"
        result["reasons"].append("Independent reference and archive bytes/hash are required")
        return result
    try:
        reference = base64.b64decode(delivery.reference_b64, validate=True)
        archive = base64.b64decode(delivery.archive_b64, validate=True)
        if len(reference) != 1200 or len(archive) != 24000:
            raise ValueError("Archive or reference length differs from policy")
        if hashlib.sha256(archive).hexdigest() != delivery.archive_sha256:
            raise ValueError("Archive SHA-256 differs")
        for identifier in range(1, 21):
            expected = reference if identifier in ids else bytes(1200)
            if archive[(identifier - 1) * 1200 : identifier * 1200] != expected:
                raise ValueError(
                    "Archive slot bytes differ from delivered IDs/reference or zero holes"
                )
    except ValueError as exc:
        result["assessment"] = "inconsistent"
        result["reasons"].append(str(exc))
    else:
        result.update(
            assessment="verified", verified_messages=len(ids), verified_bytes=len(ids) * 1200
        )
    return result


def assess_memory(evidence: MemoryEvidence):
    status, events = evidence.status, evidence.events
    rows = [event.data for event in events]
    reasons = list(evidence.collection_errors)
    if not rows:
        reasons.append("No memory samples were retained")
    if len({(event.device_id, event.boot_id, event.node_role) for event in events}) > 1:
        reasons.append("Memory samples span devices, boots or roles")
    if any(row.observation_id != status.observation_id for row in rows):
        reasons.append("Memory sample observation identity differs")
    if [row.sample_index for row in rows] != list(range(status.samples_taken)):
        reasons.append("Memory samples are missing, duplicated or out of order")
    if any(rows[i].taken_us < rows[i - 1].finished_us for i in range(1, len(rows))):
        reasons.append("Memory sample times overlap or move backwards")
    if any(rows[i].taken_us - rows[i - 1].finished_us >= 200000 for i in range(1, len(rows))):
        reasons.append("Memory timeline has a gap of at least two sample periods")
    if any(
        heap.largest_free_bytes > heap.free_bytes or heap.minimum_free_bytes > heap.free_bytes
        for row in rows
        for heap in (row.memory.internal, row.memory.psram)
        if heap is not None
    ):
        reasons.append("Heap free/block/boot-minimum observations disagree")
    if status.active or status.stopped_us is None:
        reasons.append("Observation is still active or has no terminal status")
    if (
        status.samples_dropped
        or status.missed_periods
        or any(row.samples_dropped or row.missed_periods for row in rows)
    ):
        reasons.append("Memory telemetry was dropped or periodic observations were missed")
    if any(row.inventory_truncated or row.overlap_detected for row in rows):
        reasons.append("Named buffer inventory was truncated or overlapped")
    if rows and (
        status.started_us is None
        or status.stopped_us is None
        or rows[0].reason != "start"
        or rows[0].taken_us < status.started_us
        or rows[-1].reason != status.stop_reason
        or rows[-1].finished_us > status.stopped_us
    ):
        reasons.append("Observation start/end samples are unavailable")

    def summarize(selected):
        def region(name):
            heaps = [getattr(row.memory, name) for row in selected]
            available = [heap for heap in heaps if heap is not None]
            return {
                "sampled_min_free_bytes": min((h.free_bytes for h in available), default=None),
                "sampled_min_largest_free_block_bytes": min(
                    (h.largest_free_bytes for h in available), default=None
                ),
                "sampled_max_known_requested_bytes": max(
                    (getattr(row.known_requested_bytes, name) for row in selected), default=None
                )
                if available
                else None,
                "boot_minimum_free_bytes": min(
                    (h.minimum_free_bytes for h in available), default=None
                ),
                "availability": "available"
                if available and len(available) == len(heaps)
                else "partial"
                if available
                else "unavailable",
            }

        return {
            "sample_count": len(selected),
            "internal": region("internal"),
            "psram": region("psram"),
        }

    summary = summarize(rows)
    if status.measurement_minimum and rows and not reasons:
        for region in ("internal", "psram"):
            if (
                getattr(status.measurement_minimum, region + "_free_bytes")
                != summary[region]["sampled_min_free_bytes"]
            ):
                reasons.append("Reported measurement minimum differs from retained sample minima")
    segments = []
    for row in rows:
        key = (row.stage, row.workload_id)
        if not segments or key != (segments[-1]["stage"], segments[-1]["workload_id"]):
            segments.append({"stage": key[0], "workload_id": key[1], "rows": []})
        segments[-1]["rows"].append(row)
    stage_results = []
    for segment in segments:
        selected = segment.pop("rows")
        stage_results.append(
            {
                **segment,
                "first_observed_us": selected[0].taken_us,
                "last_observed_us": selected[-1].finished_us,
                **summarize(selected),
            }
        )
    lifetimes, pending = {}, set()
    for row in rows:
        present = {(buffer.name, buffer.generation) for buffer in row.known_buffers}
        if not row.inventory_truncated:
            for key in pending - present:
                lifetimes[key]["first_absent_sample_us"] = row.taken_us
            pending.intersection_update(present)
        for buffer in row.known_buffers:
            key = (buffer.name, buffer.generation)
            value = lifetimes.setdefault(
                key,
                {
                    **buffer.model_dump(),
                    "first_retained_sample_us": row.taken_us,
                    "last_retained_sample_us": row.finished_us,
                    "first_absent_sample_us": None,
                    "exact_free_us": None,
                },
            )
            if value["first_absent_sample_us"] is not None:
                reasons.append("Named buffer generation reappeared after observed absence")
            if (value["region"], value["requested_bytes"], value["first_observed_us"]) != (
                buffer.region,
                buffer.requested_bytes,
                buffer.first_observed_us,
            ):
                reasons.append("Named buffer generation changed identity or size")
            value["last_retained_sample_us"] = row.finished_us
            pending.add(key)
    return {
        "kind": "stage_memory",
        "hardware_qualified": False,
        "assessment": "inconclusive" if reasons else "consistent",
        "reasons": list(dict.fromkeys(reasons)),
        "observed": summary,
        "reported_measurement_minimum": status.measurement_minimum.model_dump()
        if status.measurement_minimum
        else None,
        "reported_workload_minimum": status.workload_minimum.model_dump()
        if status.workload_minimum
        else None,
        "stages": stage_results,
        "buffer_lifetimes": list(lifetimes.values()),
        "true_peak": {
            "value": None,
            "reason": "100 ms non-atomic snapshots miss between-sample peaks; "
            "library, driver, DMA and task allocations remain untracked",
        },
        "known_buffer_scope": "Requested owned bytes only; exclude allocator overhead "
        "and never add to total heap use",
        "recovery": {
            "internal_free_delta_bytes": rows[-1].memory.internal.free_bytes
            - rows[0].memory.internal.free_bytes
            if rows
            else None,
            "basis": "Last minus first sampled free bytes; "
            "no automatic leak or recovery qualification",
        },
    }


class AssessmentRequest(StrictModel):
    source: SourceEvidence | None = None
    memory: MemoryEvidence | None = None
    parent_run_id: UUID | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if self.source is None and self.memory is None:
            raise ValueError("Source or memory evidence is required")
        return self
