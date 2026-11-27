"""Capture evidence from the live dashboard during an owned IF-03 C5 trial."""

from collections import defaultdict
from itertools import pairwise
from typing import Literal

from .control_v2 import UUID
from .models import StrictModel
from .storage import utc_now

MAX_OBSERVATIONS = 32


class Observation(StrictModel):
    tab_id: UUID
    document_id: UUID
    view: Literal["bench", "experiments", "campaigns", "voice", "results"]
    navigation_type: Literal["navigate", "reload", "back_forward", "unknown"]


def active_case(host):
    execution = host.physical_campaigns.current
    procedure = host.procedures.current
    if (
        not execution
        or execution["status"] != "running"
        or not execution["active_case_id"]
        or not procedure
        or procedure["catalog_id"] != "IF-03"
        or execution["enclosing_procedure_id"] != procedure["id"]
        or not host.radio.current
    ):
        return None
    active = next(
        (case for case in procedure["cases"] if case["id"] == procedure["active_case"]), None
    )
    if active and active["group"] == "C5" and execution["id"] in active.get("campaign_ids", ()):
        return execution, procedure, active
    return None


def observations(ledger, run_id, case_id):
    return [
        row["document"]["campaign_browser_view"]
        for row in ledger.evidence(run_id, limit=MAX_OBSERVATIONS + 4, case_id=case_id)
        if "campaign_browser_view" in row["document"]
    ]


def record(host, identifier, request):
    target = active_case(host)
    if not target or target[0]["id"] != identifier:
        raise ValueError("This campaign is not accepting dashboard observations")
    execution, procedure, case = target
    recent = observations(host.procedures, procedure["id"], case["id"])
    previous = next((row for row in reversed(recent) if row["tab_id"] == request.tab_id), None)
    if previous and (previous["document_id"], previous["view"]) == (
        request.document_id,
        request.view,
    ):
        return {"recorded": False, "reason": "unchanged view"}
    if len(recent) >= MAX_OBSERVATIONS:
        return {"recorded": False, "reason": "observation limit reached"}
    event = {
        **request.model_dump(),
        "observed_at": utc_now(),
        "campaign_id": execution["id"],
        "plan_sha256": execution["plan_sha256"],
        "host_instance_id": execution["host_instance_id"],
        "campaign_case_id": execution["active_case_id"],
        "radio_run_id": host.radio.current["id"],
    }
    host.procedures.append(procedure["id"], case["id"], {"campaign_browser_view": event})
    return {"recorded": True, "campaign_id": execution["id"]}


def assess(execution, recorded):
    result = {
        "observations": len(recorded),
        "refresh": False,
        "navigation": False,
        "verified_in_same_tab": False,
    }
    observed = defaultdict(list)
    trials = {
        case["case_id"]: (case["index"], case["child"]["id"])
        for case in execution["cases"]
        if case["child"] and case["child"]["service"] == "radio"
    }
    for event in recorded:
        trial = trials.get(event["campaign_case_id"])
        if (
            not trial
            or trial[1] != event["radio_run_id"]
            or (event["campaign_id"], event["plan_sha256"], event["host_instance_id"])
            != (execution["id"], execution["plan_sha256"], execution["host_instance_id"])
        ):
            return result
        observed[event["tab_id"]].append(event | {"index": trial[0]})
    for visits in observed.values():
        if any(b["index"] < a["index"] for a, b in pairwise(visits)):
            continue
        campaign_views = [event for event in visits if event["view"] == "campaigns"]
        refresh = any(
            a["document_id"] != b["document_id"] and b["navigation_type"] == "reload"
            for a, b in pairwise(campaign_views)
        )
        navigation = any(
            a["document_id"] == b["document_id"] == c["document_id"]
            and a["view"] == c["view"] == "campaigns"
            and b["view"] != "campaigns"
            for a, b, c in zip(visits, visits[1:], visits[2:], strict=False)
        )
        if refresh and navigation:
            return result | {"refresh": True, "navigation": True, "verified_in_same_tab": True}
        result["refresh"] |= refresh
        result["navigation"] |= navigation
    return result
