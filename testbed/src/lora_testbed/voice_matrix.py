"""Plan fixed-reference and attended microphone voice comparisons."""

from itertools import product

from .voice_runs import VoiceRunRequest

GROUPS = {"VOICE-02": {"C1": "reference", "C2": "microphone"}}
EXPECTED_SAMPLES = 24000
EXPECTED_ENCODED_BYTES = 1200


def cases(request, groups):
    microphones = {
        (row.utterance, row.direction, row.repetition): row.voice_run_id
        for row in request.voice_microphone_evidence or ()
    }
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
                "driver": "voice_reference" if source == "reference" else "voice_microphone_review",
                "role": direction,
                "direction": direction,
                "reference_id": reference,
                "sample_count": EXPECTED_SAMPLES,
                "message_bytes": EXPECTED_ENCODED_BYTES,
                "comparison_bytes": [EXPECTED_ENCODED_BYTES, 64],
                **(
                    {"saved_voice_id": microphones[(ordinal, direction, repetition)]}
                    if source == "microphone" and (ordinal, direction, repetition) in microphones
                    else {}
                ),
            }


def request_for(case):
    return VoiceRunRequest(
        source="reference", direction=case["direction"], reference_id=case["reference_id"]
    )


def blockers(voice, case):
    if case["driver"] == "voice_microphone_review":
        if not (identifier := case.get("saved_voice_id")):
            return ["Attach a saved microphone-origin voice run"]
        if voice is None:
            return ["Saved voice evidence is unavailable"]
        try:
            require_microphone_record(voice.get(identifier), case)
        except ValueError as exc:
            return [str(exc)]
        return []
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

    def measurements(link):
        accounting = link["accounting"]
        return {
            "unique_original_delivery_ratio": accounting.get("unique_original_delivery_ratio"),
            "verified_delivered_bytes": accounting.get("verified_delivered_bytes"),
            "goodput_bps": accounting.get("goodput_bps"),
            "sender_transfer_window": accounting.get("sender_transfer_window"),
        }

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
                and data["session_id"] != voice_link["session_id"]
                and data["plan"]["spec"]["security"] == voice_link["plan"]["spec"]["security"]
                and data["plan"]["spec"]["direction"] == voice_link["plan"]["spec"]["direction"]
            ),
        }
        if baselines[basis]["matched"]:
            baselines[basis]["measurements"] = measurements(data)
    metadata_complete = (
        record["status"] == "completed"
        and record["sample_count"] == EXPECTED_SAMPLES
        and view["encoded_integrity"]["verified"]
        and files["source"].get("length_bytes") == EXPECTED_SAMPLES * 2
        and files["decoded"].get("length_bytes") == EXPECTED_SAMPLES * 2
        and byte_match(voice_link, EXPECTED_ENCODED_BYTES)
        and record["playback_completed"]
        and all(x["matched"] for x in baselines.values())
        and len(
            {
                voice_link["session_id"],
                *(entry["run"]["session_id"] for entry in comparisons.values()),
            }
        )
        == 3
    )
    return {
        "checked_transfer_and_playback": bool(metadata_complete),
        "physical_listening": record["listening"],
        "one_way_latency": view["one_way_latency"],
        "stages": view["stages"],
        "artifacts": files,
        "comparisons": baselines,
        "voice_link": measurements(voice_link)
        if byte_match(voice_link, EXPECTED_ENCODED_BYTES)
        else None,
    }


def require_microphone_record(record, case):
    if (
        record["status"] != "completed"
        or record["request"]["source"] != "microphone"
        or record["request"]["direction"] != case["direction"]
        or record["request"]["security"] != "aes128_gcm"
        or record["sample_count"] != EXPECTED_SAMPLES
        or not (record.get("cleanup") or {}).get("confirmed")
        or not record["jobs"].get("source_audio")
    ):
        raise ValueError("Use a complete protected microphone run in the selected direction")


def review_microphone(voice, case):
    identifier = case["saved_voice_id"]
    record = voice.get(identifier)
    require_microphone_record(record, case)
    view = voice.inspect(identifier)
    report = summarize(view)
    source, encoded = view["files"]["source"], view["files"]["encoded"]
    capture = voice.audio.get(record["jobs"]["source_audio"])
    if (
        not report["checked_transfer_and_playback"]
        or not source.get("available")
        or not view["files"]["decoded"].get("available")
        or (encoded.get("manifest") or {}).get("frame_count") != 150
        or capture["action"] != "capture"
        or capture["role"] != record["sender"]
        or capture["status"] != "completed"
        or (capture.get("clip") or {}).get("pcm_sha256") != source["sha256"]
        or capture["identity"]["boot_id"] != record["identities"][record["sender"]]["boot_id"]
    ):
        raise ValueError(
            "Capture provenance, codec bytes, playback or matched data evidence is incomplete"
        )
    voice.audio.wav(capture["id"])
    heard = record["listening"]["heard"]
    if source["pcm"]["near_silence"]:
        outcome, reason = "inconclusive", "The original microphone recording is near silence"
    elif heard == "not_heard":
        outcome, reason = "fail", "The operator heard no receiver playback"
    elif heard == "heard":
        outcome, reason = "pass", None
    else:
        outcome, reason = "inconclusive", "Record the operator listening result on the voice run"
    return {
        **report,
        "outcome": outcome,
        "reason": reason,
        "voice_run_id": identifier,
        "source_capture_id": capture["id"],
        "voice_inspection": f"/api/voice/runs/{identifier}/inspection",
        "capture_wav": f"/api/voice/runs/{identifier}/artifacts/source?as_wav=true",
        "decoded_wav": f"/api/voice/runs/{identifier}/artifacts/decoded?as_wav=true",
        "encoded_artifact": f"/api/voice/runs/{identifier}/artifacts/recovered",
        "listening": record["listening"],
        "radio_run_ids": [
            record["radio_run_id"],
            *(item["radio_run_id"] for item in report["comparisons"].values()),
        ],
    }
