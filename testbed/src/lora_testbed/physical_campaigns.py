"""Execute immutable physical plans through existing bench-owned child runners."""

import asyncio
import hashlib
import json
from collections import Counter
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from uuid import uuid4

from .campaign_plans import digest
from .campaign_views import execution_header
from .session_keys import require_public_metadata
from .storage import utc_now


@dataclass
class Child:
    service: str
    identifier: str
    task: asyncio.Task | None
    stop: Callable[[], Awaitable[object]]


class CampaignStopped(Exception):
    pass


TERMINAL = {"completed", "blocked", "failed", "cancelled", "interrupted"}


class PhysicalCampaigns:
    def __init__(self, host):
        self.host, self.store = host, host.store
        self.current = self.task = None
        self.wake = asyncio.Event()
        self.owner = object()  # Only internal dispatch can bypass the campaign's own reservation.
        self.store.db.executescript("""
            CREATE TABLE IF NOT EXISTS physical_campaign_executions_v1 (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS physical_campaign_cases_v1 (
                execution_id TEXT NOT NULL, case_id TEXT NOT NULL, position INTEGER NOT NULL,
                document TEXT NOT NULL, PRIMARY KEY(execution_id,case_id));
        """)
        self.interrupt_saved()

    def interrupt_saved(self):
        rows = self.store.db.execute(
            "SELECT document FROM physical_campaign_executions_v1"
        ).fetchall()
        for row in rows:
            record = json.loads(row[0])
            if record["status"] in TERMINAL:
                continue
            cases = self.get(record["id"])["cases"]
            record.update(
                status="interrupted",
                stage="finished",
                pending_outcome=None,
                reason="Host restarted; no automatic resume",
                reason_code="host_restart",
                active_case_id=None,
                finished_at=utc_now(),
                assessment="inconclusive",
                cleanup={
                    "confirmed": False,
                    "reason": "Previous physical cleanup is unconfirmed",
                    "nodes": {},
                },
            )
            with self.store.db:
                for case in cases:
                    if case["status"] in ("pending", "running"):
                        case.update(
                            status="skipped" if case["status"] == "pending" else "interrupted",
                            reason_code="host_restart",
                            reason=record["reason"],
                            finished_at=utc_now(),
                        )
                    self.save(record, case, commit=False)
                record["case_counts"] = dict(Counter(case["status"] for case in cases))
                self.save(record, commit=False)

    @property
    def busy(self):
        return self.current is not None

    def save(self, record, case=None, *, commit=True):
        require_public_metadata(record)
        record["updated_at"] = utc_now()
        record.pop("document_sha256", None)
        record["document_sha256"] = digest(record)
        self.store.db.execute(
            "INSERT INTO physical_campaign_executions_v1 VALUES (?,?,?) ON CONFLICT(id) "
            "DO UPDATE SET document=excluded.document",
            (record["id"], record["created_at"], json.dumps(record)),
        )
        if case is not None:
            require_public_metadata(case)
            case.pop("document_sha256", None)
            case["document_sha256"] = digest(case)
            self.store.db.execute(
                "INSERT INTO physical_campaign_cases_v1 VALUES (?,?,?,?) "
                "ON CONFLICT(execution_id,case_id) DO UPDATE SET document=excluded.document",
                (record["id"], case["case_id"], case["index"], json.dumps(case)),
            )
        if commit:
            self.store.db.commit()

    def get(self, identifier):
        row = self.store.db.execute(
            "SELECT document FROM physical_campaign_executions_v1 WHERE id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown physical campaign execution")
        record = json.loads(row[0])
        self.verify_document(record)
        record["cases"] = [
            json.loads(row[0])
            for row in self.store.db.execute(
                "SELECT document FROM physical_campaign_cases_v1 "
                "WHERE execution_id=? ORDER BY position",
                (identifier,),
            )
        ]
        for case in record["cases"]:
            self.verify_document(case)
        if len(record["cases"]) != record["case_count"]:
            raise ValueError("Saved campaign case count differs")
        return record

    @staticmethod
    def verify_document(document):
        expected = document.get("document_sha256")
        if (
            expected
            and digest({k: v for k, v in document.items() if k != "document_sha256"}) != expected
        ):
            raise ValueError("Saved campaign document hash differs")

    async def rerun(self, identifier, case_ids):
        parent = self.get(identifier)
        if parent["status"] not in TERMINAL:
            raise RuntimeError("Finish or interrupt the original campaign before rerunning cases")
        if not case_ids or len(set(case_ids)) != len(case_ids):
            raise ValueError("Select one or more distinct case IDs")
        if set(case_ids) - {case["case_id"] for case in parent["cases"]}:
            raise ValueError("A selected case does not belong to the original execution")
        return await self.start(parent["plan_id"], _parent=parent, _case_ids=set(case_ids))

    def snapshot(self):
        rows = self.store.db.execute(
            "SELECT id,created_at,json_extract(document,'$.status') AS status, "
            "json_extract(document,'$.plan_id') AS plan_id "
            "FROM physical_campaign_executions_v1 ORDER BY created_at DESC LIMIT 20"
        )
        return {
            "execution_available": True,
            "active": deepcopy(execution_header(self.current)),
            "executions": [dict(row) for row in rows],
        }

    async def start(self, plan_id, *, _parent=None, _case_ids=None):
        if self.host.busy:
            raise RuntimeError("Another run or campaign owns the bench")
        plan = self.host.campaign_plans.get(plan_id)
        selected_cases = [
            case for case in plan["cases"] if _case_ids is None or case["id"] in _case_ids
        ]
        if not selected_cases or (_case_ids is not None and len(selected_cases) != len(_case_ids)):
            raise ValueError("Selected cases are unavailable in the original saved plan")
        if _parent and _parent["plan_sha256"] != plan["plan_sha256"]:
            raise ValueError("The original execution and saved plan hashes differ")
        identifier = str(uuid4())
        bindings = {
            role: self.host.adapter.bind(role)
            for role in {r for case in selected_cases for r in case["roles"]}
            if self.host.physical[role].connected
        }
        record = {
            "id": identifier,
            "created_at": utc_now(),
            "finished_at": None,
            "plan_id": plan_id,
            "name": plan["name"],
            "plan_sha256": plan["plan_sha256"],
            "parent_execution_id": _parent["id"] if _parent else None,
            "parent_snapshot_sha256": digest(_parent) if _parent else None,
            "selected_case_ids": [case["id"] for case in selected_cases],
            "status": "running",
            "stage": "queued",
            "active_case_id": None,
            "mode": "hardware",
            "pause_requested": False,
            "cancel_requested": False,
            "cancel_reason_code": None,
            "pause_count": 0,
            "resume_count": 0,
            "hardware_qualified": False,
            "assessment": "not_assessed",
            "physical_bindings": bindings,
            "case_count": len(selected_cases),
            "case_counts": {"pending": len(selected_cases)},
            "reason": None,
            "policy": "physical_campaign_execution_v1",
            "host_sources": {
                name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in (
                    "physical_campaigns.py",
                    "campaign_plans.py",
                    "host.py",
                    "physical_adapter.py",
                    "nodes.py",
                    "diagnostic_jobs.py",
                    "procedure_runs.py",
                    "radio_runs.py",
                    "voice_runs.py",
                    "node_audio.py",
                )
            },
        }
        runtime = [
            {
                "case_id": case["id"],
                "index": index,
                "saved_index": case["index"],
                "parent_execution_id": _parent["id"] if _parent else None,
                "status": "pending",
                "reason_code": None,
                "reason": None,
                "child": None,
                "started_at": None,
                "finished_at": None,
            }
            for index, case in enumerate(selected_cases)
        ]
        batch_ids = {
            case_id: batch["id"] for batch in plan["batches"] for case_id in batch["case_ids"]
        }
        with self.store.db:
            for selected, case in zip(selected_cases, runtime, strict=True):
                case.update(
                    batch_id=batch_ids[case["case_id"]],
                    label=selected["label"],
                    direction=selected["direction"],
                    repetition=selected["repetition"],
                    canonical_index=selected["canonical_index"],
                )
                self.save(record, case, commit=False)
        self.current = record
        self.task = asyncio.create_task(
            self.run(record, {**plan, "cases": selected_cases}, runtime)
        )
        return self.get(identifier)

    def transition(self, record, runtime, case, status, reason_code=None, reason=None):
        case.update(status=status, reason_code=reason_code, reason=reason)
        if status == "running":
            case["started_at"] = utc_now()
        else:
            case["finished_at"] = utc_now()
        record["case_counts"] = dict(Counter(row["status"] for row in runtime))
        self.save(record, case)

    def child_service(self, name):
        return {
            "diagnostic": self.host.diagnostics,
            "procedure": self.host.procedures,
            "audio": self.host.audio,
            "radio": self.host.radio,
            "voice": self.host.voice,
        }[name]

    async def launch(self, spec, reserved):
        kind = spec["kind"]
        if kind in ("memory_probe", "crypto_benchmark"):

            def callback(identifier):
                reserved("diagnostic", identifier)

            if kind == "memory_probe":
                accepted = await self.host.memory_probe(
                    spec["role"],
                    spec["iterations"],
                    spec["payload_bytes"],
                    _owner=self.owner,
                    _on_created=callback,
                )
            else:
                accepted = await self.host.crypto_benchmark(
                    spec["role"], **spec["request"], _owner=self.owner, _on_created=callback
                )
            return Child(
                "diagnostic",
                accepted["host_run_id"],
                self.host.diagnostics.task,
                lambda: self.host.diagnostics.stop(accepted["operation_id"]),
            )
        if kind == "serial_check":
            from .serial_validation import SerialValidationRequest

            result = await self.host.start_serial(
                SerialValidationRequest(roles=[spec["role"]], cycles=spec["cycles"]),
                _owner=self.owner,
            )
            return Child(
                "procedure", result["id"], self.host.procedures.task, self.host.procedures.stop
            )
        if kind == "audio":
            options = (
                {"artifact_id": spec["artifact_id"]}
                if spec["artifact_id"]
                else {"sample_count": spec["sample_count"], "wait_for_ptt": spec["wait_for_ptt"]}
            )
            result = await self.host.audio_action(
                spec["role"], spec["action"], **options, _owner=self.owner
            )
            return Child(
                "audio",
                result["id"],
                self.host.audio.task,
                lambda: self.host.audio.stop(result["id"]),
            )
        if kind == "known_data":
            from .radio_runs import RadioRunRequest

            result = await self.host.start_radio(
                RadioRunRequest.model_validate(spec["request"]), _owner=self.owner
            )
            return Child(
                "radio",
                result["id"],
                self.host.radio.task,
                lambda: self.host.radio.stop(result["id"]),
            )
        if kind == "voice":
            from .voice_runs import VoiceRunRequest

            result = await self.host.start_voice(
                VoiceRunRequest.model_validate(spec["request"]), _owner=self.owner
            )
            return Child(
                "voice",
                result["id"],
                self.host.voice.task,
                lambda: self.host.voice.stop(result["id"]),
            )
        raise ValueError("Full procedure matrix execution is unavailable")

    def record_child(self, record, runtime, case):
        result = self.child_service(case["child"]["service"]).get(case["child"]["id"])
        case["cleanup"] = result.get("cleanup_details") or result.get("cleanup")
        case["child_assessment"] = result.get("assessment")
        status = result["status"] if result["status"] in TERMINAL else "failed"
        reason = result.get("error") or result.get("reason")
        if result["status"] not in TERMINAL:
            reason = "Child runner did not preserve a terminal execution outcome"
        self.transition(record, runtime, case, status, reason=reason)
        return result

    async def wait_child(self, record, task, stop, deadline):
        timed_out = False
        while task and not task.done():
            self.wake.clear()
            if record["cancel_requested"] or monotonic() >= deadline:
                timed_out = not record["cancel_requested"]
                try:
                    await stop()
                except ValueError:
                    if not task.done():
                        raise
                break
            wake = asyncio.create_task(self.wake.wait())
            try:
                await asyncio.wait(
                    {task, wake},
                    timeout=max(0, deadline - monotonic()),
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                wake.cancel()
                await asyncio.gather(wake, return_exceptions=True)
        if task:
            await asyncio.shield(task)
        return timed_out

    async def cleanup(self, record):
        nodes = {}
        for role, binding in record["physical_bindings"].items():
            try:
                nodes[role] = await self.host.adapter.cleanup(
                    binding,
                    on_record=lambda row, role=role: self.store.append_node_event(role, row),
                )
            except Exception as exc:
                nodes[role] = {"confirmed": False, "error": str(exc) or type(exc).__name__}
                try:
                    await self.host.adapter.current(binding).close(release=False)
                except (ValueError, OSError) as retirement:
                    nodes[role]["retirement_error"] = str(retirement)
        record["cleanup"] = {
            "confirmed": all(item["confirmed"] for item in nodes.values()),
            "nodes": nodes,
        }

    async def stop_reference(self, reference):
        service = self.child_service(reference["service"])
        task = service.task
        if task and not task.done():
            if reference["service"] in ("diagnostic", "procedure"):
                await service.stop()
            else:
                await service.stop(reference["id"])
            await asyncio.shield(task)

    async def run(self, record, plan, runtime):
        current_case = None
        try:
            for selected, case in zip(plan["cases"], runtime, strict=True):
                current_case = case
                if record["cancel_requested"]:
                    raise CampaignStopped
                if record["pause_requested"]:
                    record.update(status="paused", stage="paused")
                    self.save(record)
                    while record["pause_requested"] and not record["cancel_requested"]:
                        self.wake.clear()
                        await self.wake.wait()
                    if record["cancel_requested"]:
                        raise CampaignStopped
                    record["status"] = "running"
                    self.save(record)
                for role in selected["roles"]:
                    if role in record["physical_bindings"]:
                        self.host.adapter.current(record["physical_bindings"][role])
                readiness = self.host.campaign_case_preflight(selected)
                case["preflight"] = readiness
                if not readiness["ready"]:
                    self.transition(
                        record,
                        runtime,
                        case,
                        "blocked",
                        "capability_unavailable",
                        "; ".join(readiness["blockers"]) or "Campaign child runner unavailable",
                    )
                    await asyncio.sleep(
                        0
                    )  # Cancellation remains responsive for long blocked plans.
                    continue
                record.update(active_case_id=case["case_id"], stage="child")
                self.transition(record, runtime, case, "running")
                deadline = monotonic() + selected["duration_bound_s"]
                spec = selected["case"]

                def reserved(service, identifier, case=case):
                    case["child"] = {"service": service, "id": identifier}
                    self.save(record, case)

                child = await self.launch(spec, reserved)
                reserved(child.service, child.identifier)
                timed_out = await self.wait_child(record, child.task, child.stop, deadline)
                result = self.record_child(record, runtime, case)
                record["active_case_id"] = None
                if record["cancel_requested"]:
                    raise CampaignStopped
                if timed_out or result["status"] != "completed":
                    record.update(
                        status="interrupted" if result["status"] == "interrupted" else "failed",
                        reason="Child case deadline exceeded"
                        if timed_out
                        else "A child run did not complete",
                        reason_code="case_timeout" if timed_out else "child_failed",
                    )
                    break
            else:
                record["status"] = (
                    "blocked"
                    if any(case["status"] == "blocked" for case in runtime)
                    else "completed"
                )
        except CampaignStopped:
            record["status"] = (
                "interrupted" if record["cancel_reason_code"] == "host_shutdown" else "cancelled"
            )
        except asyncio.CancelledError:
            record.update(
                status="interrupted",
                reason="Campaign worker interrupted",
                reason_code="worker_interrupted",
            )
        except Exception as exc:
            changed = False
            for binding in record["physical_bindings"].values():
                try:
                    self.host.adapter.current(binding)
                except ValueError:
                    changed = True
            record.update(
                status="interrupted" if changed else "failed",
                reason=str(exc) or type(exc).__name__,
                reason_code="node_changed" if changed else "child_start_failed",
            )
        finally:
            try:
                await self.finish(record, runtime, current_case)
            finally:
                self.current = self.task = None

    async def finish(self, record, runtime, current_case):
        outcome = record["status"]
        record.update(status="running", stage="cleanup", pending_outcome=outcome)
        self.save(record)
        if current_case and current_case["child"]:
            try:
                await self.stop_reference(current_case["child"])
            except Exception as exc:
                record["child_cleanup_error"] = str(exc) or type(exc).__name__
                if outcome == "completed":
                    outcome = "failed"
                    record.update(
                        reason="Child cleanup did not finish",
                        reason_code="child_cleanup_failed",
                    )
        if current_case and current_case["status"] == "running" and current_case["child"]:
            self.record_child(record, runtime, current_case)
        code = record.get("reason_code") or record["cancel_reason_code"] or "parent_ended"
        for case in runtime:
            if case["status"] in ("pending", "running"):
                self.transition(
                    record,
                    runtime,
                    case,
                    "skipped" if case["status"] == "pending" else outcome,
                    code,
                    record["reason"],
                )
        await self.cleanup(record)
        if not record["cleanup"]["confirmed"] and outcome in ("completed", "blocked"):
            outcome = "failed"
            record.update(
                reason="Campaign cleanup could not confirm idle",
                reason_code="cleanup_unconfirmed",
            )
        record.update(
            status=outcome,
            pending_outcome=None,
            finished_at=utc_now(),
            active_case_id=None,
            assessment="not_assessed",
            stage="finished",
        )
        self.save(record)

    def active(self, identifier):
        if not self.current or self.current["id"] != identifier:
            raise ValueError("This campaign execution is not active")
        return self.current

    def pause(self, identifier):
        record = self.active(identifier)
        if (
            record["cancel_requested"]
            or record["status"] in TERMINAL
            or record["stage"] == "cleanup"
        ):
            raise ValueError("Campaign is already cancelling or completing cleanup")
        if not record["pause_requested"]:
            record.update(
                pause_requested=True,
                status="pause_requested",
                pause_count=record["pause_count"] + 1,
            )
            self.save(record)
        return self.get(identifier)

    def resume(self, identifier):
        record = self.active(identifier)
        if record["cancel_requested"] or not record["pause_requested"]:
            raise ValueError("Campaign has no resumable pause")
        for binding in record["physical_bindings"].values():
            self.host.adapter.current(binding)
        record.update(
            pause_requested=False, status="running", resume_count=record["resume_count"] + 1
        )
        self.save(record)
        self.wake.set()
        return self.get(identifier)

    async def cancel(self, identifier, reason="Stopped by operator", code="operator_cancel"):
        if not self.current or self.current["id"] != identifier:
            record = self.get(identifier)
            if record["status"] in TERMINAL:
                return record
            raise ValueError("This campaign execution is not active")
        record, task = self.current, self.task
        if (
            not record["cancel_requested"]
            and record["status"] not in TERMINAL
            and record["stage"] != "cleanup"
        ):
            record.update(
                cancel_requested=True,
                cancel_reason_code=code,
                reason_code=code,
                reason=reason,
                status="cancelling",
            )
            self.save(record)
        self.wake.set()
        if task:
            await asyncio.shield(task)
        return self.get(identifier)

    async def close(self):
        if self.current:
            await self.cancel(self.current["id"], "Host shutdown", "host_shutdown")
