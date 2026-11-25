"""Plan fixed-reference voice comparisons with explicit operator-dependent cases."""

from itertools import product

from .voice_runs import VoiceRunRequest

GROUPS = {"VOICE-02": {"C1": "reference", "C2": "microphone"}}
EXPECTED_SAMPLES = 24000
EXPECTED_ENCODED_BYTES = 1200


def cases(request, groups):
    for group in groups:
        source = GROUPS["VOICE-02"][group]
        references = request.voice_reference_ids if source == "reference" else None
        clips = references or [None] * 3
        for (ordinal, reference), direction, repetition in product(
            enumerate(clips, start=1), request.directions, range(1, request.repetitions + 1)
        ):
            yield {
                "group": group,
                "variant": f"{source}_{ordinal}",
                "repetition": repetition,
                "driver": "voice_reference" if source == "reference" else "voice_operator",
                "role": direction,
                "direction": direction,
                "reference_id": reference,
                "sample_count": EXPECTED_SAMPLES,
                "message_bytes": EXPECTED_ENCODED_BYTES,
                "comparison_bytes": [EXPECTED_ENCODED_BYTES, 64],
            }


def request_for(case):
    return VoiceRunRequest(
        source="reference", direction=case["direction"], reference_id=case["reference_id"]
    )


def blockers(voice, case):
    if case["driver"] == "voice_operator":
        return ["The microphone cases need an attended utterance schedule"]
    if not case["reference_id"]:
        return ["Select a saved three-second reference"]
    if voice is None:
        return ["Voice preflight is unavailable"]
    estimate = voice.preflight(request_for(case))
    reasons = list(estimate["blockers"])
    if estimate["sample_count"] != EXPECTED_SAMPLES:
        reasons.append("The selected reference must contain exactly 24,000 samples")
    return reasons


def summarize(view):
    record = view["record"]
    files = view["files"]
    voice_link = view["radio"] or {}
    comparisons = view["comparisons"]

    def applied(link):
        return {
            role: {name: values[name] for name in ("radio", "link")}
            for role, values in link["applied_settings"].items()
        }

    def byte_match(link, size):
        if not link:
            return False
        checked = link.get("verification") or {}
        return (
            link["status"] == "completed"
            and checked.get("bytes_equal")
            and checked["length_bytes"] == size
            and (link.get("accounting") or {}).get("evidence_complete")
        )

    baselines = {}
    for basis, size in (("equal_encoded_bytes", EXPECTED_ENCODED_BYTES), ("standard_64_bytes", 64)):
        entry = comparisons.get(basis) or {}
        data = entry.get("run")
        baselines[basis] = {
            "expected_bytes": size,
            "radio_run_id": entry.get("radio_run_id"),
            "matched": bool(
                entry.get("message_bytes") == size
                and byte_match(data, size)
                and byte_match(voice_link, EXPECTED_ENCODED_BYTES)
                and applied(data) == applied(voice_link)
                and data["plan"]["spec"]["direction"] == voice_link["plan"]["spec"]["direction"]
            ),
        }
    metadata_complete = (
        record["status"] == "completed"
        and record["sample_count"] == EXPECTED_SAMPLES
        and view["encoded_integrity"]["verified"]
        and files["source"].get("length_bytes") == EXPECTED_SAMPLES * 2
        and files["decoded"].get("length_bytes") == EXPECTED_SAMPLES * 2
        and byte_match(voice_link, EXPECTED_ENCODED_BYTES)
        and record["playback_completed"]
        and all(x["matched"] for x in baselines.values())
    )
    return {
        "checked_transfer_and_playback": bool(metadata_complete),
        "physical_listening": record["listening"],
        "one_way_latency": view["one_way_latency"],
        "stages": view["stages"],
        "artifacts": files,
        "comparisons": baselines,
    }
