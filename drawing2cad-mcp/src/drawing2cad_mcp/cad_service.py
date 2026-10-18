"""Persistent part revisions and candidate release through restricted workers."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

from jsonschema import Draft202012Validator, ValidationError

from . import __version__
from .cad_tools import CAD_SCHEMAS
from .schema_errors import describe as describe_schema_error
from .part_schema import PART_SCHEMA_VERSION, description_schema, part_validate as validate_description
from .part_changes import baseline as change_baseline, proposed_change, built_effect
from .worker_runner import WorkerLimits, WorkerRunner


MAX_STATE_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_STEP_BYTES = 32 * 1024 * 1024


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _time():
    return datetime.now(timezone.utc).isoformat()


class CadError(ValueError):
    """A stable service error. Failed run calls remain in the event trace."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message

    def as_dict(self):
        return {"code": self.code, "message": self.message}


class CadService:
    """Store JSON parts, enforce revisions, and keep release checks separate."""

    def __init__(self, allowed_roots, output_root, cad_settings, *, runner=None):
        self.allowed_roots = tuple(Path(path).expanduser().resolve() for path in allowed_roots)
        if not self.allowed_roots:
            raise ValueError("At least one source root is required.")
        self.output_root = Path(output_root).expanduser().resolve()
        self.storage = self.output_root / "cad"
        self.settings = cad_settings
        self.runner = runner or WorkerRunner(self.storage / "workers", WorkerLimits(timeout_seconds=cad_settings.timeout_seconds, memory_mb=cad_settings.memory_mb,
                                                                                   concurrent_workers=cad_settings.concurrency))
        self._probe = None

    def capabilities(self):
        from .adapters.stepcode import capabilities as analyzer_capabilities
        runtime = self.runner.capabilities()
        return {"enabled": self.settings.enabled, "runtime": runtime, "sandbox_probe": deepcopy(self._probe),
                "build_code_enabled": bool(self.settings.enabled and self.settings.allow_build_code and self._probe and self._probe.get("status") == "pass"),
                "part_schema_version": PART_SCHEMA_VERSION, "export_profile": "prototype_geometry_step",
                "export_profiles": ["ap214", "ap242"],
                "ap242_construction": "application_specific_adapter",
                "semantic_pmi": "nominal_diameter_and_linear",
                "independent_step_analysis": analyzer_capabilities(),
                "native_target_cad_features": "not_tested", "full_express_conformance": "not_tested"}

    def call(self, name, arguments):
        if name not in CAD_SCHEMAS:
            raise CadError("UNKNOWN_CAD_TOOL", "Use a tool from the CAD catalog.")
        if not isinstance(arguments, dict):
            raise CadError("INVALID_ARGUMENTS", "Tool arguments must be an object.")
        return getattr(self, name)(**arguments)

    @staticmethod
    def _validate(name, arguments):
        try:
            Draft202012Validator(CAD_SCHEMAS[name]).validate(arguments)
            _json(arguments)
        except (ValidationError, ValueError, TypeError) as error:
            # Name the field and the schema rule, never the input value.
            message = describe_schema_error(error)[1] if isinstance(error, ValidationError) else "The arguments must be finite JSON data."
            raise CadError("INVALID_ARGUMENTS", message) from error

    def _root(self):
        if self.output_root.resolve() != self.output_root or self.storage.resolve() != self.storage:
            raise CadError("STORAGE_PATH_CHANGED", "The output root changed its resolved location.")
        return self.storage

    def _directory(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", run_id):
            raise CadError("INVALID_RUN_ID", "Use a bounded run identifier from the tool schema.")
        path = self._root() / "runs" / run_id
        if path.resolve() != path:
            raise CadError("STORAGE_PATH_CHANGED", "The run directory must not contain a link.")
        return path

    @contextmanager
    def _lock(self, run_id):
        directory = self._directory(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "run.lock"
        if path.is_symlink():
            raise CadError("STORAGE_PATH_CHANGED", "The run lock must not be a link.")
        with path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            deadline = time.monotonic() + 10
            while True:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as error:
                    if time.monotonic() >= deadline:
                        raise CadError("RUN_BUSY", "Another operation holds this run lock.") from error
                    time.sleep(0.02)
            try:
                yield directory
            finally:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _atomic(path, data):
        if path.is_symlink() or path.parent.resolve() != path.parent:
            raise CadError("STORAGE_PATH_CHANGED", "A state or artifact path changed its resolved location.")
        handle, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # Windows refuses to replace a file that a lock-free reader has open. Retry for a short time.
            for attempt in range(50):
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError:
                    if os.name != "nt" or attempt == 49:
                        raise
                    time.sleep(0.02)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _save(self, directory, state):
        data = _json(state)
        if len(data) > MAX_STATE_BYTES:
            raise CadError("STATE_LIMIT", "The run state exceeds its byte limit.")
        self._atomic(directory / "state.json", data)

    def _load(self, directory):
        path = directory / "state.json"
        if path.is_symlink() or path.resolve() != path:
            raise CadError("STORAGE_PATH_CHANGED", "The state file must not be a link.")
        if not path.is_file():
            raise CadError("RUN_NOT_FOUND", "Create this part run first.")
        try:
            with path.open("rb") as stream:
                data = stream.read(MAX_STATE_BYTES + 1)
            state = json.loads(data)
            if len(data) > MAX_STATE_BYTES or state["schema_version"] != 1 or state["run_id"] != directory.name:
                raise ValueError("Invalid state identity.")
            if state["description_sha256"] != _sha(_json(state["description"])):
                raise ValueError("The description hash is inconsistent.")
            if type(state["revision"]) is not int or state["revision"] < 1:
                raise ValueError("Invalid revision.")
            if state["call_count"] != len(state["events"]) or not 1 <= state["call_count"]:
                raise ValueError("Invalid event count.")
            if validate_description(state["description"])["status"] != "pass":
                raise ValueError("Invalid stored description.")
            return state
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise CadError("STATE_INVALID", "The stored part state is incomplete or inconsistent.") from error

    @staticmethod
    def _source_bytes(path):
        with path.open("rb") as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES or b"%PDF-" not in data[:1024]:
            raise CadError("INVALID_PDF_SOURCE", "Use a PDF source of at most 20 MiB.")
        return data

    def _sources(self, sources):
        result, identifiers, hashes = [], set(), {}
        for source in sources:
            path = Path(source["path"]).expanduser()
            if not path.is_absolute():
                raise CadError("SOURCE_PATH_NOT_ALLOWED", "An M1 source requires an absolute server path.")
            path = path.resolve()
            if not any(path.is_relative_to(root) for root in self.allowed_roots) or path.suffix.lower() != ".pdf" or not path.is_file():
                raise CadError("SOURCE_PATH_NOT_ALLOWED", "The source must be a PDF in an authorized root.")
            try:
                digest = _sha(self._source_bytes(path))
            except OSError as error:
                raise CadError("SOURCE_READ_FAILED", "Cannot read the authorized source.") from error
            if digest != source["sha256"]:
                raise CadError("SOURCE_HASH_MISMATCH", "The source content differs from the registered hash.")
            identifier = source.get("source_id", digest)
            if identifier in identifiers or (digest in hashes and hashes[digest] != source["role"]):
                raise CadError("SOURCE_IDENTITY_CONFLICT", "Source IDs must be unique and one hash cannot have conflicting roles.")
            identifiers.add(identifier)
            hashes[digest] = source["role"]
            result.append({"source_id": identifier, "path": str(path), "sha256": digest, "role": source["role"]})
        if not any(item["role"] == "construction" for item in result):
            raise CadError("CONSTRUCTION_SOURCE_REQUIRED", "Register at least one construction source.")
        return result

    @staticmethod
    def _bind(description, sources):
        result = validate_description(description)
        if result["status"] != "pass":
            raise CadError("PART_INVALID", json.dumps(result["defects"], ensure_ascii=False)[:4000])
        source_map = {item["source_id"]: item for item in sources}
        evidence_map = {}
        for evidence in description["evidence"]:
            source = source_map.get(evidence["source"]["source_id"])
            if source is None or source["sha256"] != evidence["source"]["source_sha256"]:
                raise CadError("EVIDENCE_SOURCE_MISMATCH", "Each evidence item must identify an authorized source and its exact hash.")
            evidence_map[evidence["id"]] = source
        for item in [*description.get("parameters", []), *description["features"], *description.get("tolerances", [])]:
            if any(evidence_map[identifier]["role"] != "construction" for identifier in item["evidence_ids"]):
                raise CadError("VERIFICATION_SOURCE_USED_FOR_CONSTRUCTION", "Verification sources cannot provide construction or tolerance inputs.")
        if description.get("tolerances"):
            from pypdf import PdfReader
            pages = {}
            for tolerance in description["tolerances"]:
                for identifier in tolerance["evidence_ids"]:
                    source_region = next(item["source"] for item in description["evidence"] if item["id"] == identifier)
                    source = evidence_map[identifier]
                    if source_region.get("coordinate_system", "pdf_points") != "normalized_displayed":
                        raise CadError("TOLERANCE_REGION_REQUIRED", "Tolerance evidence requires a normalized displayed source region.")
                    source_id = source["source_id"]
                    if source_id not in pages:
                        try:
                            pages[source_id] = len(PdfReader(io.BytesIO(CadService._source_bytes(Path(source["path"])))).pages)
                        except Exception as error:
                            raise CadError("INVALID_PDF_SOURCE", "Cannot inspect the tolerance source pages.") from error
                    if source_region["page"] > pages[source_id]:
                        raise CadError("TOLERANCE_PAGE_MISSING", "Tolerance evidence identifies a page outside its PDF source.")

    def _record(self, directory, state, name, arguments, status, result=None, error=None):
        sequence = len(state["events"]) + 1
        request_data = _json(arguments)
        request_path = directory / f"event-{sequence:03d}-request.json"
        self._atomic(request_path, request_data)
        event = {"sequence": sequence, "recorded_at": _time(), "tool": name, "status": status, "revision": state["revision"], "request_path": str(request_path), "request_sha256": _sha(request_data)}
        if result is not None:
            result_data = _json(result)
            result_path = directory / f"event-{sequence:03d}-result.json"
            self._atomic(result_path, result_data)
            event.update(result_path=str(result_path), result_sha256=_sha(result_data))
        if error is not None:
            event["error"] = error
        state["events"].append(event)
        state["call_count"] = sequence
        self._save(directory, state)

    def _perform(self, name, arguments, operation):
        run_id = arguments.get("run_id")
        with self._lock(run_id) as directory:
            state = self._load(directory)
            if state["call_count"] >= state["step_budget"] and name not in {"part_read", "part_export_review"}:
                raise CadError("STEP_BUDGET_EXHAUSTED", "The run reached its tool-call budget. Review its recorded trace before a new run.")
            try:
                self._validate(name, arguments)
                if "expected_revision" in arguments and arguments["expected_revision"] != state["revision"]:
                    raise CadError("REVISION_CONFLICT", "Read the current revision before another mutation.")
                result = operation(state, directory)
            except CadError as error:
                self._record(directory, state, name, arguments, "fail", error=error.as_dict())
                raise
            except Exception as error:
                wrapped = CadError("CAD_SERVICE_FAILED", str(error)[:2000])
                self._record(directory, state, name, arguments, "fail", error=wrapped.as_dict())
                raise wrapped from error
            self._record(directory, state, name, arguments, result.get("status", "pass"), result=result)
            return {**result, "run_id": run_id, "revision": state["revision"], "call_count": state["call_count"], "step_budget": state["step_budget"]}

    def part_schema(self):
        return {"status": "pass", "schema": description_schema()}

    def pmi_schema(self):
        from .adapters.semantic_pmi import pmi_schema
        return {"status": "pass", "schema": pmi_schema()}

    def part_validate(self, description):
        result = validate_description(description)
        if result["status"] == "pass":
            from .expected_values import compute_expected
            from .part_schema import PartDescription

            result["computed_expected"] = compute_expected(PartDescription.model_validate(description))
        return result

    def part_create(self, **arguments):
        self._validate("part_create", arguments)
        run_id = arguments["run_id"]
        with self._lock(run_id) as directory:
            if (directory / "state.json").exists():
                raise CadError("RUN_EXISTS", "Choose a new run ID or read the existing run.")
            sources = self._sources(arguments["sources"])
            self._bind(arguments["description"], sources)
            budget = arguments.get("step_budget", self.settings.max_tool_calls)
            if budget > self.settings.max_tool_calls:
                raise CadError("STEP_BUDGET_LIMIT", "The requested budget exceeds the server limit.")
            state = {"schema_version": 1, "run_id": run_id, "revision": 1, "created_at": _time(), "description": deepcopy(arguments["description"]), "description_sha256": _sha(_json(arguments["description"])), "sources": sources, "build": None, "release": None, "source_review": None, "change_report": None, "step_budget": budget, "call_count": 0, "events": []}
            result = {"status": "pass", "description_sha256": state["description_sha256"]}
            self._record(directory, state, "part_create", arguments, "pass", result=result)
            return {**result, "run_id": run_id, "revision": 1, "call_count": 1, "step_budget": budget}

    def part_read(self, **arguments):
        return self._perform("part_read", arguments, lambda state, directory: {"status": "pass", "part": deepcopy(state)})

    def _replace(self, state, description):
        sources = self._sources(state["sources"])
        self._bind(description, sources)
        current_build = state.get("build")
        previous_report = state.get("change_report")
        if current_build and current_build.get("status") == "pass":
            base = change_baseline(state["description"], state["revision"], state["description_sha256"], current_build)
        elif previous_report:
            base = previous_report["baseline"]
        else:
            base = change_baseline(state["description"], state["revision"], state["description_sha256"], None)
        report = proposed_change(base, description, state["revision"] + 1)
        state.update(description=deepcopy(description), description_sha256=_sha(_json(description)), revision=state["revision"] + 1, build=None, release=None, source_review=None)
        state["change_report"] = report
        return {"status": "pass", "description_sha256": state["description_sha256"], "build_invalidated": True,
                "release_invalidated": True, "change_report": deepcopy(report)}

    def part_update(self, **arguments):
        return self._perform("part_update", arguments, lambda state, directory: self._replace(state, arguments["description"]))

    def _feature(self, name, arguments, kinds):
        def action(state, directory):
            feature = deepcopy(arguments["feature"])
            if feature["type"] not in kinds:
                raise CadError("FEATURE_TYPE_MISMATCH", "Use the feature type supported by this granular tool.")
            description = deepcopy(state["description"])
            if name == "create_base_body" and feature.get("operation") == "base":
                description["features"][0] = feature
            else:
                description["features"].append(feature)
            result = self._replace(state, description)
            return {**result, "feature_id": feature["id"]}
        return self._perform(name, arguments, action)

    def create_base_body(self, **arguments):
        return self._feature("create_base_body", arguments, {"box", "cylinder", "extrusion", "profile_extrusion"})

    def add_hole(self, **arguments):
        return self._feature("add_hole", arguments, {"hole"})

    def add_pocket(self, **arguments):
        return self._feature("add_pocket", arguments, {"pocket"})

    def add_cut(self, **arguments):
        return self._feature("add_cut", arguments, {"cut"})

    def add_chamfer(self, **arguments):
        return self._feature("add_chamfer", arguments, {"chamfer"})

    def add_fillet(self, **arguments):
        return self._feature("add_fillet", arguments, {"fillet"})

    def cad_worker_probe(self):
        if not self.settings.enabled:
            raise CadError("CAD_DISABLED", "Enable the configured CAD worker before running probes.")
        self._probe = self.runner.probe()
        return deepcopy(self._probe)

    def _candidate(self, result):
        worker = result.get("worker", {})
        directory = Path(worker.get("work_dir", ""))
        worker_root = Path(self.runner.storage).resolve()
        if not directory.is_absolute() or directory.resolve() != directory or directory.parent != worker_root:
            raise CadError("INVALID_WORKER_ARTIFACT", "The worker directory is not a direct child of its storage root.")
        path = directory / "candidate.step"
        if path.is_symlink() or path.resolve() != path or result.get("candidate_step") != str(path):
            raise CadError("INVALID_WORKER_ARTIFACT", "Only the fixed candidate STEP path in the worker directory is accepted.")
        if not path.is_file() or path.stat().st_size > MAX_STEP_BYTES:
            raise CadError("INVALID_WORKER_ARTIFACT", "The worker did not produce a bounded regular STEP candidate.")
        return path

    def check_build(self, name, arguments, state):
        """Reject a build before it changes state. A rejected call keeps the build, release, and reviews."""
        if not self.settings.enabled:
            raise CadError("CAD_DISABLED", "Enable the configured CAD worker before construction.")
        if name == "build_code" and not (self.settings.allow_build_code and self._probe and self._probe.get("status") == "pass"):
            raise CadError("BUILD_CODE_DISABLED", "Enable build_code and pass the sandbox probe in this server process first. Use build_from_description.")
        if name == "build_from_description" and arguments.get("pmi") is not None and arguments.get("export_profile", "ap214") != "ap242":
            raise CadError("PMI_PROFILE_REQUIRED", "PMI requires the AP242 export profile. Set export_profile to ap242 or remove pmi.")
        if state["call_count"] >= state["step_budget"]:
            raise CadError("STEP_BUDGET_EXHAUSTED", "The run reached its tool-call budget. Review its recorded trace before a new run.")
        self._sources(state["sources"])

    def _build(self, name, arguments):
        def failed(payload, *, build, validation=None, agreement=None, replay=None, analysis=None,
                   service_checks=None, fallback_code="BUILD_CHECK_FAILED"):
            phases = [("build", build), ("validation", validation), ("reconstruction", replay),
                      ("independent_analysis", analysis)]
            checks = [{**deepcopy(check), "phase": label} for label, phase in phases
                      if isinstance(phase, dict) for check in phase.get("checks", [])
                      if check.get("status") in {"pass", "fail"}]
            if isinstance(agreement, dict) and agreement.get("status") in {"pass", "fail"}:
                checks.append({**deepcopy(agreement), "phase": "agreement"})
            checks.extend(deepcopy(service_checks or []))
            cause = next((phase["error"] for _, phase in phases if isinstance(phase, dict)
                          and isinstance(phase.get("error"), dict)), {})
            payload["error"] = {"code": cause.get("code", fallback_code),
                                "message": cause.get("message", "The build failed its executed checks."),
                                "feature_id": cause.get("feature_id")}
            payload["feature_id"] = payload["error"]["feature_id"]
            payload["checks"] = checks
            return payload

        def action(state, directory):
            self.check_build(name, arguments, state)
            state["build"], state["release"], state["source_review"] = None, None, None
            def complete(payload):
                if state.get("change_report"):
                    state["change_report"] = built_effect(state["change_report"], state["build"])
                    payload["change_report"] = deepcopy(state["change_report"])
                return payload
            options = {"code": arguments["code"]} if name == "build_code" else {
                "export_profile": arguments.get("export_profile", "ap214"), "pmi": arguments.get("pmi")}
            result = self.runner.run("build_code" if name == "build_code" else "build", description=state["description"], **options)
            if result.get("status") != "pass":
                return complete(failed({"status": "fail", "build": result, "validation": {"status": "not_tested"}}, build=result))
            candidate = self._candidate(result)
            candidate_hash = _sha(candidate.read_bytes())
            imported = self.runner.run("validate", description=state["description"], input_step=candidate)
            if _sha(candidate.read_bytes()) != candidate_hash:
                raise CadError("CANDIDATE_CHANGED", "The candidate changed during validation.")
            build_worker = result.get("worker", {}).get("worker_id")
            import_worker = imported.get("worker", {}).get("worker_id")
            fresh = bool(build_worker and import_worker and build_worker != import_worker)
            import_checks = imported.get("checks", [])
            reimport = next((item for item in import_checks if item.get("check") == "step_reimport"), None)
            imported_hash = imported.get("step", {}).get("sha256")
            reimport_passed = bool(reimport and reimport.get("status") == "pass" and fresh and imported_hash == candidate_hash)
            fresh_check = {"check": "fresh_worker_reimport", "status": "pass" if reimport_passed else "fail"}
            if not reimport_passed:
                if not reimport or reimport.get("status") != "pass":
                    fresh_check["reason"] = reimport.get("reason", "The validation worker did not report a successful STEP import.") if reimport else "The validation worker did not report a STEP import result."
                elif not fresh:
                    fresh_check["reason"] = "The build and validation workers are not distinct."
                elif imported_hash != candidate_hash:
                    fresh_check["reason"] = "The validation worker did not confirm the candidate STEP hash."
            result["checks"] = [item for item in result.get("checks", []) if item.get("check") != "fresh_worker_reimport"] + [deepcopy(fresh_check)]
            imported["checks"] = [item for item in import_checks if item.get("check") != "fresh_worker_reimport"] + [deepcopy(fresh_check)]
            if imported.get("status") != "pass":
                state["build"] = {"status": "fail", "description_revision": state["revision"], "description_sha256": state["description_sha256"], "candidate_path": str(candidate), "candidate_sha256": candidate_hash, "build": result, "validation": imported, "feature_replay": "pass" if name == "build_from_description" else "not_tested"}
                return complete(failed({"status": "fail", "build": deepcopy(state["build"]), "released": False},
                                       build=result, validation=imported))
            if imported.get("step", {}).get("sha256") != candidate_hash:
                raise CadError("VALIDATION_HASH_MISMATCH", "The imported STEP bytes do not match the candidate.")
            if not fresh:
                raise CadError("FRESH_WORKER_REQUIRED", "Build and import must use different worker processes.")
            agreement = self._compare(result.get("measured", {}), imported.get("measured", {}))
            # Client code can forge its worker result. Only trusted import checks authorize release.
            if name == "build_code":
                agreement = {"check": "build_import_agreement", "status": "not_tested", "reason": "The code-worker report is not independent evidence."}
            status = "pass" if reimport_passed and imported.get("status") == "pass" and agreement["status"] != "fail" else "fail"
            record = {"status": status, "description_revision": state["revision"], "description_sha256": state["description_sha256"], "candidate_path": str(candidate), "candidate_sha256": candidate_hash, "build": result, "validation": imported, "agreement": agreement, "feature_replay": "pass" if name == "build_from_description" else "not_tested"}
            record["export_profile"] = options.get("export_profile", "ap214")
            service_checks = []
            fallback_code = "BUILD_CHECK_FAILED"
            if record["export_profile"] == "ap242":
                schemas = imported.get("step", {}).get("schemas", [])
                if not any(schema.startswith("AP242_MANAGED_MODEL_BASED_3D_ENGINEERING") for schema in schemas):
                    record["status"] = "fail"
                    state["build"] = record
                    payload = failed({"status": "fail", "build": deepcopy(record), "released": False},
                                     build=result, validation=imported, agreement=agreement)
                    payload["error"] = {"code": "AP242_SCHEMA_REQUIRED",
                                        "message": "The selected AP242 export must have an AP242 schema header.",
                                        "feature_id": None}
                    payload["checks"].append({"check": "ap242_schema_header", "status": "fail", "phase": "validation"})
                    return complete(payload)
                replay = self.runner.run("reconstruct_step", input_step=candidate)
                record["step_only_reconstruction"] = replay
                if _sha(candidate.read_bytes()) != candidate_hash:
                    raise CadError("CANDIDATE_CHANGED", "The candidate changed during STEP-only reconstruction.")
                replay_worker = replay.get("worker", {}).get("worker_id")
                replay_ok = (replay.get("status") == "pass"
                             and replay.get("input_sha256") == candidate_hash
                             and replay.get("construction", {}).get("original_agreement") == "pass"
                             and replay_worker and replay_worker not in {build_worker, import_worker})
                if not replay_ok:
                    record["status"] = status = "fail"
                    fallback_code = "STEP_RECONSTRUCTION_FAILED"
                    service_checks.append({"check": "step_only_reconstruction", "status": "fail",
                                           "phase": "reconstruction"})
                analysis = self.runner.run("analyze_ap242", input_step=candidate)
                from .adapters.stepcode_pmi import verify_nominal_pmi
                nominal = verify_nominal_pmi(analysis, expected=result.get("pmi", {}).get("dimensions", []),
                                             product_name=state["description"]["name"])
                analysis["nominal_pmi"] = nominal
                analysis.setdefault("checks", []).append({"check": nominal["check"], "status": nominal["status"]})
                if nominal["status"] != "pass":
                    analysis["status"] = "fail"
                # The parent-owned worker record retains the complete typed inventory.
                # Keep the run state and MCP result limited to the inspected dimensions.
                analysis.pop("pmi_inventory", None)
                record["independent_analysis"] = analysis
                if _sha(candidate.read_bytes()) != candidate_hash:
                    raise CadError("CANDIDATE_CHANGED", "The candidate changed during independent analysis.")
                analysis_worker = analysis.get("worker", {}).get("worker_id")
                analysis_ok = (self._analysis_passed(analysis, candidate_hash)
                               and analysis_worker
                               and analysis_worker not in {build_worker, import_worker, replay_worker})
                if not analysis_ok:
                    record["status"] = status = "fail"
                    if fallback_code == "BUILD_CHECK_FAILED":
                        fallback_code = "INDEPENDENT_ANALYSIS_FAILED"
                    service_checks.append({"check": "independent_analysis_binding", "status": "fail",
                                           "phase": "independent_analysis"})
            state["build"] = record
            payload = {"status": status, "build": deepcopy(record), "released": False}
            return complete(failed(payload, build=result, validation=imported, agreement=agreement,
                           replay=record.get("step_only_reconstruction"),
                           analysis=record.get("independent_analysis"), service_checks=service_checks,
                           fallback_code=fallback_code)
                    if status == "fail" else payload)
        return self._perform(name, arguments, action)

    @staticmethod
    def _analysis_passed(analysis, candidate_hash):
        checks = {item.get("check"): item.get("status") for item in analysis.get("checks", [])}
        return (analysis.get("status") == "pass"
                and analysis.get("input_sha256") == candidate_hash
                and analysis.get("analyzer") == "STEPcode"
                and checks.get("independent_ap242_schema_read") == "pass"
                and checks.get("independent_nominal_pmi_graph") == "pass"
                and "fail" not in checks.values())

    @staticmethod
    def _compare(built, imported):
        try:
            volume = float(built["volume_mm3"])
            imported_volume = float(imported["volume_mm3"])
            pairs = [(volume, imported_volume), *zip(built["bbox_min"], imported["bbox_min"]), *zip(built["bbox_max"], imported["bbox_max"])]
            passed = len(pairs) == 7 and all(math.isfinite(a) and math.isfinite(b) and abs(a - b) <= max(1e-5, abs(a) * 1e-7) for a, b in pairs)
        except (KeyError, TypeError, ValueError):
            passed = False
        return {"check": "build_import_agreement", "status": "pass" if passed else "fail", "scope": "volume_and_bounding_box"}

    def build_from_description(self, **arguments):
        return self._build("build_from_description", arguments)

    def build_code(self, **arguments):
        return self._build("build_code", arguments)

    @staticmethod
    def _coverage(state, coverage):
        expected_hashes = {item["sha256"] for item in state["sources"] if item["role"] == "construction"}
        if set(coverage["source_hashes"]) != expected_hashes:
            raise CadError("COVERAGE_SOURCE_MISMATCH", "The review must cover all current construction source hashes.")
        for category in ("views", "features", "printed_dimensions"):
            if coverage[category]["reviewed"] != coverage[category]["total"]:
                raise CadError("COVERAGE_INCOMPLETE", "All source views, features, and printed dimensions must be reviewed.")
        measurements = {item["id"] for item in state["description"].get("measurements", [])}
        if not set(coverage["critical_measurement_ids"]) <= measurements:
            raise CadError("COVERAGE_MEASUREMENT_MISSING", "Each critical dimension must identify a declared measurement.")
        return {**deepcopy(coverage), "status": "pass", "scope": "identified_source_review_attestation", "automatically_verified_source_completeness": "not_tested"}

    def export_step(self, **arguments):
        def action(state, directory):
            self._sources(state["sources"])
            built = state["build"]
            if not built or built["status"] != "pass" or built["description_sha256"] != state["description_sha256"] or built["description_revision"] != state["revision"]:
                raise CadError("VALIDATED_BUILD_REQUIRED", "Build and validate the current description before release.")
            if built.get("export_profile") == "ap242" and not self._analysis_passed(
                    built.get("independent_analysis", {}), built["candidate_sha256"]):
                raise CadError("INDEPENDENT_ANALYSIS_REQUIRED", "Rebuild the AP242 candidate with independent schema and nominal PMI analysis before release.")
            checks = built["validation"].get("checks", [])
            statuses = {item["check"]: item["status"] for item in checks}
            required = {"step_reimport", "solid_validity", "solid_count", "positive_volume", "step_references", "step_product_name", "step_units_mm", "step_schema_present", "drawing_measurements"}
            if any(statuses.get(name) != "pass" for name in required) or any(item["status"] == "fail" for item in checks):
                raise CadError("RELEASE_CHECKS_INCOMPLETE", "Trusted import, geometry, identity, units, schema, and drawing measurements must pass.")
            coverage = self._coverage(state, arguments["coverage"])
            if any(statuses.get(identifier) != "pass" for identifier in coverage["critical_measurement_ids"]):
                raise CadError("CRITICAL_DIMENSION_UNVERIFIED", "Each critical source dimension must have a passing imported geometry measurement.")
            candidate = Path(built["candidate_path"])
            self._candidate(built["build"])
            data = candidate.read_bytes()
            if _sha(data) != built["candidate_sha256"]:
                raise CadError("CANDIDATE_CHANGED", "The validated candidate bytes changed before release.")
            release_path = directory / f"part-r{state['revision']}-{built['candidate_sha256'][:12]}.step"
            self._atomic(release_path, data)
            state["source_review"] = coverage
            state["release"] = {"path": str(release_path), "sha256": built["candidate_sha256"], "bytes": len(data), "description_revision": state["revision"], "profile": "validated_prototype_step", "metric_acceptance": "not_tested", "scope": "Kernel checks and identified source review passed. Independent conformance, target CAD, construction reconstruction, and PMI are separate checks."}
            state["release"]["export_profile"] = built.get("export_profile", "ap214")
            if built.get("export_profile") == "ap242":
                state["release"].update(profile="validated_ap242_application_construction",
                    scope="Geometry, the application-specific STEP-only adapter, and bounded independent schema analysis passed. Read the separate PMI and visual reports. Native target-CAD features and full EXPRESS conformance are not proven.")
            return {"status": "pass", "release": deepcopy(state["release"]), "checks": deepcopy(checks), "source_review": coverage}
        return self._perform("export_step", arguments, action)

    def part_export_review(self, **arguments):
        def action(state, directory):
            artifact_dir = directory / ("reports-" + uuid.uuid4().hex)
            artifact_dir.mkdir()
            review = validate_description(state["description"])["review_items"]
            rows = [{"id": item.get("id"), "status": item.get("status"), "reason": item.get("reason"), "source": json.dumps(item.get("source", item.get("evidence_ids")), ensure_ascii=False)} for item in review]
            csv_buffer = io.StringIO(newline="")
            writer = csv.DictWriter(csv_buffer, fieldnames=["id", "status", "reason", "source"])
            writer.writeheader()
            for row in rows:
                writer.writerow({key: ("'" + str(value) if str(value).lstrip().startswith(("=", "+", "-", "@")) else value) for key, value in row.items()})
            markdown = "# Part review list\n\n" + ("No inferred, assumed, derived, or unresolved evidence is recorded.\n" if not rows else "\n".join(f"- {row['id']}: {row['status']}. {row['reason']}" for row in rows) + "\n")
            manifest = {"schema_version": 1, "run_id": state["run_id"], "description_revision": state["revision"], "description_sha256": state["description_sha256"], "sources": state["sources"], "created_at": _time(), "package_version": __version__, "tool_names": sorted(CAD_SCHEMAS), "limits": {"timeout_seconds": self.settings.timeout_seconds, "memory_mb": self.settings.memory_mb, "step_budget": state["step_budget"]}, "build": state["build"], "release": state["release"], "source_review": state["source_review"], "change_report": state.get("change_report"), "call_count_before_export": state["call_count"]}
            trace = []
            for event in state["events"]:
                record = deepcopy(event)
                for field in ("request", "result"):
                    if field + "_path" in event:
                        path = Path(event[field + "_path"])
                        if path.parent != directory or path.is_symlink():
                            raise CadError("TRACE_INVALID", "A trace artifact is outside this run.")
                        data = path.read_bytes()
                        if _sha(data) != event[field + "_sha256"]:
                            raise CadError("TRACE_INVALID", "A recorded trace artifact changed.")
                        record[field] = json.loads(data)
                trace.append(record)
            files = {"part.json": _json(state["description"]), "review.md": markdown.encode("utf-8"), "review.csv": csv_buffer.getvalue().encode("utf-8"), "coverage.json": _json(state["source_review"] or {"status": "not_tested"}), "trace.jsonl": ("\n".join(json.dumps(event, ensure_ascii=False, allow_nan=False) for event in trace) + "\n").encode("utf-8")}
            if state.get("change_report"):
                files["change-report.json"] = _json(state["change_report"])
            artifacts = []
            for name, data in files.items():
                path = artifact_dir / name
                self._atomic(path, data)
                artifacts.append({"path": str(path), "sha256": _sha(data), "bytes": len(data)})
            manifest["artifacts"] = artifacts
            manifest_data = _json(manifest)
            self._atomic(artifact_dir / "manifest.json", manifest_data)
            artifacts.append({"path": str(artifact_dir / "manifest.json"), "sha256": _sha(manifest_data), "bytes": len(manifest_data)})
            return {"status": "pass", "artifacts": artifacts, "trace_scope": "All completed run calls before this report export. Requests rejected before run lookup are transport-level events."}
        return self._perform("part_export_review", arguments, action)
