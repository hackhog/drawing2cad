"""Shared upload, CAD, drawing, artifact, and job application service.

Transport adapters supply a verified AccessContext. Public contracts use source
and artifact IDs. Only maintained adapters resolve those IDs to private paths.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
from copy import deepcopy
import hashlib
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
from tempfile import TemporaryDirectory
from uuid import uuid4

from jsonschema import Draft202012Validator, ValidationError
from pydantic import ValidationError as ModelValidationError

from . import __version__
from .cad_service import CadError, CadService
from .cad_tools import CAD_SCHEMAS
from .domain_jobs import JobCancelled, JobFailed, JobService
from .domain_store import AccessContext, DomainError, DomainStore
from .domain_tools import DOMAIN_SCHEMAS
from .drawing_contract import drawing_schema, drawing_validate
from .measurements_tools import MEASUREMENT_METHODS
from .pdf import MAX_STROKE_LIMIT, PdfError, PdfService
from .part_schema import EdgeSelectionDiagnostic
from .schema_errors import describe as describe_schema_error
from .source_flags import check_decision, review_flags
from .step import StepError, StepService


LOG = logging.getLogger(__name__)
# Host paths in worker messages: Windows drive paths and common POSIX roots.
# JSON Pointers such as /features/0/diameter do not match.
_HOST_PATH = re.compile(r"(?:\b[A-Za-z]:[\\/]|(?<![\w.])/(?:tmp|opt|usr|home|data|var|root|srv|mnt|etc|proc|inputs|app|Users|private|Volumes|Library|System|workspace)/)[^\s'\"<>|,;)]*")
# Read-only run operations. During an active operation they return a consistent snapshot without the run lock.
SNAPSHOT_READS = frozenset({"part_read", "drawing_read", "drawing_validate", "notes_read"})
MAX_PUBLIC_MESSAGE = 4000
# Flags are derived from immutable source bytes. The cache prevents a new analysis for each decision.
FLAG_CACHE_SIZE = 32


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


class DomainService:
    """Use one instance for all adapters in a backend application."""

    def __init__(self, settings):
        self.settings = settings
        root = settings.domain.root or settings.pdf.output_root / "domain"
        self.store = DomainStore(root, settings.domain.max_source_bytes, settings.domain.max_chunk_bytes)
        self._services = {}
        self._services_lock = threading.Lock()
        self._cad_slots = threading.BoundedSemaphore(settings.cad.concurrency)
        self._pdf_slots = threading.BoundedSemaphore(settings.server.pdf_concurrency)
        self._flags = {}
        self.jobs = JobService(self.store.root / "jobs", self._dispatch_job,
                               concurrency=settings.cad.concurrency)

    def start(self):
        self.jobs.start()

    def close(self):
        self.jobs.close()

    def source_delete(self, ctx: AccessContext, source_id: str) -> dict:
        """Delete an uploaded source for a trusted adapter. Not an MCP tool, so an agent cannot remove its input."""
        self.store.namespace_root(ctx)
        return self._public(self.store.source_delete(ctx, source_id))

    def _backend(self, ctx):
        namespace = self.store.namespace_root(ctx)
        with self._services_lock:
            if ctx.subject not in self._services:
                output = namespace / "execution"
                pdf = self.settings.pdf
                self._services[ctx.subject] = (
                    CadService([namespace], output, self.settings.cad),
                    PdfService((namespace,), output / "pdf", pdf.pdftoppm, pdf.timeout_seconds,
                               min(pdf.max_pdf_bytes, self.store.max_source_bytes), pdf.max_pixels),
                    StepService([namespace], output / "step", self.settings.server.max_step_bytes),
                )
            return self._services[ctx.subject]

    @contextmanager
    def _run_lock(self, ctx, run_id, wait_seconds=10):
        """Serialize domain operations across processes without nesting CAD locks."""
        cad = self._backend(ctx)[0]
        directory = cad._directory(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "domain.lock"
        self.store._check_path(path)
        with path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if not stream.tell():
                stream.write(b"0")
                stream.flush()
            deadline = time.monotonic() + wait_seconds
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
                except OSError:
                    if time.monotonic() >= deadline:
                        raise DomainError("RUN_BUSY", "Another operation holds this run.") from None
                    time.sleep(0.02)
            try:
                yield cad, directory
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _state(self, cad, directory, expected_revision=None):
        if not (directory / "state.json").is_file():
            raise DomainError("NOT_FOUND", "The requested run does not exist.")
        state = cad._load(directory)
        if expected_revision is not None and state["revision"] != expected_revision:
            raise DomainError("REVISION_CONFLICT", "Read the current part revision before this operation.")
        return state

    def _redact(self, text):
        """Return a bounded message without storage roots or other host paths."""
        # Resolved roots can differ from configured ones, e.g. /private/var and /var on macOS. Longest first.
        roots = {path for root in (self.store.root, self.settings.pdf.output_root) for path in (root, root.resolve())}
        for root in sorted(roots, key=lambda path: len(str(path)), reverse=True):
            text = text.replace(str(root), "[private storage]").replace(root.as_posix(), "[private storage]")
        return _HOST_PATH.sub("[path]", text)[:MAX_PUBLIC_MESSAGE]

    def _public(self, value):
        """Remove private locations and process output from transport results."""
        private = {"path", "work_dir", "candidate_step", "logs", "stdout", "stderr", "traceback"}
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key in private or key.endswith("_path"):
                    continue
                if key == "error" and item is not None:
                    # Keep the code, the redacted message, and the feature ID, so that an agent can correct the input.
                    item = item if isinstance(item, dict) else {}
                    message = item.get("message")
                    error = {"code": str(item.get("code", "OPERATION_FAILED")),
                             "message": self._redact(message) if isinstance(message, str) and message
                             else "The operation reported an error. Inspect its code and check results."}
                    if isinstance(item.get("feature_id"), str):
                        error["feature_id"] = item["feature_id"]
                    if error["code"] == "EDGE_SELECTION" and item.get("details") is not None:
                        try:
                            error["details"] = EdgeSelectionDiagnostic.model_validate(item["details"]).model_dump(mode="json")
                        except ModelValidationError:
                            # Reject the whole diagnostic if it includes private or unsupported data.
                            pass
                    result[key] = error
                else:
                    result[key] = self._public(item)
            return result
        if isinstance(value, list):
            return [self._public(item) for item in value]
        if isinstance(value, str):
            for root in (self.store.root, self.settings.pdf.output_root):
                value = value.replace(str(root), "[private storage]").replace(root.as_posix(), "[private storage]")
            return value
        return value

    @staticmethod
    def _validate(name, arguments, prefix=""):
        if name not in DOMAIN_SCHEMAS:
            raise DomainError("UNKNOWN_TOOL", "The domain operation is not supported.")
        try:
            Draft202012Validator(DOMAIN_SCHEMAS[name]).validate(arguments)
            encoded = _json(arguments)
            if len(encoded) > 8 * 1024 * 1024:
                raise DomainError("LIMIT_EXCEEDED", "The request exceeds the domain size limit.")
        except ValidationError as error:
            # The JSON Pointer and the failed schema rule tell the agent which field to correct.
            # The message never repeats the input value, because it can be private.
            target, message = describe_schema_error(error, prefix)
            raise DomainError("INVALID_ARGUMENT", "The arguments do not match the tool contract. " + message,
                              target=target, next_action=f"Read the input schema of {name} and correct the field at the target.") from None
        except (ValueError, TypeError, RecursionError):
            raise DomainError("INVALID_ARGUMENT", "The arguments do not match the tool contract.") from None

    def call(self, ctx: AccessContext, name: str, arguments: dict):
        self.store.namespace_root(ctx)
        self._validate(name, arguments)
        try:
            return self._public(self._call(ctx, name, deepcopy(arguments)))
        except DomainError:
            raise
        except CadError as error:
            message = error.message if error.code != "CAD_SERVICE_FAILED" else "The CAD operation failed."
            raise DomainError(error.code, self._redact(message)) from None
        except StepError as error:
            raise DomainError(error.code, "The STEP inspection failed. Check the artifact and expected hash.") from None
        except PdfError as error:
            LOG.warning("PDF operation %s failed: %s", name, self._redact(str(error)))
            raise DomainError("PDF_PREPARATION_FAILED", "The uploaded PDF could not be prepared with the requested options.",
                              next_action="Inspect the server diagnostic. Use PDF image tools if the vector profile does not support this page.") from None
        except Exception:
            LOG.exception("Domain operation %s failed", name)
            raise DomainError("DOMAIN_OPERATION_FAILED", "The domain operation failed. No private process details are returned.") from None

    def _call(self, ctx, name, args):
        if name == "domain_schema":
            from .domain_contracts import domain_schema
            return domain_schema()
        if name.startswith("upload_") or name in {"source_get", "source_list", "artifact_get", "artifact_list", "artifact_read"}:
            return getattr(self.store, name)(ctx, **args)
        if name in {"job_get", "job_cancel"}:
            return getattr(self.jobs, name.removeprefix("job_"))(ctx, **args)
        if name == "job_list":
            return {"items": self.jobs.list(ctx, **args)}
        if name == "job_submit":
            operation, operation_args = args["operation"], args["arguments"]
            # The nested arguments are a separate request; the pointer still names the field of job_submit.
            self._validate(operation, operation_args, "/arguments")
            with self._run_lock(ctx, operation_args["run_id"]) as (cad, directory):
                self._state(cad, directory, operation_args["expected_revision"])
                return self.jobs.submit(ctx, operation, operation_args, args["idempotency_key"])
        if name == "artifact_preview":
            with self._pdf_slots:
                return self._artifact_preview(ctx, args)
        if name.startswith("source_flags_"):
            return self._source_flags(ctx, name, args)
        if name.startswith("pdf_") or name == "drawing_extract":
            with self._pdf_slots:
                return self._pdf_call(ctx, name, args)
        if name == "step_reconstruct":
            with self._cad_slots:
                return self._reconstruct_step(ctx, args)
        if name == "step_render_pmi":
            with self._cad_slots:
                return self._step_visual(ctx, args)
        if name.startswith("step_"):
            return self._step_call(ctx, name, args)
        if name == "drawing_schema":
            return drawing_schema()
        cad = self._backend(ctx)[0]
        if name in {"part_schema", "pmi_schema", "part_validate", "cad_worker_probe"}:
            if name == "cad_worker_probe":
                with self._cad_slots:
                    return cad.call(name, args)
            return cad.call(name, args)
        if name in {"build_from_description", "build_code", "drawing_render", "export_step", "part_render_pmi"}:
            with self._cad_slots:
                return self._run_call(ctx, name, args)
        return self._run_call(ctx, name, args)

    def _dispatch_job(self, ctx, operation, arguments, cancel_event):
        if cancel_event.is_set():
            raise JobCancelled()
        # call() repeats schema, ownership, and revision checks after queue delay.
        # Once execution starts, the actual result is recorded even if cancelled.
        result = self.call(ctx, operation, arguments)
        if result.get("status") == "fail":
            # Keep the public report, for example the defects of a failed drawing validation, in the job record.
            raise JobFailed("JOB_OPERATION_FAILED", "The operation failed its checks. Read the job result for its report.", result)
        return result

    def _preview(self, path):
        from PIL import Image
        with Image.open(path) as original:
            image = original.copy()
        try:
            max_pixels = self.settings.server.preview_max_pixels
            ratio = min(1, (max_pixels / (image.width * image.height)) ** 0.5)
            if ratio < 1:
                image.thumbnail((max(1, int(image.width * ratio)), max(1, int(image.height * ratio))))
            for _ in range(12):
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                if len(buffer.getvalue()) <= self.settings.server.preview_max_bytes:
                    return {"mime_type": "image/png", "data_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
                            "width_pixels": image.width, "height_pixels": image.height}
                image.thumbnail((max(1, image.width // 2), max(1, image.height // 2)))
            return {"status": "unavailable", "reason": "The preview exceeds the configured limit."}
        finally:
            image.close()

    def _pdf_call(self, ctx, name, args):
        source_id = args.pop("source_id")
        source = self.store.source_get(ctx, source_id)
        path = self.store.source_path(ctx, source_id)
        preview = args.pop("include_image", True)
        methods = {"pdf_info": "info", "pdf_read_text": "read_text", "pdf_render_page": "render_page",
                   "pdf_crop_region": "crop_region", "drawing_extract": "extract_drawing", **MEASUREMENT_METHODS}
        result = getattr(self._backend(ctx)[1], methods[name])(path=path, **args)
        self.store.source_path(ctx, source_id)
        if result.get("source", {}).get("sha256", source["sha256"]) != source["sha256"]:
            raise DomainError("SOURCE_HASH_MISMATCH", "The PDF preparation used different source bytes.")
        result["source"] = source
        if name == "pdf_read_text":
            for found in result["tolerance_candidates"]:
                found["source"]["source_id"] = source_id
                found["source"]["source_sha256"] = source["sha256"]
        if "artifact" in result:
            internal = result["artifact"]
            result["artifact"] = self.store.artifact_register(ctx, internal["path"], "source_preview", source_id,
                                                              0, "image/png", Path(internal["path"]).name)
            if preview:
                result["preview"] = self._preview(internal["path"])
        return result

    def _page_flags(self, ctx, source_id, page):
        """Flags of a source page and the unclear strokes by ID, from the cache or a new analysis."""
        source = self.store.source_get(ctx, source_id)
        key = (ctx.subject, source["sha256"], page)
        with self._services_lock:
            cached = self._flags.get(key)
        if cached is None:
            with self._pdf_slots:
                # Flags need only the unclear strokes, so one page of strokes holds all of them.
                drawing = self._pdf_call(ctx, "drawing_extract", {"source_id": source_id, "page": page, "include_strokes": True,
                                                                  "stroke_kinds": ["unclear"], "stroke_limit": MAX_STROKE_LIMIT})
            if drawing["strokes_page"]["next_offset"] is not None:
                raise DomainError("LIMIT_EXCEEDED", f"The page has more than {MAX_STROKE_LIMIT} unclear strokes.")
            cached = (review_flags(drawing), {s["id"]: s for s in drawing["strokes"]})
            with self._services_lock:
                self._flags[key] = cached
                while len(self._flags) > FLAG_CACHE_SIZE:
                    self._flags.pop(next(iter(self._flags)))
        return source, deepcopy(cached[0]), cached[1]

    def _flags_view(self, ctx, source_id, page):
        source, flags, _ = self._page_flags(ctx, source_id, page)
        decisions = {d["flag_id"]: d for d in self.store.flag_decisions(ctx, source_id, page)}
        for flag in flags:
            flag["decision"] = decisions.pop(flag["flag_id"], None)
        # A decision without a current flag shows that the analysis now explains the location.
        return {"source": source, "page": page, "analysis_version": __version__, "flags": flags,
                "decisions_without_flag": list(decisions.values())}

    def _source_flags(self, ctx, name, args):
        if name == "source_flags_export":
            names = {}
            decisions = []
            for decision in self.store.flag_decisions(ctx):
                if decision["source_id"] not in names:
                    names[decision["source_id"]] = self.store.source_get(ctx, decision["source_id"])["filename"]
                decisions.append({**decision, "filename": names[decision["source_id"]]})
            return {"schema_version": 1, "analysis_version": __version__, "exported_at": time.time(), "decisions": decisions}
        source_id, page = args["source_id"], args.get("page", 1)
        if name == "source_flags_read":
            return self._flags_view(ctx, source_id, page)
        if args["action"] == "reopen":
            self.store.flag_decision_set(ctx, source_id, page, args["flag_id"], None)
            return self._flags_view(ctx, source_id, page)
        source, flags, unclear = self._page_flags(ctx, source_id, page)
        flag = next((f for f in flags if f["flag_id"] == args["flag_id"]), None)
        if flag is None:
            raise DomainError("NOT_FOUND", "The flag does not exist on this source page.", "flag_id",
                              next_action="Read source_flags_read and use a current flag ID.")
        reason = check_decision(flag, args["action"], args.get("stroke_class"), args.get("text"))
        if reason:
            raise DomainError("INVALID_ARGUMENT", reason, "action")
        # The decision keeps the flag and its stroke geometry, so the feedback export is complete without the PDF.
        self.store.flag_decision_set(ctx, source_id, page, flag["flag_id"], {
            "action": args["action"], "stroke_class": args.get("stroke_class"), "text": args.get("text"),
            "note": args.get("note") or None, "reviewer": args.get("reviewer"), "decided_at": time.time(),
            "source_sha256": source["sha256"], "analysis_version": __version__,
            "flag": {**flag, "strokes": [unclear[i] for i in flag["stroke_ids"]]}})
        return self._flags_view(ctx, source_id, page)

    def _artifact_preview(self, ctx, args):
        metadata = self.store.artifact_get(ctx, args["artifact_id"])
        source = self.store._path(ctx, "artifacts", args["artifact_id"])
        self.store._verify(source, metadata["size_bytes"], metadata["sha256"])
        if metadata["media_type"] == "image/png":
            if args.get("page", 1) != 1:
                raise DomainError("INVALID_ARGUMENT", "A PNG artifact has one page.")
            result = {"artifact": metadata}
            if args.get("include_image", True):
                result["preview"] = self._preview(source)
            return result
        if metadata["media_type"] != "application/pdf":
            raise DomainError("INVALID_ARTIFACT_TYPE", "Preview supports PDF and PNG artifacts.")
        if metadata["size_bytes"] > min(self.settings.pdf.max_pdf_bytes, self.store.max_source_bytes):
            raise DomainError("LIMIT_EXCEEDED", "The PDF artifact exceeds the preparation byte limit.")
        parent = self.store.namespace_root(ctx) / "inspection"
        self.store._check_path(parent)
        parent.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix="preview-", dir=parent) as temporary:
            snapshot = Path(temporary) / "drawing.pdf"
            CadService._atomic(snapshot, source.read_bytes())
            result = self._backend(ctx)[1].render_page(snapshot, page=args.get("page", 1), dpi=args.get("dpi", 150))
        internal = result.pop("artifact")
        result.pop("source", None)
        result["source_artifact"] = metadata
        result["artifact"] = self.store.artifact_register(ctx, internal["path"], "artifact_preview", metadata["run_id"],
                                                          metadata["revision"], "image/png", Path(internal["path"]).name)
        if args.get("include_image", True):
            result["preview"] = self._preview(internal["path"])
        return result

    def _step_call(self, ctx, name, args):
        artifact_id = args.pop("artifact_id")
        metadata = self.store.artifact_get(ctx, artifact_id)
        if metadata["sha256"] != args["expected_sha256"].lower():
            raise DomainError("ARTIFACT_HASH_MISMATCH", "The artifact differs from the expected hash.")
        if metadata["media_type"] != "model/step":
            raise DomainError("INVALID_ARTIFACT_TYPE", "Use a STEP artifact for this operation.")
        if metadata["size_bytes"] > self.settings.server.max_step_bytes:
            raise DomainError("LIMIT_EXCEEDED", "The STEP artifact exceeds the inspection byte limit.")
        source = self.store._path(ctx, "artifacts", artifact_id)
        self.store._verify(source, metadata["size_bytes"], metadata["sha256"])
        parent = self.store.namespace_root(ctx) / "inspection"
        self.store._check_path(parent)
        parent.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix="step-", dir=parent) as temporary:
            snapshot = Path(temporary) / "part.step"
            CadService._atomic(snapshot, source.read_bytes())
            result = self._backend(ctx)[2].call(name, {"path": str(snapshot), **args})
        result["artifact_id"] = artifact_id
        return result

    def _reconstruct_step(self, ctx, args):
        """Keep STEP-only replay separate from an approved drawing/model release."""
        cad = self._backend(ctx)[0]
        if not self.settings.cad.enabled:
            raise DomainError("CAD_DISABLED", "Enable the CAD worker before reconstruction.")
        metadata = self.store.artifact_get(ctx, args["artifact_id"])
        if metadata["sha256"] != args["expected_sha256"]:
            raise DomainError("ARTIFACT_HASH_MISMATCH", "The artifact differs from the expected hash.")
        if metadata["media_type"] != "model/step":
            raise DomainError("INVALID_ARTIFACT_TYPE", "Use a STEP artifact for reconstruction.")
        if metadata["size_bytes"] > min(self.settings.server.max_step_bytes, 32 * 1024 * 1024):
            raise DomainError("LIMIT_EXCEEDED", "The STEP artifact exceeds the reconstruction limit.")
        source = self.store._path(ctx, "artifacts", args["artifact_id"])
        self.store._verify(source, metadata["size_bytes"], metadata["sha256"])
        result = cad.runner.run("reconstruct_step", input_step=source,
                                parameter_changes=args.get("parameter_changes"))
        self.store._verify(source, metadata["size_bytes"], metadata["sha256"])
        report = {"status": "fail", "source_artifact_id": args["artifact_id"],
                  "input_sha256": metadata["sha256"], "released": False,
                  "scope": "Application-specific STEP-only adapter replay. No drawing release, native target-CAD feature tree, or full EXPRESS conformance claim.",
                  "reconstruction": result, "validation": {"status": "not_tested"}}
        if result.get("status") != "pass":
            return report
        if result.get("input_sha256") != metadata["sha256"]:
            raise DomainError("RECONSTRUCTION_HASH_MISMATCH", "Reconstruction used different STEP bytes.")
        if result.get("construction", {}).get("original_agreement") != "pass":
            raise DomainError("CONSTRUCTION_AGREEMENT_REQUIRED", "The embedded construction must match the input BREP before edits.")
        candidate = cad._candidate(result)
        candidate_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
        validation = cad.runner.run("validate", input_step=candidate, description=result["description"])
        report["validation"] = validation
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != candidate_hash:
            raise DomainError("CANDIDATE_CHANGED", "The reconstructed candidate changed during validation.")
        if validation.get("status") != "pass":
            return report
        if validation.get("step", {}).get("sha256") != candidate_hash:
            raise DomainError("VALIDATION_HASH_MISMATCH", "Validation used different candidate bytes.")
        workers = [item.get("worker", {}).get("worker_id") for item in (result, validation)]
        if not all(workers) or workers[0] == workers[1]:
            raise DomainError("FRESH_WORKER_REQUIRED", "Reconstruction and validation require different workers.")
        agreement = cad._compare(result.get("measured", {}), validation.get("measured", {}))
        report["agreement"] = agreement
        if agreement["status"] != "pass":
            return report
        # A replay has its own identity. It must not impersonate the source run revision.
        replay_id = "replay_" + uuid4().hex
        parent = self.store.namespace_root(ctx) / "inspection"
        self.store._check_path(parent)
        parent.mkdir(exist_ok=True)
        report.update(status="pass", replay_id=replay_id, candidate_sha256=candidate_hash)
        report["artifacts"] = [
            self.store.artifact_register(ctx, candidate, "reconstruction_candidate", replay_id, 0,
                                         "model/step", "reconstructed.step"),
            self._register_json(ctx, parent, result["description"], "reconstructed-part.json",
                                "reconstruction_description", replay_id, 0),
        ]
        report["artifacts"].append(self._register_json(ctx, parent, report, "reconstruction-report.json",
                                                       "reconstruction_report", replay_id, 0))
        return report

    def _step_visual(self, ctx, args):
        metadata = self.store.artifact_get(ctx, args["artifact_id"])
        if metadata["sha256"] != args["expected_sha256"]:
            raise DomainError("ARTIFACT_HASH_MISMATCH", "The artifact differs from the expected hash.")
        if metadata["media_type"] != "model/step":
            raise DomainError("INVALID_ARTIFACT_TYPE", "Use a STEP artifact for PMI inspection.")
        source = self.store._path(ctx, "artifacts", args["artifact_id"])
        self.store._verify(source, metadata["size_bytes"], metadata["sha256"])
        return self._visual(ctx, self._backend(ctx)[0], source, metadata["sha256"],
                            metadata["run_id"], metadata["revision"],
                            {"source_artifact_id": metadata["artifact_id"]})

    def _part_visual(self, ctx, cad, state):
        built = state.get("build") or {}
        if (built.get("status") != "pass" or built.get("description_revision") != state["revision"]
                or built.get("description_sha256") != state["description_sha256"]):
            raise DomainError("VALIDATED_BUILD_REQUIRED", "Build and validate the current part before PMI inspection.")
        if built.get("export_profile") != "ap242":
            raise DomainError("AP242_PROFILE_REQUIRED", "PMI inspection requires an AP242 build.")
        source = cad._candidate(built["build"])
        if str(source) != built.get("candidate_path"):
            raise DomainError("CANDIDATE_CHANGED", "The current build candidate path differs from its record.")
        if hashlib.sha256(source.read_bytes()).hexdigest() != built["candidate_sha256"]:
            raise DomainError("CANDIDATE_CHANGED", "The current build candidate bytes changed.")
        return self._visual(ctx, cad, source, built["candidate_sha256"], state["run_id"], state["revision"],
                            {"candidate_sha256": built["candidate_sha256"],
                             "description_sha256": state["description_sha256"], "released": False})

    def _visual(self, ctx, cad, source, source_hash, run_id, revision, binding):
        """Publish only fixed, hash-checked outputs from the restricted reader."""
        if not self.settings.cad.enabled:
            raise DomainError("CAD_DISABLED", "Enable the restricted worker before PMI inspection.")
        source_bytes = source.stat().st_size
        if source_bytes > min(self.settings.server.max_step_bytes, 32 * 1024 * 1024):
            raise DomainError("LIMIT_EXCEEDED", "The STEP exceeds the PMI inspection limit.")
        self.store._verify(source, source_bytes, source_hash)
        result = cad.runner.run("ap242_visual", input_step=source)
        self.store._verify(source, source_bytes, source_hash)
        report = {"status": "fail", "run_id": run_id, "revision": revision,
                  "source_sha256": source_hash, **binding, "inspection": self._public(result)}
        report["inspection"].pop("artifacts", None)
        if result.get("status") != "pass":
            return report
        if result.get("source_sha256") != source_hash or result.get("source_bytes") != source_bytes:
            raise DomainError("INSPECTION_HASH_MISMATCH", "PMI inspection used different STEP bytes.")
        workdir = Path(result.get("worker", {}).get("work_dir", ""))
        if (not workdir.is_absolute() or workdir.parent != Path(cad.runner.storage).resolve()
                or workdir.resolve() != workdir):
            raise DomainError("INVALID_WORKER_ARTIFACT", "The PMI worker directory is invalid.")
        expected_files = [("ap242-inspection.pdf", "application/pdf", "ap242_visual_inspection", 32 * 1024 * 1024),
                          ("ap242-inspection.png", "image/png", "ap242_visual_overview", 8 * 1024 * 1024),
                          ("ap242-inspection-detail.png", "image/png", "ap242_visual_detail", 8 * 1024 * 1024)]
        outputs = result.get("artifacts", [])
        if len(outputs) != len(expected_files):
            raise DomainError("INVALID_WORKER_ARTIFACT", "The PMI worker did not return all inspection artifacts.")
        verified = []
        for filename, media, role, limit in expected_files:
            path = workdir / filename
            self.store._check_path(path)
            item = next((item for item in outputs if item.get("path") == str(path)), None)
            if (not item or item.get("media_type") != media or item.get("role") != role
                    or not isinstance(item.get("bytes"), int) or not 0 < item["bytes"] <= limit):
                raise DomainError("INVALID_WORKER_ARTIFACT", "The PMI worker did not return bounded fixed artifact paths.")
            self.store._verify(path, item["bytes"], item["sha256"])
            verified.append((path, media, role, filename))
        report["artifacts"] = [self.store.artifact_register(ctx, path, role, run_id, revision, media, filename)
                               for path, media, role, filename in verified]
        report["status"] = "pass"
        report["artifacts"].append(self._register_json(ctx, workdir, report, "ap242-inspection-report.json",
                                                       "ap242_visual_report", run_id, revision))
        return report

    @staticmethod
    def _drawing_path(directory):
        return directory / "drawing-state.json"

    def _drawing(self, directory, state):
        path = self._drawing_path(directory)
        self.store._check_path(path)
        if not path.is_file():
            return None
        if path.stat().st_size > 4 * 1024 * 1024:
            raise DomainError("DRAWING_STATE_INVALID", "The stored drawing state exceeds its limit.")
        drawing = json.loads(path.read_text(encoding="utf-8"))
        if drawing["part_revision"] != state["revision"] or drawing["description_sha256"] != state["description_sha256"]:
            return None
        return drawing

    def _save_drawing(self, directory, drawing):
        CadService._atomic(self._drawing_path(directory), _json(drawing))

    def _register_json(self, ctx, directory, value, filename, role, run_id, revision):
        path = directory / (uuid4().hex + "-" + filename)
        CadService._atomic(path, _json(self._public(value)))
        return self.store.artifact_register(ctx, path, role, run_id, revision, "application/json", filename)

    def _notes(self, ctx, run_id):
        try:
            return self.store.notes_read(ctx, run_id)
        except DomainError as error:
            if error.code != "NOT_FOUND":
                raise
            return {"run_id": run_id, "revision": 0, "text": ""}

    def _invalidate_release(self, cad, run_id):
        with cad._lock(run_id) as directory:
            state = cad._load(directory)
            state["release"] = None
            state["source_review"] = None
            cad._save(directory, state)

    @staticmethod
    def _release_is_current(state):
        """A release is current when it belongs to the current validated model build.
        The drawing does not gate the STEP release; the release records the drawing status separately."""
        release = state.get("release") or {}
        build = state.get("build") or {}
        return bool(release.get("artifact") and release.get("sha256") == build.get("candidate_sha256")
                    and release.get("description_revision") == state.get("revision"))

    @staticmethod
    def _drawing_status(drawing, state):
        """Summarize the technical drawing for a release record.
        States: accepted, unreviewed, rejected, failed, or missing (with a reason)."""
        if not drawing:
            return {"status": "missing", "drawing_sha256": None, "artifacts": [],
                    "reason": "No technical drawing was rendered for the current part revision."}
        summary = {"drawing_sha256": drawing["drawing_sha256"], "artifacts": deepcopy(drawing.get("artifacts", []))}
        if drawing.get("status") != "pass":
            report = drawing.get("report") or {}
            return {**summary, "status": "failed", "defects": deepcopy(report.get("defects", [])),
                    "reason": "The latest drawing render did not pass its checks. The artifacts are diagnostic files, not an accepted drawing."}
        review = drawing.get("review") or {}
        candidate = (state.get("build") or {}).get("candidate_sha256")
        if review.get("decision") == "accepted" and review.get("candidate_sha256") == candidate:
            return {**summary, "status": "accepted", "review": deepcopy(review)}
        if review.get("decision") == "rejected" and review.get("candidate_sha256") == candidate:
            return {**summary, "status": "rejected", "review": deepcopy(review),
                    "reason": "The drawing review rejected the drawing for the current model."}
        return {**summary, "status": "unreviewed",
                "reason": "The drawing rendered and passed its checks, but it has no review for the current model."}

    def _release_view(self, state, drawing):
        """Return the release with the current drawing status. Hide a release that is not current."""
        release = state.get("release")
        if not release or not self._release_is_current(state):
            return None
        release = deepcopy(release)
        recorded = release.get("drawing") or {}
        current = self._drawing_status(drawing, state)
        release["drawing_current"] = (recorded.get("status") == current["status"]
                                      and recorded.get("drawing_sha256") == current["drawing_sha256"])
        return release

    def _snapshot_read(self, ctx, name, args):
        """Read a run without its lock while another operation, for example a job, holds it.

        State files are replaced atomically, so each read gives one complete revision.
        """
        cad = self._backend(ctx)[0]
        directory = cad._directory(args["run_id"])
        if name == "notes_read":
            return self._notes(ctx, args["run_id"])
        state = self._state(cad, directory, args.get("expected_revision"))
        if name == "drawing_read":
            result = {"run_id": args["run_id"], "revision": state["revision"], "drawing": self._drawing(directory, state)}
        elif name == "drawing_validate":
            result = drawing_validate(args["drawing_spec"], state["description"], state["revision"])
            result.pop("resolved", None)
        else:
            result = {"status": "pass", "part": deepcopy(state), "run_id": args["run_id"], "revision": state["revision"],
                      "call_count": state["call_count"], "step_budget": state["step_budget"]}
            result["drawing"] = self._drawing(directory, state)
            result["part"]["release"] = self._release_view(result["part"], result["drawing"])
        result["read_mode"] = "snapshot_during_active_operation"
        return result

    def _run_call(self, ctx, name, args):
        if name in SNAPSHOT_READS:
            try:
                with self._run_lock(ctx, args["run_id"], wait_seconds=0.2) as (cad, directory):
                    return self._run_operation(ctx, name, args, cad, directory)
            except (DomainError, CadError) as error:
                if error.code != "RUN_BUSY":
                    raise
            return self._snapshot_read(ctx, name, args)
        with self._run_lock(ctx, args["run_id"]) as (cad, directory):
            # Record domain mutations separately from the existing CAD trace.
            # Read-only calls do not consume an unbounded audit log.
            record = name not in {"part_read", "drawing_read", "drawing_validate", "notes_read", "part_export_review"}
            events = directory / "domain-events"
            if record:
                self.store._check_path(events)
                events.mkdir(exist_ok=True)
                if sum(1 for _ in events.glob("*.json")) >= 1000:
                    raise DomainError("AUDIT_LIMIT", "The run reached its domain mutation limit.")
            event = {"operation": name, "request": self._public(args), "request_sha256": _digest(self._public(args)),
                     "started_at": time.time(), "status": "interrupted", "scope": "domain_run_operation"}
            event_path = events / (str(time.time_ns()) + "-" + uuid4().hex + ".json")
            if record:
                CadService._atomic(event_path, _json(event))
            try:
                result = self._run_operation(ctx, name, args, cad, directory)
                event.update(status=result.get("status", "pass"), result_sha256=_digest(self._public(result)), finished_at=time.time())
                if name in {"drawing_review", "drawing_render", "export_step"}:
                    drawing = result.get("drawing") or {}
                    event.update(drawing_sha256=drawing.get("drawing_sha256"),
                                 artifacts=self._public(drawing.get("artifacts", [])), review=self._public(drawing.get("review")))
                if name == "part_render_pmi":
                    event.update(source_sha256=result.get("source_sha256"), artifacts=result.get("artifacts", []))
                if record:
                    CadService._atomic(event_path, _json(event))
                return result
            except (DomainError, CadError) as error:
                if record:
                    event.update(status="fail", error={"code": error.code}, finished_at=time.time())
                    CadService._atomic(event_path, _json(event))
                raise

    def _run_operation(self, ctx, name, args, cad, directory):
        if name == "part_create":
            for source in args["sources"]:
                metadata = self.store.source_get(ctx, source["source_id"])
                if metadata["sha256"] != source["sha256"]:
                    raise DomainError("SOURCE_HASH_MISMATCH", "The source differs from its expected hash.")
                source["path"] = str(self.store.source_path(ctx, source["source_id"]))
            return cad.call(name, args)
        state = self._state(cad, directory, None if name.startswith("notes_") else args.get("expected_revision"))
        if name == "notes_read":
            return self._notes(ctx, args["run_id"])
        if name == "notes_update":
            return getattr(self.store, name)(ctx, **args)
        if name == "drawing_read":
            return {"run_id": args["run_id"], "revision": state["revision"], "drawing": self._drawing(directory, state)}
        if name == "drawing_validate":
            report = drawing_validate(args["drawing_spec"], state["description"], state["revision"])
            report.pop("resolved", None)
            return report
        if name == "drawing_render":
            return self._render(ctx, cad, directory, state, args["drawing_spec"])
        if name == "part_render_pmi":
            return self._part_visual(ctx, cad, state)
        if name == "drawing_review":
            return self._review(ctx, cad, directory, state, args)
        if name == "part_export_review":
            return self._export_review(ctx, cad, directory, state)
        if name == "export_step":
            # The model validation gates the release. The drawing status is recorded, not required.
            drawing = self._drawing(directory, state)
            drawing_status = self._drawing_status(drawing, state)
            for artifact in drawing_status["artifacts"]:
                self.store.artifact_read(ctx, artifact["artifact_id"], length=1)
            result = cad.call(name, args)
            if result.get("status") == "pass":
                release = result["release"]
                artifact = self.store.artifact_register(ctx, release["path"], "released_step", args["run_id"],
                                                        state["revision"], "model/step", Path(release["path"]).name)
                result["release"]["artifact"] = artifact
                result["release"]["drawing"] = drawing_status
                with cad._lock(args["run_id"]) as saved_directory:
                    saved = cad._load(saved_directory)
                    saved["release"]["artifact"] = artifact
                    saved["release"]["drawing"] = drawing_status
                    cad._save(saved_directory, saved)
                result["drawing"] = drawing
            return result
        if name not in CAD_SCHEMAS:
            raise DomainError("UNKNOWN_TOOL", "The run operation is not supported.")
        if name in {"build_from_description", "build_code"}:
            # A rejected build must keep the current build, release, and drawing review.
            cad.check_build(name, args, state)
            self._invalidate_release(cad, state["run_id"])
            drawing = self._drawing(directory, state)
            if drawing:
                drawing["review"] = None
                self._save_drawing(directory, drawing)
        result = cad.call(name, args)
        if name == "part_read":
            result["drawing"] = self._drawing(directory, state)
            result["part"]["release"] = self._release_view(result["part"], result["drawing"])
        return result

    def _render(self, ctx, cad, directory, state, spec):
        if not self.settings.cad.enabled:
            raise DomainError("CAD_DISABLED", "Enable the restricted worker before drawing creation.")
        report = drawing_validate(spec, state["description"], state["revision"])
        if report["status"] != "pass" and not report.get("diagnostic_eligible"):
            report.pop("resolved", None)
            return report
        # Replace the drawing state first, including when the worker fails or the process exits.
        # A new drawing does not invalidate a STEP release; the release keeps its recorded drawing status.
        drawing = {"part_revision": state["revision"], "description_sha256": state["description_sha256"],
                   "drawing_sha256": _digest(spec), "status": "not_tested", "review": None, "artifacts": [], "spec": spec}
        self._save_drawing(directory, drawing)
        for source in state["sources"]:
            self.store.source_path(ctx, source["source_id"])
        result = cad.runner.run("drawing", drawing_spec=spec, description=state["description"], revision=state["revision"])
        if result.get("status") != "pass":
            drawing.update(status="fail", report=self._public(result))
            if result.get("diagnostic_only") is True:
                expected_binding = {"part_revision": state["revision"], "description_sha256": state["description_sha256"],
                                    "drawing_sha256": drawing["drawing_sha256"]}
                if any(result.get(key) != value for key, value in expected_binding.items()):
                    raise DomainError("INVALID_WORKER_ARTIFACT", "The diagnostic does not match the current drawing binding.")
                files = self._drawing_worker_files(cad, result, (
                    ("drawing-diagnostic.pdf", "application/pdf", "drawing_diagnostic_preview"),
                    ("drawing-diagnostic.json", "application/json", "drawing_diagnostic_report")))
                report_path = files[1][0]
                if report_path.stat().st_size > 4 * 1024 * 1024:
                    raise DomainError("INVALID_WORKER_ARTIFACT", "The diagnostic report exceeds its size limit.")
                try:
                    diagnostic = json.loads(report_path.read_text(encoding="utf-8"))
                    encoded = _json(diagnostic)
                except (ValueError, TypeError, RecursionError):
                    raise DomainError("INVALID_WORKER_ARTIFACT", "The diagnostic report is invalid.") from None
                if (not isinstance(diagnostic, dict) or diagnostic.get("diagnostic_only") is not True
                        or diagnostic.get("status") != "fail"
                        or any(diagnostic.get(key) != value for key, value in expected_binding.items())
                        or _json(self._public(diagnostic)) != encoded):
                    raise DomainError("INVALID_WORKER_ARTIFACT", "The diagnostic report has invalid public data or binding.")
                drawing["diagnostic_only"] = True
                # Verify every file before publishing any diagnostic artifact.
                for path, media, role in files:
                    drawing["artifacts"].append(self.store.artifact_register(
                        ctx, path, role, state["run_id"], state["revision"], media, path.name))
                drawing["report"].pop("artifacts", None)
            self._save_drawing(directory, drawing)
            return {"status": "fail", "run_id": state["run_id"], "revision": state["revision"], "drawing": drawing}
        if result.get("checks", {}).get("rendered_layout") != "pass":
            raise DomainError("DRAWING_LAYOUT_REQUIRED", "The drawing worker must pass the rendered layout check.")
        files = self._drawing_worker_files(cad, result, (
            ("drawing.dxf", "image/vnd.dxf", "technical_drawing"),
            ("drawing.pdf", "application/pdf", "technical_drawing")))
        for path, media, role in files:
            drawing["artifacts"].append(self.store.artifact_register(ctx, path, role, state["run_id"],
                                                                    state["revision"], media, path.name))
        public_report = self._public(result)
        public_report.pop("artifacts", None)
        drawing["artifacts"].append(self._register_json(ctx, directory, public_report, "drawing-report.json",
                                                       "drawing_report", state["run_id"], state["revision"]))
        drawing.update(status="pass", report=public_report)
        self._save_drawing(directory, drawing)
        return {"status": "pass", "run_id": state["run_id"], "revision": state["revision"], "drawing": drawing}

    def _drawing_worker_files(self, cad, result, files):
        """Verify fixed private paths and file hashes before artifact publication."""
        workdir = Path(result.get("worker", {}).get("work_dir", ""))
        if not workdir.is_absolute() or not workdir.is_relative_to(cad.runner.storage) or workdir.resolve() != workdir:
            raise DomainError("INVALID_WORKER_ARTIFACT", "The drawing worker directory is invalid.")
        verified = []
        for filename, media, role in files:
            path = workdir / filename
            self.store._check_path(path)
            matches = [item for item in result.get("artifacts", []) if item.get("name") == filename]
            expected = matches[0] if len(matches) == 1 else None
            if (not expected or expected.get("path") != str(path)
                    or type(expected.get("bytes")) is not int or not 0 < expected["bytes"] <= 32 * 1024 * 1024
                    or not isinstance(expected.get("sha256"), str) or len(expected["sha256"]) != 64
                    or (role.startswith("drawing_diagnostic_") and expected.get("role") != role)):
                raise DomainError("INVALID_WORKER_ARTIFACT", "The drawing worker did not return its fixed artifact paths.")
            self.store._verify(path, expected["bytes"], expected["sha256"])
            verified.append((path, media, role))
        return verified

    def _review(self, ctx, cad, directory, state, args):
        drawing = self._drawing(directory, state)
        if not drawing or drawing["status"] != "pass" or drawing["drawing_sha256"] != args["drawing_sha256"]:
            raise DomainError("DRAWING_REVIEW_CONFLICT", "Render the current drawing and review its exact hash.")
        hashes = {source["sha256"] for source in state["sources"] if source["role"] == "construction"}
        if set(args["source_hashes"]) != hashes:
            raise DomainError("COVERAGE_SOURCE_MISMATCH", "The drawing review must cover all construction source hashes.")
        for source in state["sources"]:
            self.store.source_path(ctx, source["source_id"])
        for artifact in drawing["artifacts"]:
            self.store.artifact_read(ctx, artifact["artifact_id"], length=1)
        drawing["review"] = {**args, "scope": "identified_drawing_and_model_review_attestation",
                             "automatic_cad_equivalence": "not_tested",
                             "candidate_sha256": (state.get("build") or {}).get("candidate_sha256")}
        # A review does not invalidate a STEP release. Call export_step again to record the new drawing status.
        self._save_drawing(directory, drawing)
        return {"status": "pass", "drawing": drawing}

    def _export_review(self, ctx, cad, directory, state):
        remaining = 32 * 1024 * 1024

        def read_record(path):
            nonlocal remaining
            self.store._check_path(path)
            size = path.stat().st_size
            if size > remaining:
                raise DomainError("TRACE_LIMIT", "The complete run trace exceeds the 32 MiB export limit.")
            with path.open("rb") as stream:
                raw = stream.read(remaining + 1)
            if len(raw) > remaining:
                raise DomainError("TRACE_LIMIT", "The complete run trace exceeds the 32 MiB export limit.")
            remaining -= len(raw)
            return raw

        trace = []
        for event in state["events"]:
            record = deepcopy(event)
            for field in ("request", "result"):
                if field + "_path" not in event:
                    continue
                path = Path(event[field + "_path"])
                self.store._check_path(path)
                if path.parent != directory or path.stat().st_size > 16 * 1024 * 1024:
                    raise DomainError("TRACE_INVALID", "A stored trace record is invalid.")
                raw = read_record(path)
                if hashlib.sha256(raw).hexdigest() != event[field + "_sha256"]:
                    raise DomainError("TRACE_INVALID", "A stored trace record changed.")
                record[field] = self._public(json.loads(raw))
                record["recorded_private_" + field + "_sha256"] = record[field + "_sha256"]
                record[field + "_sha256"] = _digest(record[field])
            trace.append(record)
        domain_events = []
        for path in sorted((directory / "domain-events").glob("*.json")):
            self.store._check_path(path)
            if path.stat().st_size > 8 * 1024 * 1024:
                raise DomainError("TRACE_INVALID", "A domain event exceeds its limit.")
            domain_events.append(json.loads(read_record(path)))
        drawing = self._drawing(directory, state)
        public_state = deepcopy(state)
        public_state["release"] = self._release_view(public_state, drawing)
        manifest = {"schema_version": "1.0", "package_version": __version__, "run": public_state,
                    "drawing": drawing, "notes": self._notes(ctx, state["run_id"]),
                    "scope": "Path-free application evidence. Target CAD and AP242 acceptance require separate tests.",
                    "trace_hash_scope": "request_sha256 and result_sha256 bind canonical public payloads. recorded_private_* hashes preserve the original private record hashes."}
        artifacts = []
        for filename, role, value in (("part.json", "part_description", state["description"]),
                                       ("manifest.json", "run_manifest", manifest), ("trace.json", "run_trace", trace),
                                       ("domain-events.json", "domain_run_events", domain_events)):
            artifacts.append(self._register_json(ctx, directory, value, filename, role, state["run_id"], state["revision"]))
        return {"status": "pass", "run_id": state["run_id"], "revision": state["revision"], "artifacts": artifacts}
