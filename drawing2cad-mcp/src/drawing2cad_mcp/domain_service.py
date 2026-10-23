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
import sqlite3
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
from . import derived_views, drawing_verification
from .drawing_contract import DRAWING_SCHEMA_VERSION, drawing_schema, drawing_validate, render_gate
from .measurements_tools import MEASUREMENT_METHODS
from .pdf import MAX_STROKE_LIMIT, PdfError, PdfProcessError, PdfService
from .part_schema import EdgeSelectionDiagnostic
from .schema_errors import describe_all as describe_schema_errors, summary as schema_error_summary
from .measurements import calibration_defects
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
        self._result_failures = set()
        self._result_event_cache = {}
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
        except ValidationError:
            # The JSON Pointers and the failed schema rules tell the agent which fields to correct.
            # The messages never repeat an input value, because it can be private.
            extra = calibration_defects(arguments.get("references")) if name == "pdf_calibrate" and isinstance(arguments, dict) else ()
            defects, total = describe_schema_errors(Draft202012Validator(DOMAIN_SCHEMAS[name]), arguments, prefix, extra)
            raise DomainError("INVALID_ARGUMENT", "The arguments do not match the tool contract. " + schema_error_summary(defects, total),
                              target=defects[0]["target"], defects=defects if len(defects) > 1 else None,
                              next_action=f"Read the input schema of {name} and correct the field at the target.") from None
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
        except PdfProcessError as error:
            # Helper process output stays in the server log.
            LOG.warning("PDF operation %s failed: %s", name, self._redact(str(error)))
            raise DomainError("PDF_PREPARATION_FAILED", "The uploaded PDF could not be prepared with the requested options.",
                              next_action="Inspect the server diagnostic. Use PDF image tools if the vector profile does not support this page.") from None
        except PdfError as error:
            # Written messages name the argument or the evidence to correct.
            message = self._redact(str(error))
            LOG.warning("PDF operation %s failed: %s", name, message)
            raise DomainError("PDF_PREPARATION_FAILED", "The uploaded PDF could not be prepared with the requested options: " + message,
                              next_action="Correct the arguments or the evidence named in the message. Use PDF image tools if the vector profile does not support this page.") from None
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
            return drawing_schema(args.get("schema_version", DRAWING_SCHEMA_VERSION))
        cad = self._backend(ctx)[0]
        if name in {"part_schema", "pmi_schema", "part_validate", "cad_worker_probe"}:
            if name == "cad_worker_probe":
                with self._cad_slots:
                    return cad.call(name, args)
            return cad.call(name, args)
        if name in {"build_from_description", "build_code", "drawing_render", "export_step", "part_render_pmi",
                    "model_projection_check", "drawing_derive_views", "drawing_verify"}:
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

    def _projection_check(self, ctx, cad, directory, state, args):
        """Compare the validated build candidate with the views of one construction source."""
        if not self.settings.cad.enabled:
            raise DomainError("CAD_DISABLED", "Enable the restricted worker before the projection check.")
        built = state.get("build") or {}
        if (built.get("status") != "pass" or built.get("description_revision") != state["revision"]
                or built.get("description_sha256") != state["description_sha256"]):
            raise DomainError("VALIDATED_BUILD_REQUIRED", "Build and validate the current part before the projection check.")
        for view in args["views"]:
            left, top, right, bottom = view["region"]
            if right <= left or bottom <= top:
                raise DomainError("INVALID_VIEW", f"View {view['view_id']}: the region needs left < right and top < bottom.")
            if view["toward_viewer"][1] == view["up"][1]:
                raise DomainError("INVALID_VIEW", f"View {view['view_id']}: the up axis must be perpendicular to the viewing axis.")
        sources = [item for item in state["sources"] if item["source_id"] == args["source_id"]]
        if not sources or sources[0]["role"] != "construction":
            raise DomainError("SOURCE_NOT_IN_RUN", "Use a construction source of this run.")
        source = self.store.source_path(ctx, args["source_id"])
        if hashlib.sha256(source.read_bytes()).hexdigest() != sources[0]["sha256"]:
            raise DomainError("SOURCE_HASH_MISMATCH", "The source differs from its hash in the run.")
        candidate = cad._candidate(built["build"])
        if str(candidate) != built.get("candidate_path") or hashlib.sha256(candidate.read_bytes()).hexdigest() != built["candidate_sha256"]:
            raise DomainError("CANDIDATE_CHANGED", "The current build candidate differs from its record.")
        result = cad.runner.run("projection_check", input_step=candidate, input_pdf=source, page=args["page"], views=args["views"])
        report = {"status": result.get("status", "fail"), "run_id": state["run_id"], "revision": state["revision"],
                  "candidate_sha256": built["candidate_sha256"], "source_sha256": sources[0]["sha256"], "page": args["page"],
                  "claim": "drawing_model_consistency", "views": self._public(result.get("views", [])), "artifacts": []}
        if "views" not in result:
            report.update(status="fail", error=self._public(result.get("error", {"code": "PROJECTION_FAILED"})))
            return report
        files = self._drawing_worker_files(cad, result, (("projection-overlay.png", "image/png", "projection_overlay"),))
        for path, media, role in files:
            report["artifacts"].append(self.store.artifact_register(ctx, path, role, state["run_id"], state["revision"], media, path.name))
        report["artifacts"].append(self._register_json(ctx, directory, {key: value for key, value in report.items() if key != "artifacts"},
                                                       "projection-check.json", "projection_report", state["run_id"], state["revision"]))
        return report

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

    @staticmethod
    def _derivation_path(directory):
        return directory / "derived-views-state.json"

    def _derivation(self, directory):
        path = self._derivation_path(directory)
        self.store._check_path(path)
        if not path.is_file():
            return None
        if path.stat().st_size > 16 * 1024 * 1024:
            raise DomainError("DERIVATION_STATE_INVALID", "The stored view derivation exceeds its limit.")
        return json.loads(path.read_text(encoding="utf-8"))

    def _validate_drawing(self, directory, state, spec):
        """Put derived views into the drawing, then validate it. Return the report and the expanded drawing."""
        expanded, failure = derived_views.expand(spec, self._derivation(directory), state)
        if failure is not None:
            return failure, spec
        return drawing_validate(expanded, state["description"], state["revision"]), expanded

    def _current_candidate(self, cad, state, purpose):
        built = state.get("build") or {}
        if derived_views.binding(state) is None:
            raise DomainError("VALIDATED_BUILD_REQUIRED", f"Build and validate the current part before {purpose}.")
        candidate = cad._candidate(built["build"])
        if str(candidate) != built.get("candidate_path") or hashlib.sha256(candidate.read_bytes()).hexdigest() != built["candidate_sha256"]:
            raise DomainError("CANDIDATE_CHANGED", "The current build candidate differs from its record.")
        return candidate

    def _last_results_record(self, directory):
        """Read immutable result references independently of the current build."""
        path = directory / "last-results.json"
        self.store._check_path(path)
        if not path.is_file():
            return {"step": None, "drawing": None}
        if path.stat().st_size > 4 * 1024 * 1024:
            raise DomainError("RESULT_STATE_INVALID", "The stored result state exceeds its limit.")
        record = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(record, dict) and record.get("unavailable") is True:
            raise DomainError("RESULTS_UNAVAILABLE", "The retained diagnostic record is unavailable.")
        if (not isinstance(record, dict)
                or any(record.get(key) is not None and not isinstance(record[key], dict) for key in ("step", "drawing"))):
            raise DomainError("RESULT_STATE_INVALID", "The stored result state has invalid fields.")
        for field, required in (("step", {"artifact", "build_revision", "description_sha256", "candidate_sha256", "validation"}),
                                ("drawing", {"part_revision", "drawing_sha256", "artifacts"})):
            if record.get(field) is not None and not required.issubset(record[field]):
                raise DomainError("RESULT_STATE_INVALID", "The stored result fields are incomplete.")
        step, drawing = record.get("step") or {}, record.get("drawing") or {}
        verification = drawing.get("verification") if drawing.get("verification") is not None else {}
        review = drawing.get("review") if drawing.get("review") is not None else {}
        objects = (step.get("artifact", {}), step.get("validation", {}), verification, review)
        if not all(isinstance(item, dict) for item in objects):
            raise DomainError("RESULT_STATE_INVALID", "The stored result objects are invalid.")
        if not isinstance(verification.get("binding", {}), dict):
            raise DomainError("RESULT_STATE_INVALID", "The stored verification binding is invalid.")
        for items in (verification.get("artifact_ids", []), verification.get("covered_rules", [])):
            if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
                raise DomainError("RESULT_STATE_INVALID", "The stored verification identifiers are invalid.")
        for items in (drawing.get("artifacts", []), verification.get("findings", []), review.get("verification_decisions", [])):
            if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                raise DomainError("RESULT_STATE_INVALID", "The stored result lists are invalid.")
        return record

    def _save_last_results(self, directory, record):
        CadService._atomic(directory / "last-results.json", _json(record))

    @staticmethod
    def _unavailable_results():
        return {"released": False, "failed_phase": None, "reason": "Retained diagnostic results are unavailable.",
                "no_step_reason": "The retained model result is unavailable.", "step": None, "drawing": None,
                "error": {"code": "RESULTS_UNAVAILABLE", "message": "The stored diagnostic metadata or files are unavailable or invalid."}}

    def _remember_result(self, directory, operation):
        """Keep auxiliary publication failures separate from the completed primary operation."""
        if str(directory) in self._result_failures:
            try:
                self._save_last_results(directory, {"unavailable": True})
            except (DomainError, CadError, OSError, ValueError, KeyError, TypeError, sqlite3.Error):
                pass
            return
        try:
            operation()
        except (DomainError, CadError, OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            self._result_failures.add(str(directory))
            try:
                self._save_last_results(directory, {"unavailable": True})
            except (DomainError, CadError, OSError, ValueError, KeyError, TypeError, sqlite3.Error):
                pass

    def _remember_build(self, ctx, cad, directory, state):
        self._remember_result(directory, lambda: self._remember_build_result(ctx, cad, directory, state))

    def _remember_build_result(self, ctx, cad, directory, state):
        built = state.get("build") or {}
        if derived_views.binding(state) is None:
            return
        candidate = self._current_candidate(cad, state, "candidate publication")
        artifact = self.store.artifact_register(ctx, candidate, "step_candidate", state["run_id"],
                                                state["revision"], "model/step", "candidate.step")
        if artifact["sha256"] != built["candidate_sha256"]:
            raise DomainError("CANDIDATE_CHANGED", "The candidate changed during artifact publication.")
        record = self._last_results_record(directory)
        record["step"] = {"artifact": artifact, "build_revision": state["revision"],
                          "description_sha256": state["description_sha256"],
                          "candidate_sha256": built["candidate_sha256"],
                          "validation": self._public(built["validation"])}
        self._save_last_results(directory, record)

    def _remember_drawing(self, directory, drawing):
        self._remember_result(directory, lambda: self._remember_drawing_result(directory, drawing))

    def _remember_drawing_result(self, directory, drawing):
        record = self._last_results_record(directory)
        failed = drawing.get("status") == "fail" or (drawing.get("verification") or {}).get("status") == "fail"
        if not any(item.get("role") == "technical_drawing" for item in drawing.get("artifacts", [])):
            if failed:
                record["failed_phase"] = "drawing"
                self._save_last_results(directory, record)
            return
        record["drawing"] = deepcopy(drawing)
        record["failed_phase"] = "drawing" if failed else None
        self._save_last_results(directory, record)

    def _results_unavailable_in_events(self, directory):
        """Retain a publication failure when the separate result-state write failed."""
        events = directory / "domain-events"
        self.store._check_path(events)
        paths, fingerprint, total = [], [], 0
        for index, path in enumerate(events.glob("*.json")):
            if index >= 1000:
                raise DomainError("RESULT_STATE_INVALID", "The diagnostic event count exceeds its limit.")
            self.store._check_path(path)
            metadata = path.stat()
            total += metadata.st_size
            if metadata.st_size > 8 * 1024 * 1024 or total > 32 * 1024 * 1024:
                raise DomainError("RESULT_STATE_INVALID", "The diagnostic event data exceeds its limit.")
            paths.append(path)
            fingerprint.append((path.name, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns))
        key = str(directory)
        cached = self._result_event_cache.get(key)
        if cached and cached[0] == fingerprint:
            return cached[1]
        unavailable = False
        for path in paths:
            event = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(event, dict):
                raise DomainError("RESULT_STATE_INVALID", "The diagnostic event record is invalid.")
            if event.get("results_unavailable") is True:
                unavailable = True
                break
        self._result_event_cache[key] = (fingerprint, unavailable)
        return unavailable

    def _last_results(self, ctx, directory, state):
        """Keep unavailable diagnostics separate from current release inspection."""
        if str(directory) in self._result_failures:
            return self._unavailable_results()
        try:
            if self._results_unavailable_in_events(directory):
                return self._unavailable_results()
            return self._last_results_view(ctx, directory, state)
        except (DomainError, CadError, OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            return self._unavailable_results()

    def _last_results_view(self, ctx, directory, state):
        """Project diagnostic results without changing release state or files."""
        record = self._last_results_record(directory)
        step, drawing = deepcopy(record.get("step")), record.get("drawing")
        verification = None
        if drawing and drawing.get("verification"):
            current_drawing = self._drawing(directory, state)
            current = self._verification_binding(ctx, state, current_drawing) if current_drawing else None
            verification = drawing_verification.status(drawing["verification"], current)
        review = (drawing or {}).get("review") or {}
        decisions = review.get("verification_decisions") if review.get("verification_report_sha256") == (verification or {}).get("report_sha256") else []
        gate = drawing_verification.gate(verification, decisions)
        blocking = list(gate.get("blocking", []))
        # Retain report findings as diagnostic evidence even when the acceptance gate rejects stale inputs.
        decided = {(item["rule_id"], item.get("feature")) for item in decisions or []}
        known = {(item["rule_id"], item.get("feature")) for item in blocking}
        for item in (verification or {}).get("findings", []):
            key = (item["rule_id"], item.get("feature"))
            unresolved = (item["status"] in {"fail", "not_tested"}
                          or item["status"] == "needs_review" and key not in decided
                          or item["status"] == "not_applicable" and not item.get("message"))
            if unresolved and key not in known:
                blocking.append(item)
                known.add(key)
        if step is None:
            reason = "No validated build is available."
        elif drawing is None:
            reason = "No technical drawing was rendered."
        elif verification and verification["validity"] == "stale":
            reason = "The retained verification is stale. Its findings describe the earlier results, not the current part."
            if blocking:
                rules = ", ".join(dict.fromkeys(item["rule_id"] for item in blocking))
                reason += " Retained findings: " + rules + "."
        elif blocking:
            rules = ", ".join(dict.fromkeys(item["rule_id"] for item in blocking))
            reason = "The drawing verification blocks release (" + rules + ")."
        elif not gate["passed"]:
            reason = ("The retained drawing has not been verified." if verification is None
                      else "The retained drawing verification is incomplete or does not meet the acceptance requirements.")
        elif review.get("decision") != "accepted":
            reason = "The drawing has no accepted review."
        else:
            reason = "These results are diagnostic files. They are not a release."

        def artifact(item):
            metadata = self.store.artifact_get(ctx, item["artifact_id"])
            if metadata["run_id"] != state["run_id"] or metadata != item:
                raise DomainError("RESULT_ARTIFACT_CHANGED", "The result artifact does not match its record.")
            self.store.artifact_read(ctx, metadata["artifact_id"], length=1)
            return {**metadata, "released": False, "release_status": "not_released", "reason": reason}

        if step:
            step["artifact"] = artifact(step["artifact"])
            step["current_revision"] = (step["build_revision"] == state["revision"]
                                         and step["description_sha256"] == state["description_sha256"])
        result_drawing = None
        if drawing:
            result_drawing = {"part_revision": drawing["part_revision"], "drawing_sha256": drawing["drawing_sha256"],
                              "artifacts": [artifact(item) for item in drawing.get("artifacts", [])
                                            if item.get("role") == "technical_drawing"], "verification": None}
            if verification:
                result_drawing["verification"] = {"status": verification["status"], "validity": verification["validity"],
                    "artifacts": [artifact(self.store.artifact_get(ctx, identifier)) for identifier in verification.get("artifact_ids", [])],
                    "blocking": [{key: item.get(key) for key in ("rule_id", "status", "feature", "message")} for item in blocking]}
        return {"released": False, "reason": reason, "no_step_reason": None if step else reason,
                "failed_phase": record.get("failed_phase"), "step": step, "drawing": result_drawing}

    def _drawing_read(self, ctx, directory, state, run_id):
        drawing = self._drawing(directory, state)
        verification = None
        current = None
        if drawing and drawing.get("verification"):
            current = self._verification_binding(ctx, state, drawing)
            verification = drawing_verification.status(drawing["verification"], current)
        acceptance = self._drawing_status(drawing, state, ctx, current)
        release = self._release_view(state, drawing, ctx)
        release_fields = ("artifact", "released_artifact_ids", "delivery", "drawing", "drawing_current", "pair_current", "pair_reason")
        return {"run_id": run_id, "revision": state["revision"], "drawing": drawing, "verification": verification,
                "acceptance": {key: acceptance.get(key) for key in ("status", "reason", "verification")},
                "last_results": self._last_results(ctx, directory, state),
                "release": {key: release.get(key) for key in release_fields} if release else None,
                "derived_views": derived_views.status(self._derivation(directory), state)}

    def _drawing_pdf(self, ctx, drawing):
        """The metadata and the stored path of the PDF of a rendered drawing, or None."""
        for item in drawing.get("artifacts", []):
            if item.get("media_type") == "application/pdf" and item.get("role") == "technical_drawing":
                return item, self.store._path(ctx, "artifacts", item["artifact_id"])
        return None

    def _verification_binding(self, ctx, state, drawing):
        """The binding that a verification report needs to stay current."""
        pdf = self._drawing_pdf(ctx, drawing)
        digest = None
        if pdf is not None:
            metadata, path = pdf
            digest = metadata["sha256"] if self._file_has(path, metadata["sha256"], metadata["size_bytes"]) else "changed"
        built = derived_views.binding(state)
        candidate = None
        if built:
            # The stored candidate bytes, not only the recorded hash. A missing candidate is a change, not an error.
            try:
                path = self._backend(ctx)[0]._candidate((state.get("build") or {})["build"])
                same_path = str(path) == (state.get("build") or {}).get("candidate_path")
            except (DomainError, CadError, OSError, KeyError):
                same_path = False
            candidate = built["candidate_sha256"] if same_path and self._file_has(path, built["candidate_sha256"]) else "changed"
        sources = sorted(source["sha256"] for source in state["sources"] if source["role"] == "construction")
        return {"part_revision": state["revision"], "description_sha256": state["description_sha256"],
                "source_sha256s": sources, "profile": drawing_verification.PROFILE,
                "candidate_sha256": candidate,
                "drawing_sha256": drawing["drawing_sha256"], "pdf_sha256": digest}

    def _file_has(self, path, digest, size=None) -> bool:
        """True when the file has the digest. A verified result is reused while inode, size, mtime, and ctime stay the same.

        A read of the drawing state can need the hashes of the PDF and the STEP candidate. The cache keeps repeated reads cheap.
        """
        try:
            info = Path(path).stat()
        except OSError:
            return False
        key = (str(path), info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, digest)
        # On Windows, st_ctime is the creation time, not the time of the last change. Do not cache there.
        cache = self.__dict__.setdefault("_verified_files", {}) if os.name != "nt" else {}
        if key in cache:
            return cache[key]
        if size is not None and info.st_size != size:
            result = False
        else:
            try:
                actual = hashlib.sha256()
                with Path(path).open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        actual.update(chunk)
                result = actual.hexdigest() == digest
            except OSError:
                result = False
        if len(cache) > 256:
            cache.clear()
        cache[key] = result
        return result

    def _verify_drawing(self, ctx, cad, directory, state, args):
        """Verify the stored PDF bytes of the current drawing, or a construction source without a binding."""
        if not self.settings.cad.enabled:
            raise DomainError("CAD_DISABLED", "Enable the restricted worker before the drawing verification.")
        if ("artifact_id" in args) == ("source_id" in args):
            raise DomainError("INVALID_ARGUMENT", "Give either artifact_id or source_id.")
        drawing = None
        candidate = None
        if "artifact_id" in args:
            metadata = self.store.artifact_get(ctx, args["artifact_id"])
            if metadata["sha256"] != args["expected_sha256"]:
                raise DomainError("ARTIFACT_HASH_MISMATCH", "The artifact differs from the expected hash.")
            drawing = self._drawing(directory, state)
            pdf = self._drawing_pdf(ctx, drawing) if drawing and drawing.get("status") == "pass" else None
            if pdf is None or pdf[0]["artifact_id"] != args["artifact_id"]:
                raise DomainError("STALE_DRAWING", "The artifact is not the PDF of the current drawing. Render the drawing again.")
            path = pdf[1]
            self.store._verify(path, metadata["size_bytes"], metadata["sha256"])
            report = drawing_validate(drawing["spec"], state["description"], state["revision"])
            if report["status"] != "pass":
                raise DomainError("STALE_DRAWING", "The stored drawing does not validate against the current part.")
            try:
                candidate = self._current_candidate(cad, state, "the drawing verification")
            except DomainError:
                candidate = None
            expected = {"pdf_sha256": metadata["sha256"], "part_revision": state["revision"],
                        "description_sha256": state["description_sha256"], "dxf_sha256": (drawing.get("report") or {}).get("dxf_sha256")}
        else:
            sources = [item for item in state["sources"] if item["source_id"] == args["source_id"]]
            if not sources:
                raise DomainError("SOURCE_NOT_IN_RUN", "Use a source of this run.")
            if sources[0]["sha256"] != args["expected_sha256"]:
                raise DomainError("SOURCE_HASH_MISMATCH", "The source differs from the expected hash.")
            path = self.store.source_path(ctx, args["source_id"])
            expected = {"pdf_sha256": sources[0]["sha256"], "part_revision": None, "description_sha256": None, "dxf_sha256": None}
        # One private snapshot for both workers. The raster and the verified bytes are the same bytes.
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected["pdf_sha256"]:
            raise DomainError("INTEGRITY_ERROR", "The stored PDF changed before the verification.")
        snapshot = cad.runner.storage / ("verify-" + uuid4().hex + ".pdf")
        cad.runner.storage.mkdir(parents=True, exist_ok=True)
        with snapshot.open("xb") as stream:
            stream.write(data)
        try:
            return self._verify_snapshot(ctx, cad, directory, state, drawing, report if drawing is not None else None,
                                         candidate, expected, snapshot)
        finally:
            snapshot.unlink(missing_ok=True)

    def _verify_snapshot(self, ctx, cad, directory, state, drawing, report, candidate, expected, path):
        before = self._verification_binding(ctx, state, drawing) if drawing is not None else None
        rendered = cad.runner.run("render_pdf_poppler", input_pdf=path)
        pages = rendered.get("pages", []) if rendered.get("status") == "pass" else []
        image = None
        if pages:
            image = Path(pages[0]["path"])
            if not image.is_relative_to(cad.runner.storage) or image.resolve() != image or not image.is_file():
                raise DomainError("INVALID_WORKER_ARTIFACT", "The renderer page is outside its worker directory.")
        if drawing is not None:
            request = drawing_verification.build_request(report["resolved"], expected, len(pages))
            if candidate is None:
                request["service_findings"].append(({"rule_id": "REV-01", "status": "fail", "severity": "major"},
                                                     "No current validated build exists. The model comparison is not possible."))
        else:
            request = drawing_verification.build_unbound_request(expected, len(pages))
        request["raster_pdf_sha256"] = expected["pdf_sha256"]
        if rendered.get("status") != "pass":
            request["service_findings"].append(({"rule_id": "RENDER-00", "status": "fail", "severity": "critical"},
                                                 "Poppler failed: " + str(self._public(rendered.get("error", {})).get("message", ""))))
        result = cad.runner.run("verify_drawing_pdf", input_pdf=path, input_image=image, input_step=candidate,
                                verification=request, timeout=max(self.settings.cad.timeout_seconds, 240))
        if result.get("status") != "pass" or not isinstance(result.get("report"), dict):
            return {"status": "fail", "run_id": state["run_id"], "revision": state["revision"],
                    "error": self._public(result.get("error", {"code": "VERIFICATION_FAILED"}))}
        files = self._drawing_worker_files(cad, result, tuple(
            item for item in (("verification-report.json", "application/json", "drawing_verification_report"),
                              ("verification-preview.png", "image/png", "drawing_verification_preview"))
            if any(artifact.get("name") == item[0] for artifact in result.get("artifacts", []))))
        artifacts = [self.store.artifact_register(ctx, path_, role, state["run_id"], state["revision"], media, path_.name)
                     for path_, media, role in files]
        body = result["report"]
        body["report_sha256"] = next(item["sha256"] for item in artifacts if item["role"] == "drawing_verification_report")
        if drawing is not None:
            # The inputs must not change while the workers run. A changed input gives no record.
            after = self._verification_binding(ctx, state, drawing)
            if after != before:
                raise DomainError("VERIFICATION_INPUT_CHANGED", "A bound input changed during the verification. Verify the drawing again.")
            drawing["verification"] = drawing_verification.record(body, before, [item["artifact_id"] for item in artifacts])
            self._save_drawing(directory, drawing)
            self._remember_drawing(directory, drawing)
        open_findings = [item for item in body["findings"] if item["status"] in {"fail", "needs_review"}]
        return {"status": body["status"], "run_id": state["run_id"], "revision": state["revision"], "mode": body["mode"],
                "binding": body["binding"], "untested_rules": body["untested_rules"], "findings": open_findings[:60],
                "findings_truncated": len(open_findings) > 60, "artifacts": artifacts, "scope": body["scope"]}

    def _derive_views(self, ctx, cad, directory, state, args):
        """Derive drawing views from the validated build in the restricted worker and store the derivation."""
        if not self.settings.cad.enabled:
            raise DomainError("CAD_DISABLED", "Enable the restricted worker before view derivation.")
        try:
            views = derived_views.normalize_requests(args["views"])
        except ValueError as error:
            raise DomainError("INVALID_VIEW", str(error)) from None
        candidate = self._current_candidate(cad, state, "view derivation")
        bound = derived_views.binding(state)
        result = cad.runner.run("derive_views", input_step=candidate, views=views)
        report = {"status": result.get("status", "fail"), "run_id": state["run_id"], "revision": state["revision"],
                  "binding": bound, "artifacts": []}
        if result.get("status") != "pass" or not isinstance(result.get("views"), list):
            report.update(status="fail", error=self._public(result.get("error", {"code": "DERIVATION_FAILED"})))
            return report
        derived = result["views"]
        if [view.get("id") for view in derived] != [view["id"] for view in views]:
            raise DomainError("INVALID_WORKER_RESULT", "The derived views do not match the request.")
        record = {"binding": bound, "views": derived}
        record["derivation_sha256"] = _digest(record)
        CadService._atomic(self._derivation_path(directory), _json(record))
        public, omitted = derived_views.public_views(derived)
        report.update(derivation_sha256=record["derivation_sha256"], views=public, geometry_omitted=omitted,
                      usage="Refer to a view in DrawingSpec 2.0 with derivation: {derivation_sha256, view_id, feature_ids, evidence_ids}.")
        report["artifacts"].append(self._register_json(ctx, directory, record, "derived-views.json", "derived_views",
                                                       state["run_id"], state["revision"]))
        return report

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

    def _drawing_status(self, drawing, state, ctx=None, current=None):
        """Summarize the technical drawing for a release record.
        States: accepted, unverified, unreviewed, rejected, failed, or missing (with a reason).
        accepted needs an accepted review of the current model and a current verification that passes the acceptance gate."""
        if not drawing:
            return {"status": "missing", "drawing_sha256": None, "artifacts": [],
                    "reason": "No technical drawing was rendered for the current part revision."}
        summary = {"drawing_sha256": drawing["drawing_sha256"], "artifacts": deepcopy(drawing.get("artifacts", []))}
        if drawing.get("status") != "pass":
            report = drawing.get("report") or {}
            return {**summary, "status": "failed", "defects": deepcopy(report.get("defects", [])),
                    "reason": "The latest drawing render did not pass its checks. The artifacts are diagnostic files, not an accepted drawing."}
        verification = None
        if drawing.get("verification"):
            if current is None and ctx is not None:
                current = self._verification_binding(ctx, state, drawing)
            verification = drawing_verification.status(drawing["verification"], current)
        review = drawing.get("review") or {}
        decisions = review.get("verification_decisions") if review.get("verification_report_sha256") == (verification or {}).get("report_sha256") else []
        gate = drawing_verification.gate(verification, decisions)
        summary["verification"] = {"validity": (verification or {}).get("validity"), "status": (verification or {}).get("status"),
                                   "report_sha256": (verification or {}).get("report_sha256"), "gate": gate}
        candidate = (state.get("build") or {}).get("candidate_sha256")
        if review.get("decision") == "rejected" and review.get("candidate_sha256") == candidate:
            return {**summary, "status": "rejected", "review": deepcopy(review),
                    "reason": "The drawing review rejected the drawing for the current model."}
        if review.get("decision") == "accepted" and review.get("candidate_sha256") == candidate:
            if gate["passed"] and review.get("verification_report_sha256") == verification["report_sha256"]:
                return {**summary, "status": "accepted", "review": deepcopy(review)}
            return {**summary, "status": "unverified", "review": deepcopy(review),
                    "reason": gate["reason"] or "The review does not cover the current verification. Record the review again."}
        return {**summary, "status": "unreviewed",
                "reason": "The drawing rendered and passed its checks, but it has no review for the current model."}

    def _release_pair(self, ctx, state, drawing, drawing_status):
        """The verified pair of STEP and drawing PDF, or None. Only an accepted drawing with a current verification forms a pair."""
        if drawing_status.get("status") != "accepted" or not drawing or not drawing.get("verification"):
            return None
        record = drawing["verification"]
        binding = record["binding"]
        pdf = self._drawing_pdf(ctx, drawing)
        if pdf is None or binding.get("pdf_sha256") != pdf[0]["sha256"]:
            return None
        report = next((item for item in record.get("artifact_ids", [])), None)
        return {"step_sha256": binding["candidate_sha256"], "pdf_sha256": binding["pdf_sha256"], "pdf_artifact_id": pdf[0]["artifact_id"],
                "report_sha256": record["report_sha256"], "report_artifact_id": report, "profile": record.get("profile"),
                "drawing_sha256": drawing["drawing_sha256"], "part_revision": state["revision"],
                "review_sha256": _digest(drawing.get("review") or {})}

    def _pair_current(self, ctx, release, state, drawing, current_status):
        """Whether the released pair is still the delivered pair: both files unchanged and the drawing still accepted for it."""
        pair = release.get("pair")
        if not pair:
            return None, None
        step = (release.get("artifact") or {})
        files = (("STEP", step.get("artifact_id"), pair["step_sha256"]), ("PDF", pair["pdf_artifact_id"], pair["pdf_sha256"]))
        for label, artifact_id, digest in files:
            try:
                path = self.store._path(ctx, "artifacts", artifact_id)
            except DomainError:
                return False, f"The released {label} file is missing."
            if not self._file_has(path, digest):
                return False, f"The released {label} file changed after the release."
        now = self._release_pair(ctx, state, drawing, current_status)
        keys = ("step_sha256", "pdf_sha256", "report_sha256", "profile", "drawing_sha256", "review_sha256")
        if now is None or any(now[key] != pair[key] for key in keys):
            return False, "The drawing, its verification, or its review changed after the release. Call export_step again."
        return True, None

    def _release_view(self, state, drawing, ctx=None):
        """Return the release with the current drawing status. Hide a release that is not current."""
        release = state.get("release")
        if not release or not self._release_is_current(state):
            return None
        release = deepcopy(release)
        recorded = release.get("drawing") or {}
        current = self._drawing_status(drawing, state, ctx)
        def evidence(item):
            verification = item.get("verification") or {}
            review = item.get("review") or {}
            return (verification.get("report_sha256"), verification.get("validity"), (verification.get("gate") or {}).get("passed"),
                    review.get("decision"), review.get("reviewer"), review.get("verification_report_sha256"))
        release["drawing_current"] = (recorded.get("status") == current["status"]
                                      and recorded.get("drawing_sha256") == current["drawing_sha256"]
                                      and evidence(recorded) == evidence(current))
        if ctx is not None:
            release["pair_current"], release["pair_reason"] = self._pair_current(ctx, release, state, drawing, current)
        released_ids = []
        step = release.get("artifact") or {}
        if step.get("role") == "released_step":
            released_ids.append(step["artifact_id"])
        if (release.get("delivery") == "complete_service" and release.get("pair_current") is True
                and release["drawing_current"] and current["status"] == "accepted"):
            released_ids.extend(item["artifact_id"] for item in recorded.get("artifacts", [])
                                if item.get("role") != "step_candidate")
        release["released_artifact_ids"] = sorted(set(released_ids))
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
            result = self._drawing_read(ctx, directory, state, args["run_id"])
        elif name == "drawing_validate":
            result = self._validate_drawing(directory, state, args["drawing_spec"])[0]
            result.pop("resolved", None)
        else:
            result = {"status": "pass", "part": deepcopy(state), "run_id": args["run_id"], "revision": state["revision"],
                      "call_count": state["call_count"], "step_budget": state["step_budget"]}
            result["drawing"] = self._drawing(directory, state)
            result["part"]["release"] = self._release_view(result["part"], result["drawing"], ctx)
            result["last_results"] = self._last_results(ctx, directory, result["part"])
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
                if str(directory) in self._result_failures:
                    result["last_results"] = self._unavailable_results()
                    event["results_unavailable"] = True
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
            return self._drawing_read(ctx, directory, state, args["run_id"])
        if name == "drawing_validate":
            report = self._validate_drawing(directory, state, args["drawing_spec"])[0]
            report.pop("resolved", None)
            return report
        if name == "drawing_derive_views":
            return self._derive_views(ctx, cad, directory, state, args)
        if name == "drawing_verify":
            return self._verify_drawing(ctx, cad, directory, state, args)
        if name == "drawing_render":
            return self._render(ctx, cad, directory, state, args["drawing_spec"])
        if name == "part_render_pmi":
            return self._part_visual(ctx, cad, state)
        if name == "model_projection_check":
            return self._projection_check(ctx, cad, directory, state, args)
        if name == "drawing_review":
            return self._review(ctx, cad, directory, state, args)
        if name == "part_export_review":
            return self._export_review(ctx, cad, directory, state)
        if name == "export_step":
            # The model validation gates each release. A complete-service release also needs a verified drawing of the same STEP bytes.
            delivery = args.get("delivery", "step_only")
            drawing = self._drawing(directory, state)
            drawing_status = self._drawing_status(drawing, state, ctx)
            for artifact in drawing_status["artifacts"]:
                self.store.artifact_read(ctx, artifact["artifact_id"], length=1)
            pair = self._release_pair(ctx, state, drawing, drawing_status)
            candidate = (state.get("build") or {}).get("candidate_sha256")
            if delivery == "complete_service" and (pair is None or pair["step_sha256"] != candidate):
                raise DomainError("RELEASE_PAIR_REQUIRED",
                                  "A complete-service release needs an accepted drawing whose PDF verification is bound to the STEP bytes of this release. "
                                  + (drawing_status.get("reason") or "The drawing verification belongs to other STEP bytes."),
                                  next_action="Call drawing_verify and drawing_review for the current build, or release with delivery step_only.")
            previous = deepcopy(state.get("release"))

            def restore_and_fail(message):
                # The CAD service saved its release before these checks. Put the previous release back before the failure.
                with cad._lock(args["run_id"]) as saved_directory:
                    saved = cad._load(saved_directory)
                    saved["release"] = previous
                    cad._save(saved_directory, saved)
                raise DomainError("RELEASE_PAIR_REQUIRED", message, next_action="Verify the current drawing again, then release again.")

            result = cad.call(name, {key: value for key, value in args.items() if key != "delivery"})
            if result.get("status") == "pass":
                release = result["release"]
                if pair is not None and pair["step_sha256"] != release["sha256"]:
                    pair = None
                if delivery == "complete_service" and pair is None:
                    restore_and_fail("The released STEP bytes differ from the verified STEP bytes.")
                artifact = self.store.artifact_register(ctx, release["path"], "released_step", args["run_id"],
                                                        state["revision"], "model/step", Path(release["path"]).name)
                if pair is not None:
                    # The registered copy and the stored PDF must still be the verified bytes when the release is saved.
                    pdf_path = self.store._path(ctx, "artifacts", pair["pdf_artifact_id"])
                    if artifact["sha256"] != pair["step_sha256"] or not self._file_has(pdf_path, pair["pdf_sha256"]):
                        pair = None
                if delivery == "complete_service" and pair is None:
                    restore_and_fail("The STEP file or the PDF changed during the release. Release again.")
                # Only a complete-service release claims a verified pair. A STEP-only release records the drawing status only.
                recorded = {"artifact": artifact, "drawing": drawing_status, "delivery": delivery,
                            "pair": {**pair, "step_artifact_id": artifact["artifact_id"]} if pair and delivery == "complete_service" else None}
                result["release"].update(recorded)
                with cad._lock(args["run_id"]) as saved_directory:
                    saved = cad._load(saved_directory)
                    saved["release"].update(recorded)
                    cad._save(saved_directory, saved)
                result["release"]["pair_current"], result["release"]["pair_reason"] = self._pair_current(
                    ctx, result["release"], state, drawing, drawing_status)
                if delivery == "complete_service" and result["release"]["pair_current"] is not True:
                    restore_and_fail("The verified pair changed during the release: " + (result["release"]["pair_reason"] or "unknown change."))
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
        if name in {"build_from_description", "build_code"} and result.get("status") == "pass":
            self._remember_build(ctx, cad, directory, cad._load(directory))
        if name == "part_read":
            result["drawing"] = self._drawing(directory, state)
            result["part"]["release"] = self._release_view(result["part"], result["drawing"], ctx)
            result["last_results"] = self._last_results(ctx, directory, result["part"])
        return result

    def _render(self, ctx, cad, directory, state, spec):
        if not self.settings.cad.enabled:
            raise DomainError("CAD_DISABLED", "Enable the restricted worker before drawing creation.")
        report, spec = self._validate_drawing(directory, state, spec)
        report = render_gate(report)
        if report["status"] != "pass" and not report.get("diagnostic_eligible"):
            report.pop("resolved", None)
            self._remember_drawing(directory, {"status": "fail", "artifacts": []})
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
            self._remember_drawing(directory, drawing)
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
        self._remember_drawing(directory, drawing)
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
        verification = drawing.get("verification") or {}
        decisions = args.get("verification_decisions", [])
        if decisions:
            open_keys = {(item["rule_id"], item.get("feature")) for item in verification.get("findings", []) if item["status"] == "needs_review"}
            unknown = [item for item in decisions if (item["rule_id"], item.get("feature")) not in open_keys]
            if unknown:
                raise DomainError("REVIEW_DECISION_INVALID",
                                  "A verification decision must name a needs_review finding of the current verification: "
                                  + ", ".join(f"{item['rule_id']}/{item.get('feature')}" for item in unknown[:5]) + ".")
        drawing["review"] = {**args, "scope": "identified_drawing_and_model_review_attestation",
                             "automatic_cad_equivalence": "not_tested",
                             "candidate_sha256": (state.get("build") or {}).get("candidate_sha256"),
                             "verification_report_sha256": verification.get("report_sha256")}
        # A review does not invalidate a STEP release. Call export_step again to record the new drawing status.
        self._save_drawing(directory, drawing)
        self._remember_drawing(directory, drawing)
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
        public_state["release"] = self._release_view(public_state, drawing, ctx)
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
