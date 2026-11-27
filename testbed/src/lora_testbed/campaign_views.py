"""Bounded read-only dashboard views; lifecycle remains in the campaign owner."""

PAGE = 32
HEADER = (
    "id",
    "plan_id",
    "name",
    "created_at",
    "updated_at",
    "finished_at",
    "status",
    "stage",
    "active_case_id",
    "case_count",
    "case_counts",
    "parent_execution_id",
    "plan_sha256",
    "pause_requested",
    "cancel_requested",
    "pause_count",
    "resume_count",
    "pending_outcome",
    "reason",
    "reason_code",
    "assessment",
    "hardware_qualified",
    "cleanup",
    "physical_bindings",
    "document_sha256",
)


def execution_header(record):
    return {key: record.get(key) for key in HEADER} if record else None


def plan_header(record):
    return {
        key: record[key]
        for key in (
            "id",
            "name",
            "created_at",
            "case_count",
            "batch_count",
            "duration_bound_s",
            "plan_sha256",
        )
    }


def page(rows, offset):
    selected = rows[offset : offset + PAGE]
    return {
        "rows": selected,
        "offset": offset,
        "total": len(rows),
        "next_offset": offset + len(selected) if offset + len(selected) < len(rows) else None,
    }


def plan_view(host, identifier, offset):
    record = host.campaign_plans.get(identifier)
    selected = page(record["cases"], offset)
    for row in selected["rows"]:
        try:
            row["readiness"] = host.campaign_case_preflight(row)
        except (ValueError, OSError) as exc:
            row["readiness"] = {"ready": False, "blockers": [str(exc)]}
    return {
        "profile": "physical_campaign_view_v1",
        "record": plan_header(record),
        "cases": selected,
        "readiness_scope": "Current page only; execution repeats all checks",
    }


def execution_view(host, identifier, offset):
    record = host.physical_campaigns.get(identifier)
    plan = host.campaign_plans.get(record["plan_id"])
    if record["plan_sha256"] != plan["plan_sha256"]:
        raise ValueError("Campaign and saved plan hashes differ")
    intent = {case["id"]: case for case in plan["cases"]}
    selected = page(record["cases"], offset)
    selected["rows"] = [{**case, "intent": intent[case["case_id"]]} for case in selected["rows"]]
    return {
        "profile": "physical_campaign_view_v1",
        "record": execution_header(record),
        "plan": plan_header(plan),
        "cases": selected,
        "active_case": next(
            (case for case in record["cases"] if case["case_id"] == record["active_case_id"]), None
        ),
    }
