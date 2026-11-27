"""Persist imported traces or read-only evidence from an already owned physical node."""

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from . import memory_observation_v2 as memory
from . import run_protocol_v2
from . import source_protocol_v2 as source
from .campaign_plans import digest
from .session_keys import require_public_metadata
from .storage import utc_now
from .workload_assessment import AssessmentRequest, assess_memory, assess_source


class WorkloadObservations:
    def __init__(self, store, adapter):
        self.store, self.adapter = store, adapter
        self.collectors = set()
        self.closing = False
        store.db.execute(
            "CREATE TABLE IF NOT EXISTS workload_assessments_v1 "
            "(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL)"
        )
        store.db.commit()

    def save(self, evidence: AssessmentRequest, *, origin="imported_unverified", provenance=None):
        raw = evidence.model_dump()
        if len(json.dumps(raw).encode()) > 12 * 1024 * 1024:
            raise ValueError("Raw assessment evidence exceeds 12 MiB")
        record = {
            "id": str(uuid4()),
            "created_at": utc_now(),
            "policy": "observed_workload_assessment_v1",
            "origin": origin,
            "provenance": provenance,
            "hardware_qualified": False,
            "qualification_reason": "Evidence consistency is separate from "
            "full physical procedure qualification",
            "evidence": raw,
            "evidence_sha256": digest(raw),
            "assessments": {
                "source": assess_source(evidence.source) if evidence.source else None,
                "memory": assess_memory(evidence.memory) if evidence.memory else None,
            },
            "host_sources": {
                name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in ("workload_assessment.py", "workload_observations.py")
            },
            "schema_sha256": digest(AssessmentRequest.model_json_schema()),
        }
        record["document_sha256"] = digest(record)
        require_public_metadata(record)
        document = json.dumps(record)
        if len(document.encode()) > 16 * 1024 * 1024:
            raise ValueError("Assessment evidence exceeds 16 MiB")
        self.store.db.execute(
            "INSERT INTO workload_assessments_v1 VALUES (?,?,?)",
            (record["id"], record["created_at"], document),
        )
        self.store.db.commit()
        return record

    def get(self, identifier):
        row = self.store.db.execute(
            "SELECT document FROM workload_assessments_v1 WHERE id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown workload assessment")
        record = json.loads(row[0])
        expected = record.pop("document_sha256")
        if digest(record) != expected or digest(record["evidence"]) != record["evidence_sha256"]:
            raise ValueError("Saved workload evidence or document hash differs")
        return {**record, "document_sha256": expected}

    def list(self, limit=20):
        rows = self.store.db.execute(
            "SELECT id,created_at,json_extract(document,'$.origin') AS origin, "
            "json_extract(document,'$.document_sha256') AS document_sha256 "
            "FROM workload_assessments_v1 ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return {"assessments": [{**dict(row), "hardware_qualified": False} for row in rows]}

    @asynccontextmanager
    async def operation(self):
        if self.closing:
            raise ValueError("Host is shutting down")
        task = asyncio.current_task()
        self.collectors.add(task)
        try:
            yield
        finally:
            self.collectors.discard(task)

    async def close(self):
        self.closing = True
        tasks = list(self.collectors)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def start_memory(self, role, duration_ms):
        async with self.operation():
            return await self._start_memory(role, duration_ms)

    async def collect_memory(self, role, observation_id, stop=False):
        async with self.operation():
            return await self._collect_memory(role, observation_id, stop)

    async def collect_source(self, role, run_id, *, parent_radio=None):
        async with self.operation():
            return await self._collect_source(role, run_id, parent_radio)

    async def _start_memory(self, role, duration_ms):
        binding = self.adapter.bind(role)
        current = await self.adapter.request(binding, "memory.status")
        if current["active"]:
            raise ValueError("A memory observation is already active")
        # Observation runs alongside the existing bench workload, with its own finite deadline.
        started = await self.adapter.request(binding, "memory.start", {"duration_ms": duration_ms})
        return {**started, "binding": binding, "qualification": "unassessed"}

    async def _collect_memory(self, role, observation_id, stop=False):
        binding = self.adapter.bind(role)
        current = memory.Status.model_validate(await self.adapter.request(binding, "memory.status"))
        if current.observation_id != observation_id:
            raise ValueError("The current observation ID differs; no other observer was stopped")
        if stop and current.active:
            await self.adapter.request(binding, "memory.stop", {"observation_id": observation_id})
        # Final memory.stop events precede its reply and are already in the store.
        status = memory.Status.model_validate(await self.adapter.request(binding, "memory.status"))
        if status.observation_id != observation_id:
            raise ValueError("Observation changed during readback")
        events = self.store.memory_observation_records(role, observation_id)
        self.adapter.current(binding)
        errors = []
        if any(
            (event["device_id"], event["boot_id"], event["node_role"])
            != (binding["device_id"], binding["boot_id"], binding["role"])
            for event in events
        ):
            errors.append("Saved memory events do not match the current physical binding")
        return self.save(
            AssessmentRequest(
                memory={"status": status, "events": events, "collection_errors": errors}
            ),
            origin="physical_readback",
            provenance={
                "binding": binding,
                "observer_profile": memory.PROFILE,
                "observer_schema_sha256": memory.schema_digest(),
            },
        )

    async def _collect_source(self, role, run_id, parent_radio):
        binding = parent_radio["binding"] if parent_radio else self.adapter.bind(role)
        if binding["role"] != role:
            raise ValueError("Source role does not match the parent run's binding")
        node = self.adapter.current(binding)
        if node.rf_run_id != run_id:
            raise ValueError("Source readback requires the currently owned RF session")
        reports = []

        async def query(view="status", offset=0, limit=1):
            report = source.Report.model_validate(
                await self.adapter.request(
                    binding,
                    "run.source",
                    {"view": view, "offset": offset, "limit": limit},
                    run_id=run_id,
                    timeout=1,
                    retries=0,
                )
            )
            if report.view != view or report.offset != offset:
                raise ValueError("Source page identity differs from the request")
            reports.append(report.model_dump())
            return report

        initial = await query()
        if initial.status is None or initial.status.phase not in (3, 4):
            raise ValueError("Read source evidence from the terminal sender before session.close")
        frames, samples, errors = [], [], []
        cancelled = False
        try:
            async with asyncio.timeout(45):
                for view, target, limit, maximum in (
                    ("frames", frames, 16, 3000),
                    ("samples", samples, 1, 451),
                ):
                    offset = 0
                    for _ in range(maximum // limit + 2):
                        page = await query(view, offset, limit)
                        if page.status != initial.status:
                            raise ValueError("Terminal source status changed during readback")
                        rows = getattr(page, view)
                        if page.next_offset != offset + len(rows) or page.next_offset > maximum:
                            raise ValueError("Source pagination skipped evidence")
                        target.extend(row.model_dump() for row in rows)
                        if page.eof:
                            break
                        if not rows:
                            raise ValueError("Source pagination did not advance")
                        offset = page.next_offset
                    else:
                        raise ValueError("Source pagination exceeded its bound")
                final = await query()
                if final.status != initial.status:
                    raise ValueError("Terminal source changed after pagination")
        except asyncio.CancelledError:
            cancelled = True
            errors.append("Source readback was cancelled; retained pages are partial")
        except (OSError, ValueError, TimeoutError) as exc:
            errors.append(str(exc))
        gaps = node.event_gaps + getattr(getattr(node, "health", None), "telemetry_drops", 0)
        gap_scope = "Observed connection gaps plus latest boot-wide reported drops"
        if parent_radio:
            baseline = parent_radio["baseline"]
            gaps = max(0, gaps - (baseline["event_gaps"] + baseline["telemetry_drops"]))
            gap_scope = "Bound sender gaps and reported drops since parent RF preflight"
        evidence = AssessmentRequest(
            parent_run_id=run_id,
            source={
                "status": initial.status,
                "frames": frames,
                "queue_samples": samples,
                "execution_status": "completed"
                if parent_radio and not cancelled
                else "unavailable",
                "telemetry_gaps": gaps,
                "collection_errors": errors,
                "delivery": parent_radio["delivery"] if parent_radio else None,
            },
        )
        record = self.save(
            evidence,
            origin="physical_readback",
            provenance={
                "binding": binding,
                "run_id": run_id,
                "source_policy": source.POLICY,
                "execution_profile": run_protocol_v2.EXECUTION_PROFILE,
                "execution_schema_sha256": run_protocol_v2.schema_digest(),
                "gap_scope": gap_scope,
                "raw_reports": reports,
                "execution_status_basis": "Both RF terminal summaries confirmed"
                if parent_radio
                else "Parent RF outcome was not collected",
                "delivery": parent_radio["receiver_provenance"]
                if parent_radio
                else "No receiver archive was collected",
            },
        )
        if cancelled:
            raise asyncio.CancelledError()
        return record
