"""Persistent, bounded evidence gates. No CAD executor is implemented here."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
import time

from jsonschema import Draft202012Validator, ValidationError

from . import __version__
from .workflow_tools import WORKFLOW_SCHEMAS, PHASES
from .schema_errors import describe as describe_schema_error


SCOPE = {
    "enforcement_scope": "managed_evidence_transitions_only",
    "cad_execution": False,
    "cad_validation": "unavailable",
    "review_evidence": "identified_attestation_not_cad_validation",
}
MAX_ARTIFACT_BYTES = 104857600
MAX_STATE_BYTES = 8388608
TOOL_PHASES = {
    "workflow_create_run": "intake", "workflow_observe": "observe",
    "workflow_register_drawing": "drawing_prepare", "workflow_review_drawing": "drawing_review",
    "workflow_fix_contract": "freeze",
}


def _defect(code, target, message, action):
    return {"code": code, "target": target, "message": message, "required_action": action}


class WorkflowError(ValueError):
    """A structured workflow failure with a specific corrective action."""

    def __init__(self, code, message, defects=None):
        super().__init__(message)
        self.code = code
        self.defects = defects or [_defect(code, "request", message, "Correct the request and retry.")]

    def as_dict(self):
        return {"code": self.code, "message": str(self), "defects": deepcopy(self.defects), **SCOPE}


class WorkflowService:
    """Manage evidence revisions. Paths and hashes do not prove CAD correctness."""

    def __init__(self, allowed_roots, output_root):
        self.allowed_roots = tuple(Path(p).expanduser().resolve() for p in allowed_roots)
        if not self.allowed_roots:
            raise ValueError("At least one authorized source root is required.")
        self.output_root = Path(output_root).expanduser().resolve()
        self.storage = self.output_root / "workflow"
        self._storage_path()

    def _storage_path(self):
        if self.storage.resolve() != self.storage or self.output_root.resolve() != self.output_root:
            raise WorkflowError("STORAGE_PATH_CHANGED", "Workflow storage changed its resolved location.")
        return self.storage

    @contextmanager
    def _lock(self, run_id):
        self._storage_path().mkdir(parents=True, exist_ok=True)
        path = self._storage_path() / (run_id + ".lock")
        if path.is_symlink():
            raise WorkflowError("STORAGE_PATH_CHANGED", "The workflow lock must not be a symbolic link.")
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
                        raise WorkflowError("RUN_BUSY", "The run is locked by another operation.") from error
                    time.sleep(0.01)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _path(self, run_id):
        path = self._storage_path() / (run_id + ".json")
        if path.is_symlink():
            raise WorkflowError("STORAGE_PATH_CHANGED", "A workflow manifest must not be a symbolic link.")
        return path

    @staticmethod
    def _validate(name, args):
        try:
            Draft202012Validator(WORKFLOW_SCHEMAS[name]).validate(args)
            # JSON Schema accepts NaN and infinity as numbers; the contract does not.
            json.dumps(args, allow_nan=False)
        except (ValidationError, ValueError, TypeError) as error:
            # Name the field and the schema rule, never the input value.
            message = describe_schema_error(error)[1] if isinstance(error, ValidationError) else "The arguments must be finite JSON data."
            raise WorkflowError("INVALID_ARGUMENTS", message) from error

    def _load(self, run_id):
        path = self._path(run_id)
        if not path.is_file():
            raise WorkflowError("RUN_NOT_FOUND", "The requested run does not exist.")
        try:
            with path.open("rb") as stream:
                payload = stream.read(MAX_STATE_BYTES + 1)
            if len(payload) > MAX_STATE_BYTES:
                raise ValueError("Workflow state exceeds the size limit.")
            state = json.loads(payload)
            if (not isinstance(state, dict) or state.get("schema_version") != 1
                    or state.get("run_id") != run_id
                    or type(state.get("state_revision")) is not int
                    or state["state_revision"] < 0
                    or state["state_revision"] != len(state["events"]) - 1):
                raise ValueError("Workflow state is inconsistent.")
            self._validate("workflow_create_run", {key: state[key] for key in ("run_id", "mode", "sources", "units")})
            for key in ("observations", "uncertainties", "drawing", "review", "contract", "events"):
                if key not in state:
                    raise ValueError("Workflow state is incomplete.")
            if not isinstance(state["events"], list) or not state["events"]:
                raise ValueError("Workflow history is missing.")
            for index, event in enumerate(state["events"]):
                if (not isinstance(event, dict) or event.get("state_revision") != index
                        or event.get("tool") not in TOOL_PHASES
                        or (index == 0) != (event["tool"] == "workflow_create_run")
                        or not isinstance(event.get("recorded_at"), str)
                        or not isinstance(event.get("data"), dict)):
                    raise ValueError("Workflow history is inconsistent.")
                event_args = {"run_id": run_id, **event["data"]}
                if index:
                    event_args["expected_state_revision"] = index - 1
                self._validate(event["tool"], event_args)
            if state.get("phase") != TOOL_PHASES[state["events"][-1]["tool"]]:
                raise ValueError("Workflow phase is inconsistent.")
            if state.get("next_phase") != self._next_phase(state):
                raise ValueError("The next workflow phase is inconsistent.")
            # Validate records again after restart. Stored booleans are never gate evidence.
            if state["observations"]:
                self._validate("workflow_observe", {"run_id": run_id, "expected_state_revision": 0,
                    "observations": state["observations"], "uncertainties": state["uncertainties"]})
            elif state["uncertainties"]:
                raise ValueError("Uncertainties require source observations.")
            for key, tool in (("drawing", "workflow_register_drawing"),
                              ("review", "workflow_review_drawing"), ("contract", "workflow_fix_contract")):
                if state[key] is not None:
                    if not isinstance(state[key], dict):
                        raise ValueError("Workflow record must be an object.")
                    record = {field: value for field, value in state[key].items() if key != "contract" or field not in ("sha256", "drawing_ref")}
                    self._validate(tool, {"run_id": run_id, "expected_state_revision": 0, **record})
                    if key == "contract":
                        if state[key].get("sha256") != self._contract_hash(state[key]):
                            raise ValueError("The contract hash is inconsistent.")
            self._verify_history(state)
            return state
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise WorkflowError("STATE_INVALID", "The stored run is incomplete or invalid.") from error

    def _verify_history(self, state):
        first = state["events"][0]["data"]
        projection = {"run_id": state["run_id"], "mode": first["mode"], "units": first["units"],
                      "sources": deepcopy(first["sources"]), "state_revision": 0, "observations": [],
                      "uncertainties": [], "drawing": None, "review": None, "contract": None, "events": []}
        self._unique(projection["sources"], "path", "sources")
        handlers = {"workflow_observe": self._observe, "workflow_register_drawing": self._drawing,
                    "workflow_review_drawing": self._review, "workflow_fix_contract": self._contract}
        for index, event in enumerate(state["events"]):
            if index:
                handler = handlers[event["tool"]]
                if event["tool"] == "workflow_observe":
                    handler(projection, event["data"])
                else:
                    handler(projection, event["data"], verify_artifacts=False)
            projection["state_revision"] = index
            projection["phase"] = TOOL_PHASES[event["tool"]]
            projection["next_phase"] = self._next_phase(projection)
            projection["events"].append(event)
        for key, value in projection.items():
            if key != "events" and state[key] != value:
                raise ValueError("The workflow snapshot differs from its transition history.")
        if (not isinstance(state.get("toolchain"), dict)
                or state["toolchain"].get("cad_backend") is not None
                or not isinstance(state["toolchain"].get("workflow_service"), str)):
            raise ValueError("The workflow toolchain record is invalid.")

    @staticmethod
    def _drawing_ref(drawing):
        return {"drawing_id": drawing["drawing_id"], "revision": drawing["revision"],
                "editable_sha256": drawing["editable"]["sha256"], "render_sha256": drawing["render"]["sha256"]}

    @staticmethod
    def _contract_hash(record):
        payload = {key: record[key] for key in ("revision", "contract", "drawing_ref")}
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

    @staticmethod
    def _next_phase(state):
        if not state["observations"]:
            return "observe"
        if not state["drawing"]:
            return "drawing_prepare"
        if (not state["review"] or any(row["severity"] == "blocking" for row in state["review"]["findings"])
                or WorkflowService._blocking(state)):
            return "drawing_review"
        if not state["contract"]:
            return "freeze"
        return "build"

    def _write(self, state):
        path = self._path(state["run_id"])
        data = json.dumps(state, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
        if len(data) > MAX_STATE_BYTES:
            raise WorkflowError("STATE_LIMIT", "The run exceeds the manifest size limit. Create a new run.")
        descriptor, temporary = tempfile.mkstemp(prefix=".workflow-", suffix=".tmp", dir=self._storage_path())
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self._storage_path()
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _artifact(self, reference, target, *, source=False):
        path = Path(reference["path"]).expanduser()
        if not path.is_absolute():
            raise WorkflowError("ARTIFACT_PATH_INVALID", "Artifact paths must be absolute.")
        path = path.resolve()
        roots = self.allowed_roots if source else (*self.allowed_roots, self.output_root)
        if not any(path.is_relative_to(root) for root in roots):
            raise WorkflowError("ARTIFACT_PATH_FORBIDDEN", "The artifact is outside the authorized roots.")
        try:
            if not path.is_file():
                raise OSError("Artifact is not a regular file.")
            digest = sha256()
            size = 0
            with path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                while chunk := stream.read(1048576):
                    size += len(chunk)
                    if size > MAX_ARTIFACT_BYTES:
                        raise WorkflowError("ARTIFACT_LIMIT", "The artifact exceeds the byte limit.")
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
            if size == 0:
                raise WorkflowError("ARTIFACT_EMPTY", "An evidence artifact must not be empty.")
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise WorkflowError("ARTIFACT_CHANGED", "The artifact changed while its hash was calculated.")
            if digest.hexdigest() != reference["sha256"]:
                raise WorkflowError("SOURCE_HASH_MISMATCH" if source else "ARTIFACT_HASH_MISMATCH",
                    "The actual artifact hash differs from the recorded hash.",
                    [_defect("SOURCE_HASH_MISMATCH" if source else "ARTIFACT_HASH_MISMATCH", target,
                             "The file bytes do not match the recorded evidence.",
                             "Restore the recorded file or register a new revision and repeat dependent reviews.")])
        except OSError as error:
            raise WorkflowError("ARTIFACT_MISSING", "The evidence artifact cannot be read.") from error
        return {"path": str(path), "sha256": reference["sha256"]}

    def _integrity(self, state, *, include_drawing=True):
        defects = []
        for index, source in enumerate(state["sources"]):
            try:
                self._artifact(source, f"sources[{index}]", source=True)
            except WorkflowError as error:
                defects.extend(error.defects)
        if include_drawing and state["drawing"]:
            for role in ("editable", "render"):
                try:
                    self._artifact(state["drawing"][role], "drawing." + role)
                except WorkflowError as error:
                    defects.extend(error.defects)
        return defects

    @staticmethod
    def _blocking(state):
        return [_defect("BLOCKING_UNCERTAINTY", "uncertainties." + item["id"], item["description"],
                        "Resolve the mandatory value or record its existing authorized assumption.")
                for item in state["uncertainties"] if item["mandatory"] and item["status"] == "unresolved"]

    def _prerequisites(self, state, phase, *, verify_artifacts=True):
        defects = self._integrity(state, include_drawing=PHASES.index(phase) >= 2) if verify_artifacts else []
        if not any(source["role"] == "construction_source" for source in state["sources"]):
            defects.append(_defect("CONSTRUCTION_SOURCE_REQUIRED", "sources",
                                   "No construction source is authorized for this run.",
                                   "Create a new run with an explicit authorized construction source."))
        if state["mode"] == "import_step" and phase != "observe":
            defects.append(_defect("MODE_NOT_IMPLEMENTED", "mode", "STEP-only execution is not implemented by this evidence service.",
                                   "Use a separately verified STEP-only adapter. Do not use a drawing as its model input."))
        if PHASES.index(phase) >= 1 and not state["observations"]:
            defects.append(_defect("OBSERVATIONS_REQUIRED", "observations", "Source observations are missing.",
                                   "Record identified observations from the authorized sources."))
        if PHASES.index(phase) >= 2 and not state["drawing"]:
            defects.append(_defect("DRAWING_REQUIRED", "drawing", "The editable technical sheet and render are missing.",
                                   "Register a drawing revision and both actual artifact hashes."))
        if PHASES.index(phase) >= 2:
            defects.extend(self._blocking(state))
        if PHASES.index(phase) >= 3:
            review, drawing = state["review"], state["drawing"]
            if not review:
                defects.append(_defect("DRAWING_REVIEW_REQUIRED", "review", "An identified drawing review is missing.",
                                       "Inspect the exact rendered sheet and record the findings."))
            elif not drawing or (review["drawing_revision"] != drawing["revision"]
                    or review["inspected_render_sha256"] != drawing["render"]["sha256"]):
                defects.append(_defect("DRAWING_REVISION_STALE", "review", "The review does not match the current drawing.",
                                       "Inspect and review the current drawing revision."))
            else:
                defects.extend(_defect("DRAWING_REVIEW_BLOCKED", "review." + row["target"], row["message"], row["required_action"])
                               for row in review["findings"] if row["severity"] == "blocking")
        if PHASES.index(phase) >= 4:
            contract, drawing = state["contract"], state["drawing"]
            if not contract:
                defects.append(_defect("CONTRACT_REQUIRED", "contract", "A fixed declarative contract is missing.",
                                       "Fix a typed contract from the reviewed drawing revision."))
            elif (not drawing or contract["contract"]["drawing_revision"] != drawing["revision"]
                    or contract["drawing_ref"] != self._drawing_ref(drawing)):
                defects.append(_defect("CONTRACT_REVISION_STALE", "contract", "The contract refers to a different drawing revision.",
                                       "Fix a new contract from the current reviewed drawing."))
        if PHASES.index(phase) >= 4:
            defects.append(_defect("CAD_VALIDATION_UNAVAILABLE", phase,
                                   "No verified CAD execution and validation backend is implemented.",
                                   "Provide a tested MCP CAD adapter before build, model comparison, or export."))
        return defects

    @staticmethod
    def _require(defects):
        if defects:
            raise WorkflowError(defects[0]["code"], "The managed evidence gate is blocked.", defects)

    @staticmethod
    def _unique(rows, field, target):
        ids = [row[field] for row in rows]
        if len(ids) != len(set(ids)):
            raise WorkflowError("DUPLICATE_ID", "Identifiers must be unique in " + target + ".")
        return set(ids)

    def _observe(self, state, args):
        observations = args["observations"]
        ids = self._unique(observations, "id", "observations")
        source_hashes = {row["sha256"] for row in state["sources"] if row["role"] == "construction_source"}
        for row in observations:
            if row["source_sha256"] not in source_hashes:
                raise WorkflowError("SOURCE_ROLE_FORBIDDEN", "An observation must refer to an authorized construction source.")
        self._unique(args["uncertainties"], "id", "uncertainties")
        self._unique(args["uncertainties"], "marker_id", "uncertainty markers")
        for row in args["uncertainties"]:
            if not set(row["evidence_ids"]).issubset(ids):
                raise WorkflowError("EVIDENCE_REFERENCE_INVALID", "An uncertainty refers to an unknown observation.")
            if row["status"] == "approved_assumption" and not row.get("decision_ref"):
                raise WorkflowError("DECISION_REFERENCE_REQUIRED", "An approved assumption requires its authorization reference.")
        state["observations"] = deepcopy(observations)
        state["uncertainties"] = deepcopy(args["uncertainties"])
        state["drawing"] = state["review"] = state["contract"] = None

    def _drawing(self, state, args, *, verify_artifacts=True):
        self._require(self._prerequisites(state, "drawing_prepare", verify_artifacts=verify_artifacts))
        if args["units"] != state["units"]:
            raise WorkflowError("UNIT_MISMATCH", "Drawing units must agree with the run units.")
        if any(event["tool"] == "workflow_register_drawing" and event["data"]["revision"] == args["revision"]
               for event in state["events"]):
            raise WorkflowError("REVISION_REUSED", "A drawing revision identifier cannot be reused.")
        editable = self._artifact(args["editable"], "drawing.editable") if verify_artifacts else deepcopy(args["editable"])
        render = self._artifact(args["render"], "drawing.render") if verify_artifacts else deepcopy(args["render"])
        hashes = {source["sha256"] for source in state["sources"]}
        if editable["sha256"] == render["sha256"] or editable["sha256"] in hashes or render["sha256"] in hashes:
            raise WorkflowError("DRAWING_ARTIFACT_NOT_DISTINCT", "The working sheet, render and source must have distinct contents.")
        state["drawing"] = {key: deepcopy(args[key]) for key in ("drawing_id", "revision", "dimension_ids", "units")}
        state["drawing"].update(editable=editable, render=render)
        state["review"] = state["contract"] = None

    def _review(self, state, args, *, verify_artifacts=True):
        self._require(self._prerequisites(state, "drawing_review", verify_artifacts=verify_artifacts))
        drawing = state["drawing"]
        if (args["drawing_revision"] != drawing["revision"]
                or args["inspected_render_sha256"] != drawing["render"]["sha256"]):
            raise WorkflowError("DRAWING_REVISION_STALE", "The review must identify the exact current drawing revision and render.")
        state["review"] = {key: deepcopy(args[key]) for key in
                           ("drawing_revision", "reviewer", "inspected_render_sha256", "findings", "notes")}
        state["contract"] = None

    def _contract(self, state, args, *, verify_artifacts=True):
        self._require(self._prerequisites(state, "freeze", verify_artifacts=verify_artifacts))
        contract = args["contract"]
        if contract["drawing_revision"] != state["drawing"]["revision"]:
            raise WorkflowError("DRAWING_REVISION_STALE", "The contract must identify the reviewed drawing revision.")
        if contract["units"] != state["units"]:
            raise WorkflowError("UNIT_MISMATCH", "Contract units must agree with the drawing units.")
        if any(event["tool"] == "workflow_fix_contract" and event["data"]["revision"] == args["revision"]
               for event in state["events"]):
            raise WorkflowError("REVISION_REUSED", "A contract revision identifier cannot be reused.")
        parameter_ids = self._unique(contract["parameters"], "id", "parameters")
        operation_ids = self._unique(contract["operations"], "id", "operations")
        dimension_ids = set(state["drawing"]["dimension_ids"])
        for parameter in contract["parameters"]:
            if parameter["dimension_id"] not in dimension_ids:
                raise WorkflowError("DIMENSION_MAPPING_INVALID", "A parameter refers to an unknown drawing dimension.")
            if not math.isfinite(parameter["value"]):
                raise WorkflowError("INVALID_ARGUMENTS", "Parameter values must be finite.")
        pending = {}
        for operation in contract["operations"]:
            dependencies = operation["depends_on"]
            if len(dependencies) != len(set(dependencies)) or not set(dependencies).issubset(operation_ids):
                raise WorkflowError("DEPENDENCY_INVALID", "An operation dependency is unknown or repeated.")
            if not set(operation["parameter_ids"]).issubset(parameter_ids):
                raise WorkflowError("PARAMETER_REFERENCE_INVALID", "An operation refers to an unknown parameter.")
            pending[operation["id"]] = set(dependencies)
        completed = set()
        while pending:
            ready = [key for key, dependencies in pending.items() if dependencies.issubset(completed)]
            if not ready:
                raise WorkflowError("OPERATION_CYCLE", "The operation graph contains a cycle.")
            for key in ready:
                completed.add(key)
                del pending[key]
        state["contract"] = {"revision": args["revision"], "contract": deepcopy(contract),
                             "drawing_ref": self._drawing_ref(state["drawing"])}
        state["contract"]["sha256"] = self._contract_hash(state["contract"])

    def call(self, name, args):
        """Execute one finite evidence operation under a cross-process run lock."""
        if name not in WORKFLOW_SCHEMAS:
            raise WorkflowError("UNKNOWN_TOOL", "Unknown workflow tool: " + name)
        self._validate(name, args)
        run_id = args["run_id"]
        reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
        if run_id.split(".", 1)[0].upper() in reserved:
            raise WorkflowError("INVALID_ARGUMENTS", "The run identifier is a reserved Windows file name.")
        with self._lock(run_id):
            if name == "workflow_create_run":
                if self._path(run_id).exists():
                    raise WorkflowError("RUN_EXISTS", "The run identifier already exists.")
                sources = []
                seen = set()
                for index, source in enumerate(args["sources"]):
                    record = self._artifact(source, f"sources[{index}]", source=True)
                    if record["path"] in seen:
                        raise WorkflowError("DUPLICATE_SOURCE", "A source path can have only one source role.")
                    seen.add(record["path"])
                    sources.append({**record, "role": source["role"]})
                state = {"schema_version": 1, "run_id": run_id, "mode": args["mode"], "units": args["units"],
                         "sources": sources, "state_revision": 0, "observations": [], "uncertainties": [],
                         "drawing": None, "review": None, "contract": None, "events": [],
                         "toolchain": {"workflow_service": __version__, "cad_backend": None}}
            else:
                state = self._load(run_id)
                if name == "workflow_read_run":
                    return {"run": state, "integrity_defects": self._integrity(state), **SCOPE}
                if name == "workflow_check_readiness":
                    defects = self._prerequisites(state, args["phase"])
                    return {"run_id": run_id, "state_revision": state["state_revision"], "phase": args["phase"],
                            "ready": not defects, "defects": defects,
                            "next_action": defects[0]["required_action"] if defects else "Record the next managed evidence operation.",
                            **SCOPE}
                if args["expected_state_revision"] != state["state_revision"]:
                    raise WorkflowError("STATE_REVISION_CONFLICT", "The run changed. Read its current state before retrying.")
                self._require(self._integrity(state, include_drawing=name not in ("workflow_observe", "workflow_register_drawing")))
                handlers = {"workflow_observe": self._observe, "workflow_register_drawing": self._drawing,
                            "workflow_review_drawing": self._review, "workflow_fix_contract": self._contract}
                handlers[name](state, args)
                state["state_revision"] += 1
            state["phase"] = TOOL_PHASES[name]
            state["next_phase"] = self._next_phase(state)
            event_data = {key: deepcopy(value) for key, value in args.items()
                          if key not in ("run_id", "expected_state_revision")}
            if name == "workflow_create_run":
                event_data["sources"] = deepcopy(state["sources"])
            elif name == "workflow_register_drawing":
                event_data = deepcopy(state["drawing"])
            state["events"].append({"state_revision": state["state_revision"], "tool": name,
                                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                                    "data": event_data})
            self._write(state)
            result = {"run": state, **SCOPE}
            if state["contract"]:
                result["contract_sha256"] = state["contract"]["sha256"]
            return result
