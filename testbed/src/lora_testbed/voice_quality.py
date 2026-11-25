"""Pair listening ratings and node-local stages with saved verified voice clips."""

import hashlib
from collections import Counter
from collections.abc import Callable

from pydantic import Field, model_validator

from .control_v2 import UUID
from .experiments_v2 import SHA256
from .models import StrictModel
from .v2 import Identifier


class Rating(StrictModel):
    listener_id: Identifier
    clip_code: str = Field(pattern=r"^[a-f0-9]{16}$")
    audio_sha256: SHA256
    score: int = Field(ge=1, le=5)
    notes: str = Field(default="", max_length=1000)


class Review(StrictModel):
    run_ids: list[UUID] = Field(min_length=1, max_length=36)
    seed: int = Field(default=743, ge=0, le=2**32 - 1)
    ratings: list[Rating] = Field(default_factory=list, max_length=216)

    @model_validator(mode="after")
    def unique_selection(self):
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("Choose distinct voice runs")
        if len({(r.listener_id, r.clip_code) for r in self.ratings}) != len(self.ratings):
            raise ValueError("Provide one rating per listener and clip")
        return self


def review(request: Review, inspect: Callable[[str], dict]):
    clips, runs, exclusions = {}, [], []
    for identifier in request.run_ids:
        view = inspect(identifier)
        record = view["record"]
        files = view["files"]
        if (
            record["status"] != "completed"
            or not view["encoded_integrity"]["verified"]
            or not all(files[kind]["available"] for kind in ("source", "decoded"))
        ):
            exclusions.append({"run_id": identifier, "reason": "Voice or PCM evidence incomplete"})
            continue
        entry = {
            "run_id": identifier,
            "source": record["request"]["source"],
            "direction": record["request"]["direction"],
            "radio_and_link": {
                "radio": record["request"]["radio"],
                "link": record["request"]["link"],
            },
            "named_stage_timing": [
                {"stage": stage["name"], "status": stage["status"], **stage["timing"]}
                for stage in view["stages"]
            ],
            "one_way_latency": view["one_way_latency"],
            "playback_command_completed": record["playback_completed"],
            "bench_listening": record["listening"],
            "ratings": {},
        }
        for kind in ("source", "decoded"):
            code = hashlib.sha256(f"{request.seed}:{identifier}:{kind}".encode()).hexdigest()[:16]
            if code in clips:
                raise ValueError("Clip code collision; choose a different order seed")
            clips[code] = {
                "code": code,
                "run_id": identifier,
                "kind": kind,
                "sha256": files[kind]["sha256"],
                "waveform": (files[kind].get("pcm") or {}).get("peaks"),
                "wav": f"/api/voice/runs/{identifier}/artifacts/{kind}?as_wav=true",
            }
            entry["ratings"][kind] = {"clip_code": code, "ratings": [], "score_counts": {}}
        runs.append(entry)

    by_code = {stage["clip_code"]: stage for run in runs for stage in run["ratings"].values()}
    for rating in request.ratings:
        clip = clips.get(rating.clip_code)
        if clip is None or clip["sha256"] != rating.audio_sha256:
            raise ValueError("A rating targets an unknown clip or a changed artifact hash")
        by_code[rating.clip_code]["ratings"].append(rating.model_dump())

    for run in runs:
        for stage in run["ratings"].values():
            stage["score_counts"] = dict(Counter(str(row["score"]) for row in stage["ratings"]))
            stage["listener_count"] = len(stage["ratings"])
        sets = [
            {rating["listener_id"] for rating in stage["ratings"]}
            for stage in run["ratings"].values()
        ]
        run["paired_listeners"] = sorted(sets[0] & sets[1])

    return {
        "policy": "voice_stage_and_listening_review_v1",
        "order_seed": request.seed,
        "hardware_validated": False,
        "presentation_order": [
            {
                "index": index,
                "code": code,
                "wav": clips[code]["wav"],
                "sha256": clips[code]["sha256"],
            }
            for index, code in enumerate(sorted(clips), 1)
        ],
        "clip_key": clips,
        "runs": runs,
        "exclusions": exclusions,
        "rubric": {
            "1": "unintelligible",
            "2": "occasional words",
            "3": "meaning with effort",
            "4": "mostly clear",
            "5": "clear",
        },
    }
