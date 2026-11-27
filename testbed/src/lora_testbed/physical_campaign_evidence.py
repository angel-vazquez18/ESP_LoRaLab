"""Bounded physical campaign bundles with verified saved files and explicit child links."""

import hashlib
import io
import json
import zipfile
import zlib
from collections import Counter
from pathlib import Path, PurePosixPath

from pydantic import TypeAdapter

from .campaign_plans import digest
from .control_v2 import UUID
from .evidence_worker import SavedEvidenceWorker
from .physical_campaigns import TERMINAL, PhysicalCampaigns
from .session_keys import require_public_metadata

MAX_BYTES = 128 * 1024 * 1024
MAX_MEMBERS = 20000
PROFILE = "physical_campaign_bundle_v1"


def identity(value):
    return TypeAdapter(UUID).validate_python(value)


def safe_name(name):
    path = PurePosixPath(name)
    if (
        not name
        or not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or str(path) != name
        or any(ord(char) < 32 for char in name)
    ):
        raise ValueError("Unsafe campaign bundle member name")


def json_bytes(value):
    require_public_metadata(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class CampaignExports(SavedEvidenceWorker):
    def __init__(self, host):
        super().__init__("Another campaign export is in progress")
        self.host = host

    async def export(self, identifier):
        return await self.run(CampaignBundle(self.host).build, identifier)


class CampaignBundle:
    def __init__(self, host):
        self.host = host
        self.members, self.children, self.files, self.links = {}, [], [], []
        self.seen = set()
        self.size = 0

    def add(self, name, data):
        safe_name(name)
        if name in self.members:
            raise ValueError("Duplicate campaign bundle member")
        if len(self.members) >= MAX_MEMBERS or self.size + len(data) > MAX_BYTES:
            raise ValueError(
                "Campaign export exceeds 128 MiB or 20,000 members; use a smaller campaign"
            )
        self.members[name] = data
        self.size += len(data)

    def file(self, owner, name, data, *, kind, expected=None, length=None):
        observed = hashlib.sha256(data).hexdigest()
        if expected is not None and observed != expected:
            raise ValueError(f"Saved campaign file hash differs: {name}")
        if length is not None and len(data) != length:
            raise ValueError(f"Saved campaign file length differs: {name}")
        if name.endswith((".json", ".ndjson", ".jsonl")):
            try:
                for raw in data.splitlines() if not name.endswith(".json") else [data]:
                    require_public_metadata(json.loads(raw))
            except (ValueError, UnicodeError):
                raise ValueError(
                    "Unsafe or malformed campaign metadata cannot be exported"
                ) from None
        self.add(name, data)
        self.files.append(
            {
                "owner": owner,
                "path": name,
                "kind": kind,
                "length_bytes": len(data),
                "sha256": observed,
                "saved_sha256": expected,
                "integrity_basis": "saved hash and observed bytes"
                if expected
                else "export-time hash only; no prior finalized file hash",
            }
        )

    def check_path(self, path):
        if not path.resolve().is_relative_to(self.host.store.root.resolve()):
            raise ValueError("Saved file is outside the campaign evidence directory")

    def read_file(self, path):
        self.check_path(path)
        try:
            with path.open("rb") as stream:
                data = stream.read(min(MAX_BYTES - self.size, 64 * 1024 * 1024) + 1)
        except OSError:
            raise ValueError(f"Saved campaign file is missing or unreadable: {path.name}") from None
        if len(data) > min(MAX_BYTES - self.size, 64 * 1024 * 1024):
            raise ValueError("Saved campaign file exceeds the bounded export budget")
        return data

    def trace(self, owner, record, directory):
        path = directory / f"{record['id']}.ndjson"
        expected = record.get("wire_sha256") or record.get("evidence_sha256")
        if path.is_file() or expected or record.get("wire_bytes"):
            self.file(
                owner,
                f"evidence/{owner['service']}/{owner['id']}.ndjson",
                self.read_file(path),
                kind="command_trace",
                expected=expected,
                length=record.get("wire_bytes") if expected else None,
            )

    def rows(self, owner, name, rows):
        output = io.BytesIO()
        for row in rows:
            data = json_bytes(row) + b"\n"
            if output.tell() + len(data) > MAX_BYTES - self.size:
                raise ValueError("Campaign row evidence exceeds the export budget")
            output.write(data)
        self.file(owner, name, output.getvalue(), kind="event_rows")

    def visit(self, service, identifier, source):
        identity(identifier)
        owner = {"service": service, "id": identifier}
        self.links.append({"from": source, "to": owner})
        key = (service, identifier)
        if key in self.seen:
            return
        self.seen.add(key)
        runner = (
            self.host.artifacts
            if service == "transfer"
            else self.host.physical_campaigns.child_service(service)
        )
        record = runner.get(identifier)
        if record is None:
            raise ValueError("A linked campaign child record is missing")
        if record["status"] not in TERMINAL:
            raise RuntimeError("Finish the linked child before exporting its campaign")
        path = f"children/{service}/{identifier}.json"
        self.add(path, json_bytes(record))
        self.children.append({**owner, "path": path, "status": record["status"]})
        prefix = f"files/{service}/{identifier}"
        if service == "diagnostic":
            self.trace(owner, record, runner.directory)
            evidence = runner.evidence(identifier, include_records=True)
            self.rows(
                owner, f"evidence/{service}/{identifier}.jsonl", evidence["operation_events"] or []
            )
        elif service == "procedure":
            self.rows(
                owner, f"evidence/{service}/{identifier}.jsonl", runner.all_evidence(identifier)
            )
            for case in record["cases"]:
                identity(case["id"])
                for index, entry in enumerate(case.get("files", [])):
                    saved = (self.host.store.root / entry["relative_path"]).resolve()
                    if not saved.is_relative_to(self.host.store.root.resolve()):
                        raise ValueError("Procedure saved file is outside the evidence directory")
                    self.file(
                        owner,
                        f"{prefix}/{case['id']}/{index}-{saved.name}",
                        self.read_file(saved),
                        kind="procedure_file",
                        expected=entry["sha256"],
                    )
        elif service == "transfer":
            self.trace(owner, record, runner.directory)
            saved = runner.directory / f"{identifier}.bin"
            if record["status"] == "completed":
                self.check_path(saved)
                saved = runner.content(identifier)
                manifest = record.get("manifest")
                if manifest and (
                    manifest["sha256"] != record["actual_sha256"]
                    or manifest["length_bytes"] != record["bytes_total"]
                ):
                    raise ValueError("Transfer and saved artifact manifests differ")
                self.file(
                    owner,
                    f"{prefix}/content.bin",
                    self.read_file(saved),
                    kind="verified_payload",
                    expected=record["actual_sha256"],
                    length=record["bytes_total"],
                )
            elif saved.exists():
                self.file(
                    owner,
                    f"{prefix}/partial.bin",
                    self.read_file(saved),
                    kind="unverified_partial_payload",
                )
        elif service == "audio":
            self.trace(owner, record, runner.directory)
            transfers = {record.get("transfer_id")} | {
                value.get("transfer_id") for value in record.get("codec_artifacts", {}).values()
            }
            for transfer in sorted(value for value in transfers if value):
                self.visit("transfer", transfer, owner)
            for stage, value in record.get("codec_artifacts", {}).items():
                if value.get("verified"):
                    runner.codec_content(
                        identifier, stage
                    )  # Independently checks the stage manifest.
            saved = runner.directory / f"{identifier}.wav"
            if record.get("clip") is not None or saved.exists():
                self.file(
                    owner,
                    f"{prefix}/audio.wav",
                    self.read_file(saved),
                    kind="saved_wav",
                    expected=record.get("wav_sha256"),
                )
        elif service == "radio":
            self.trace(owner, record, runner.directory)
            for transfer in record["transfers"].values():
                self.visit("transfer", transfer, owner)
            declared = record.get("saved_files", {})
            for kind, role in (("source", record["sender"]), ("recovered", record["receiver"])):
                saved = runner.directory / f"{identifier}.{kind}.bin"
                entry = declared.get(kind) or record["readback_manifests"].get(role)
                if saved.exists() or entry:
                    self.file(
                        owner,
                        f"{prefix}/{kind}.bin",
                        self.read_file(saved),
                        kind="radio_payload",
                        expected=entry["sha256"] if entry else None,
                        length=entry["length_bytes"] if entry else None,
                    )
        elif service == "voice":
            for name, child in record["jobs"].items():
                self.visit("transfer" if name == "source_upload" else "audio", child, owner)
            if record["radio_run_id"]:
                self.visit("radio", record["radio_run_id"], owner)
            for value in record.get("comparisons", {}).values():
                if value.get("radio_run_id"):
                    self.visit("radio", value["radio_run_id"], owner)
            reference = record.get("reference")
            if reference:
                identity(reference["id"])
                self.file(
                    owner,
                    f"{prefix}/reference.json",
                    json_bytes(reference),
                    kind="reference_metadata",
                )
                self.file(
                    owner,
                    f"{prefix}/reference.wav",
                    self.read_file(self.host.store.root / "audio" / f"{reference['id']}.wav"),
                    kind="reference_wav",
                    expected=reference["sha256"],
                )
        else:
            raise ValueError("Unknown campaign child service")

    def build(self, identifier):
        record = self.host.physical_campaigns.get(identifier)
        if record["status"] not in TERMINAL:
            raise RuntimeError("Finish or interrupt the campaign before exporting")
        plan = self.host.campaign_plans.get(record["plan_id"])
        if record["plan_sha256"] != plan["plan_sha256"]:
            raise ValueError("Campaign and saved plan hashes differ")
        self.add("campaign.json", json_bytes(record))
        self.add("plan.json", json_bytes(plan))
        for case in record["cases"]:
            if case["child"]:
                self.visit(
                    case["child"]["service"], case["child"]["id"], {"case_id": case["case_id"]}
                )
        manifest = {
            "profile": PROFILE,
            "exporter_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "execution_id": identifier,
            "plan_id": plan["id"],
            "parent_execution_id": record.get("parent_execution_id"),
            "hardware_qualified": False,
            "case_count": len(record["cases"]),
            "child_count": len(self.children),
            "file_count": len(self.files),
            "children": self.children,
            "files": self.files,
            "links": self.links,
            "integrity_scope": (
                "Saved hashes where declared; export-time member hashes otherwise. "
                "Not authentication or physical qualification."
            ),
        }
        self.add("manifest.json", json_bytes(manifest))
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in self.members.items()}
        self.add("sha256.json", json_bytes(hashes))
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in self.members.items():
                member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                member.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(member, content)
        content = output.getvalue()
        verify_campaign_bundle(content)
        return content


def verify_campaign_bundle(content):
    """Check a downloaded bundle without a host, device or extraction to disk."""
    if len(content) > MAX_BYTES:
        raise ValueError("Campaign archive exceeds 128 MiB")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or len(names) > MAX_MEMBERS:
                raise ValueError("Duplicate or excessive archive members")
            if sum(info.file_size for info in archive.infolist()) > MAX_BYTES:
                raise ValueError("Expanded campaign archive exceeds 128 MiB")
            for name in names:
                safe_name(name)
            hashes = json.loads(archive.read("sha256.json"))
            if not isinstance(hashes, dict):
                raise ValueError("Campaign hash manifest must be an object")
            if set(names) != set(hashes) | {"sha256.json"}:
                raise ValueError("Campaign archive member list differs from its hash manifest")
            for name, expected in hashes.items():
                if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                    raise ValueError(f"Campaign archive member hash differs: {name}")
            manifest = json.loads(archive.read("manifest.json"))
            record = json.loads(archive.read("campaign.json"))
            plan = json.loads(archive.read("plan.json"))
            if manifest["profile"] != PROFILE or manifest["execution_id"] != record["id"]:
                raise ValueError("Campaign bundle profile or identity differs")
            PhysicalCampaigns.verify_document({k: v for k, v in record.items() if k != "cases"})
            for case in record["cases"]:
                PhysicalCampaigns.verify_document(case)
            if (
                plan["plan_sha256"] != digest({k: v for k, v in plan.items() if k != "plan_sha256"})
                or record["plan_sha256"] != plan["plan_sha256"]
                or manifest["plan_id"] != plan["id"]
            ):
                raise ValueError("Campaign bundle plan hashes differ")
            if (
                record["case_count"] != len(record["cases"])
                or manifest["case_count"] != len(record["cases"])
                or manifest["child_count"] != len(manifest["children"])
                or manifest["file_count"] != len(manifest["files"])
            ):
                raise ValueError("Campaign bundle record counts differ")
            cases = record["cases"]
            case_ids = [case["case_id"] for case in cases]
            selected_ids = set(case_ids)
            planned = [case["id"] for case in plan["cases"] if case["id"] in selected_ids]
            if (
                len(set(case_ids)) != len(case_ids)
                or case_ids != planned
                or record.get("selected_case_ids", case_ids) != case_ids
                or dict(Counter(case["status"] for case in cases)) != record["case_counts"]
                or record["status"] not in TERMINAL
                or manifest.get("parent_execution_id") != record.get("parent_execution_id")
            ):
                raise ValueError("Campaign selected cases, order or outcomes differ")
            children = {(row["service"], row["id"]): row for row in manifest["children"]}
            if len(children) != len(manifest["children"]):
                raise ValueError("Duplicate campaign child records")
            for (service, identifier), child in children.items():
                identity(identifier)
                if child["path"] != f"children/{service}/{identifier}.json":
                    raise ValueError("Campaign child path differs")
                saved = json.loads(archive.read(child["path"]))
                require_public_metadata(saved)
                if (
                    saved["id"] != identifier
                    or saved["status"] != child["status"]
                    or saved["status"] not in TERMINAL
                ):
                    raise ValueError("Campaign child identity or terminal status differs")
            expected_paths = (
                {"campaign.json", "plan.json", "manifest.json"}
                | {child["path"] for child in children.values()}
                | {entry["path"] for entry in manifest["files"]}
            )
            if len({entry["path"] for entry in manifest["files"]}) != len(manifest["files"]):
                raise ValueError("Duplicate campaign file inventory entries")
            if set(hashes) != expected_paths:
                raise ValueError("Campaign file inventory differs from its members")
            for entry in manifest["files"]:
                data = archive.read(entry["path"])
                if (
                    len(data) != entry["length_bytes"]
                    or hashlib.sha256(data).hexdigest() != entry["sha256"]
                    or entry["saved_sha256"] is not None
                    and entry["saved_sha256"] != entry["sha256"]
                ):
                    raise ValueError("Campaign saved-file manifest differs")
                if (entry["owner"]["service"], entry["owner"]["id"]) not in children:
                    raise ValueError("Campaign file owner is missing")
            reachable = {
                (case["child"]["service"], case["child"]["id"])
                for case in record["cases"]
                if case["child"]
            }
            if not reachable <= children.keys():
                raise ValueError("A campaign case is missing its child record")
            for link in manifest["links"]:
                source, target = link["from"], link["to"]
                if (target["service"], target["id"]) not in children:
                    raise ValueError("Campaign link target is missing")
                if "case_id" in source:
                    match = next(
                        (case for case in cases if case["case_id"] == source["case_id"]), None
                    )
                    if match is None or match["child"] != target:
                        raise ValueError("Campaign case link differs from its saved child")
                elif (source["service"], source["id"]) not in children:
                    raise ValueError("Campaign link source is missing")
            root_links = {
                link["from"]["case_id"] for link in manifest["links"] if "case_id" in link["from"]
            }
            if root_links != {case["case_id"] for case in cases if case["child"]}:
                raise ValueError("Campaign case links are incomplete")
            previous = set()
            while previous != reachable:
                previous = set(reachable)
                for link in manifest["links"]:
                    source = link["from"]
                    if "service" in source and (source["service"], source["id"]) in reachable:
                        reachable.add((link["to"]["service"], link["to"]["id"]))
            if reachable != children.keys():
                raise ValueError("Campaign child links are incomplete or contain orphan records")
            require_public_metadata(record)
            require_public_metadata(plan)
            return {
                "profile": PROFILE,
                "execution_id": record["id"],
                "case_count": manifest["case_count"],
                "child_count": manifest["child_count"],
                "file_count": manifest["file_count"],
                "member_count": len(names),
                "case_counts": dict(Counter(case["status"] for case in record["cases"])),
                "sha256": hashlib.sha256(content).hexdigest(),
                "hardware_qualified": False,
            }
    except (
        zipfile.BadZipFile,
        KeyError,
        TypeError,
        UnicodeError,
        OSError,
        RuntimeError,
        NotImplementedError,
        zlib.error,
    ) as exc:
        raise ValueError("Malformed or incomplete campaign archive") from exc
