"""Test shared-domain boundaries with synthetic PDFs and explicit fake CAD."""

import base64
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from pypdf import PdfWriter

from drawing2cad_mcp.config import Settings
from drawing2cad_mcp.domain_service import DomainService
from drawing2cad_mcp.domain_store import AccessContext, DomainError
from drawing2cad_mcp.domain_tools import DOMAIN_SCHEMAS
from drawing2cad_mcp.drawing_contract import description_digest
from drawing2cad_mcp.drafting import render_drawing
from drawing2cad_mcp.pdf import PdfError
from test_cad_service import FakeRunner, coverage
from test_drafting import drawing_fixture


CTX = AccessContext("synthetic-owner")
OTHER = AccessContext("other-owner")


class DrawingRunner(FakeRunner):
    """Use real drawing output but fake CAD; this is not CAD acceptance."""

    def run(self, operation, *, description=None, input_step=None, **kwargs):
        if operation != "drawing":
            return super().run(operation, description=description, input_step=input_step, **kwargs)
        self.calls.append(operation)
        identifier = uuid4().hex
        directory = self.storage / identifier
        directory.mkdir(parents=True)
        if self.fail_operation == operation:
            return {"status": "fail", "error": {"code": "SYNTHETIC_FAILURE", "message": "Synthetic drawing failure."}}
        result = render_drawing(kwargs["drawing_spec"], description, kwargs["revision"], directory)
        result["worker"] = {"worker_id": identifier, "work_dir": str(directory)}
        return result


def upload(service, ctx=CTX):
    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=842, height=595)
    writer.write(stream)
    raw = stream.getvalue()
    begin = service.call(ctx, "upload_begin", {"filename": "synthetic.pdf", "size_bytes": len(raw),
                                                "sha256": hashlib.sha256(raw).hexdigest()})
    service.call(ctx, "upload_chunk", {"upload_id": begin["upload_id"], "offset": 0,
                                       "data_base64": base64.b64encode(raw).decode("ascii")})
    return service.call(ctx, "upload_complete", {"upload_id": begin["upload_id"]})


@pytest.fixture
def domain(tmp_path):
    settings = Settings.model_validate({"pdf": {"allowed_roots": [str(tmp_path)], "output_root": str(tmp_path / "output")},
                                        "domain": {"enabled": True}, "cad": {"enabled": True, "max_tool_calls": 100}})
    service = DomainService(settings)
    source = upload(service)
    description, spec = drawing_fixture()
    description["evidence"][0]["source"].update(source_id=source["source_id"], source_sha256=source["sha256"])
    spec["description_sha256"] = description_digest(description)
    cad = service._backend(CTX)[0]
    runner = DrawingRunner(cad.runner.storage)
    cad.runner = runner
    service.call(CTX, "part_create", {"run_id": "plate", "description": description,
                                      "sources": [{"source_id": source["source_id"], "sha256": source["sha256"], "role": "construction"}]})
    yield service, source, description, spec, runner
    service.close()


def test_pdf_failure_logs_redacted_diagnostic_and_returns_safe_recovery(domain, monkeypatch, caplog):
    service, source, _, _, _ = domain
    private_path = str(service.store.root / "private.pdf")

    def fail(*args, **kwargs):
        raise PdfError(f"Vector analysis failed: unsupported glyph at {private_path}")

    monkeypatch.setattr(service._backend(CTX)[1], "extract_drawing", fail)
    with pytest.raises(DomainError) as caught:
        service.call(CTX, "drawing_extract", {"source_id": source["source_id"]})
    assert caught.value.code == "PDF_PREPARATION_FAILED"
    assert "unsupported glyph" in caplog.text
    assert "drawing_extract" in caplog.text
    assert private_path not in caplog.text
    assert "unsupported glyph" not in caught.value.message
    assert "PDF image tools" in caught.value.next_action


def call(service, name, **args):
    return service.call(CTX, name, {"run_id": "plate", "expected_revision": 1, **args})


def edge_diagnostic():
    return {"expected_count": 1, "selected_count": 2, "truncated": False, "selected_edges": [
        {"geometry": "line", "center": [1, 2, 3], "bbox_min": [0, 2, 3], "bbox_max": [2, 2, 3], "length_mm": 2}
        for _ in range(2)]}


def test_domain_build_preserves_closed_edge_diagnostics(domain, monkeypatch):
    service, _, _, _, runner = domain
    details = edge_diagnostic()
    monkeypatch.setattr(runner, "run", lambda *_args, **_kwargs: {"status": "fail", "error": {
        "code": "EDGE_SELECTION", "message": "Expected one edge.", "feature_id": "blend", "details": details}})
    result = call(service, "build_from_description")
    assert result["build"]["error"]["details"] == details
    assert result["build"]["error"]["feature_id"] == "blend"
    assert result["error"]["code"] == "EDGE_SELECTION"
    assert result["feature_id"] == "blend"
    assert result["checks"] == []


def test_domain_build_failure_reports_only_executed_checks(domain, monkeypatch):
    service, _, _, _, runner = domain
    monkeypatch.setattr(runner, "run", lambda *_args, **_kwargs: {
        "status": "fail", "error": {"code": "NO_MATERIAL_REMOVED", "message": "No cut.",
                                   "feature_id": "end_relief"},
        "checks": [{"check": "feature_execution", "feature_id": "base", "status": "pass"},
                   {"check": "feature_execution", "feature_id": "end_relief", "status": "fail"},
                   {"check": "step_reimport", "status": "not_tested"}]})
    result = call(service, "build_from_description")
    assert result["status"] == "fail"
    assert result["error"] == {"code": "NO_MATERIAL_REMOVED", "message": "No cut.",
                               "feature_id": "end_relief"}
    assert result["checks"] == [{"check": "feature_execution", "feature_id": "base", "status": "pass", "phase": "build"},
                                {"check": "feature_execution", "feature_id": "end_relief", "status": "fail", "phase": "build"}]


def test_domain_build_timeout_has_no_invented_feature_or_checks(domain, monkeypatch):
    service, _, _, _, runner = domain
    monkeypatch.setattr(runner, "run", lambda *_args, **_kwargs: {
        "status": "fail", "error": {"code": "WORKER_TIMEOUT", "message": "The worker exceeded its configured limit."}})
    result = call(service, "build_from_description")
    assert result["error"]["code"] == "WORKER_TIMEOUT"
    assert result["feature_id"] is None
    assert result["checks"] == []
    assert result["validation"]["status"] == "not_tested"


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(path="/data/private"),
    lambda d: d["selected_edges"][0].update(path="C:/private/file"),
    lambda d: d["selected_edges"][0].update(geometry="/data/private"),
    lambda d: d["selected_edges"][0].update(center=[float("nan"), 0, 0]),
    lambda d: d.update(selected_count=1),
    lambda d: d.update(truncated="false"),
    lambda d: d.update(selected_edges=d["selected_edges"] * 40),
])
def test_domain_rejects_unknown_private_or_invalid_edge_diagnostics(domain, mutation):
    service, *_ = domain
    details = edge_diagnostic()
    mutation(details)
    result = service._public({"error": {"code": "EDGE_SELECTION", "message": "Invalid diagnostic.", "details": details}})
    assert "details" not in result["error"]


def test_domain_does_not_publish_details_for_other_errors(domain):
    service, *_ = domain
    assert "details" not in service._public({"error": {
        "code": "KERNEL_OPERATION", "message": "Failure.", "details": edge_diagnostic()}})["error"]


def render_and_build(domain):
    service, source, _, spec, _ = domain
    drawing = call(service, "drawing_render", drawing_spec=spec)
    assert drawing["status"] == "pass", drawing
    assert call(service, "build_from_description")["status"] == "pass"
    review(service, source, drawing["drawing"]["drawing_sha256"])
    return drawing


def review(service, source, digest, decision="accepted"):
    return call(service, "drawing_review", drawing_sha256=digest, reviewer="Synthetic reviewer",
                reason="Synthetic service lifecycle test. No source accuracy claim.",
                source_hashes=[source["sha256"]], decision=decision)


def artifact_bytes(service, artifact):
    result = service.call(CTX, "artifact_read", {"artifact_id": artifact["artifact_id"]})
    assert result["eof"]
    raw = base64.b64decode(result["data_base64"])
    assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]
    return raw


def test_catalog_is_closed_and_never_takes_server_paths():
    for name, schema in DOMAIN_SCHEMAS.items():
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False, name
        assert "path" not in schema["properties"], name
        assert "subject" not in schema["properties"], name
    assert "path" not in DOMAIN_SCHEMAS["part_create"]["properties"]["sources"]["items"]["properties"]


def test_upload_pdf_metadata_and_cross_principal_access(domain):
    service, source, *_ = domain
    result = service.call(CTX, "pdf_info", {"source_id": source["source_id"]})
    assert result["source"]["sha256"] == source["sha256"]
    assert "path" not in result["source"]
    with pytest.raises(DomainError, match="does not exist"):
        service.call(OTHER, "pdf_info", {"source_id": source["source_id"]})
    with pytest.raises(DomainError) as error:
        service.call(CTX, "pdf_info", {"path": "C:/private.pdf"})
    assert error.value.code == "INVALID_ARGUMENT"
    with pytest.raises(DomainError) as error:
        service.call(OTHER, "part_read", {"run_id": "plate"})
    assert error.value.code == "NOT_FOUND"


def test_drawing_model_release_and_downloaded_reports_are_path_free(domain):
    service, source, *_ = domain
    render_and_build(domain)
    result = call(service, "export_step", coverage=coverage(source))
    assert result["status"] == "pass"
    artifact = result["release"]["artifact"]
    assert artifact_bytes(service, artifact).startswith(b"ISO-10303-21;")
    assert {item["filename"] for item in result["drawing"]["artifacts"]} == {"drawing.pdf", "drawing.dxf", "drawing-report.json"}
    reports = call(service, "part_export_review")
    for item in reports["artifacts"] + result["drawing"]["artifacts"]:
        if item["media_type"] != "application/json":
            continue
        text = artifact_bytes(service, item).decode("utf-8")
        assert str(service.store.root) not in text
        assert '"path"' not in text
        assert '"work_dir"' not in text
        assert '_path"' not in text
    public = json.dumps(result)
    assert str(service.store.root) not in public
    assert '"candidate_path"' not in public
    with pytest.raises(DomainError):
        service.call(OTHER, "artifact_read", {"artifact_id": artifact["artifact_id"]})


def test_release_records_the_drawing_status_and_requires_the_current_model(domain):
    """The model validation gates the STEP release. The release records the drawing status."""
    service, source, _, spec, _ = domain
    with pytest.raises(DomainError) as error:
        call(service, "export_step", coverage=coverage(source))
    assert error.value.code == "VALIDATED_BUILD_REQUIRED"
    call(service, "build_from_description")
    missing = call(service, "export_step", coverage=coverage(source))["release"]["drawing"]
    assert missing["status"] == "missing" and missing["reason"] and missing["artifacts"] == []
    rendered = call(service, "drawing_render", drawing_spec=spec)
    digest = rendered["drawing"]["drawing_sha256"]
    unreviewed = call(service, "export_step", coverage=coverage(source))["release"]["drawing"]
    assert unreviewed["status"] == "unreviewed" and unreviewed["drawing_sha256"] == digest
    assert {item["role"] for item in unreviewed["artifacts"]} >= {"technical_drawing"}
    review(service, source, digest, "rejected")
    assert call(service, "export_step", coverage=coverage(source))["release"]["drawing"]["status"] == "rejected"
    review(service, source, digest)
    accepted = call(service, "export_step", coverage=coverage(source))["release"]["drawing"]
    assert accepted["status"] == "accepted" and accepted["review"]["decision"] == "accepted"
    # A rebuild invalidates the release and the drawing review.
    call(service, "build_from_description")
    assert service.call(CTX, "part_read", {"run_id": "plate"})["part"]["release"] is None
    assert call(service, "export_step", coverage=coverage(source))["release"]["drawing"]["status"] == "unreviewed"


def test_part_change_invalidates_drawing_and_requires_rebinding(domain):
    service, source, description, spec, _ = domain
    render_and_build(domain)
    changed = deepcopy(description)
    changed["parameters"][0]["value"] = 70
    changed["measurements"][0]["expected"] = [70, 30, 10]
    assert call(service, "part_update", description=changed)["revision"] == 2
    assert service.call(CTX, "drawing_read", {"run_id": "plate"})["drawing"] is None
    with pytest.raises(DomainError) as error:
        call(service, "drawing_render", drawing_spec=spec)
    assert error.value.code == "REVISION_CONFLICT"
    report = service.call(CTX, "drawing_validate", {"run_id": "plate", "expected_revision": 2, "drawing_spec": spec})
    assert report["status"] == "fail"
    spec.update(part_revision=2, description_sha256=description_digest(changed))
    report = service.call(CTX, "drawing_render", {"run_id": "plate", "expected_revision": 2, "drawing_spec": spec})
    assert report["status"] == "pass", report
    assert report["drawing"]["review"] is None


def test_failed_render_is_released_with_a_failed_drawing_status(domain):
    """A failed render cannot reuse the previous review. The release states the failure."""
    service, source, _, spec, runner = domain
    render_and_build(domain)
    runner.fail_operation = "drawing"
    assert call(service, "drawing_render", drawing_spec=spec)["status"] == "fail"
    drawing = call(service, "export_step", coverage=coverage(source))["release"]["drawing"]
    assert drawing["status"] == "failed" and drawing["reason"]
    assert "review" not in drawing


def test_note_revision_is_separate_and_requires_run_ownership(domain):
    service, *_ = domain
    assert service.call(CTX, "notes_read", {"run_id": "plate"}) == {"run_id": "plate", "revision": 0, "text": ""}
    note = service.call(CTX, "notes_update", {"run_id": "plate", "expected_revision": 0, "text": "Fixture note."})
    assert note["revision"] == 1
    with pytest.raises(DomainError):
        service.call(CTX, "notes_update", {"run_id": "plate", "expected_revision": 0, "text": "Conflict."})
    with pytest.raises(DomainError):
        service.call(OTHER, "notes_update", {"run_id": "plate", "expected_revision": 0, "text": "Denied."})
    assert service.call(CTX, "part_read", {"run_id": "plate"})["revision"] == 1


def test_queued_job_rechecks_revision_and_owner(domain):
    service, _, description, *_ = domain
    args = {"operation": "build_from_description", "arguments": {"run_id": "plate", "expected_revision": 1}, "idempotency_key": "build-1"}
    job = service.call(CTX, "job_submit", args)
    assert service.call(CTX, "job_submit", args)["job_id"] == job["job_id"]
    with pytest.raises(DomainError):
        service.call(OTHER, "job_submit", args)
    changed = deepcopy(description)
    changed["name"] = "Changed synthetic plate"
    call(service, "part_update", description=changed)
    service.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = service.call(CTX, "job_get", {"job_id": job["job_id"]})
        if current["state"] == "failed":
            break
        time.sleep(0.02)
    assert current["state"] == "failed", current
    assert current["error"]["code"] == "REVISION_CONFLICT"
    with pytest.raises(DomainError):
        service.call(OTHER, "job_get", {"job_id": job["job_id"]})


def test_drawing_review_rejects_stale_hash_and_tampered_artifact(domain):
    service, source, _, spec, _ = domain
    rendered = call(service, "drawing_render", drawing_spec=spec)
    with pytest.raises(DomainError) as error:
        review(service, source, "0" * 64)
    assert error.value.code == "DRAWING_REVIEW_CONFLICT"
    artifact = rendered["drawing"]["artifacts"][0]
    path = service.store._path(CTX, "artifacts", artifact["artifact_id"])
    path.write_bytes(b"tampered")
    with pytest.raises(DomainError):
        review(service, source, rendered["drawing"]["drawing_sha256"])


def test_shared_execution_limit_covers_direct_and_job_dispatch(domain):
    service, *_ = domain
    entered = threading.Event()
    release = threading.Event()
    active = []
    original = service._run_call

    def blocking(ctx, name, args):
        active.append(name)
        entered.set()
        release.wait(5)
        return original(ctx, name, args)

    service._run_call = blocking
    job = service.call(CTX, "job_submit", {"operation": "build_from_description", "arguments": {"run_id": "plate", "expected_revision": 1}, "idempotency_key": "bounded"})
    service.start()
    assert entered.wait(3)
    errors = []

    def direct():
        try:
            call(service, "build_from_description")
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=direct)
    thread.start()
    time.sleep(0.1)
    assert active == ["build_from_description"]
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert not errors
    assert len(active) == 2


def test_release_survives_service_restart_and_a_new_review_marks_its_drawing_status_stale(domain):
    service, source, *_ = domain
    drawing = render_and_build(domain)
    released = call(service, "export_step", coverage=coverage(source))
    other = DomainService(service.settings)
    try:
        state = other.call(CTX, "part_read", {"run_id": "plate"})
        assert state["part"]["release"]["artifact"] == released["release"]["artifact"]
        assert state["part"]["release"]["drawing"]["drawing_sha256"] == drawing["drawing"]["drawing_sha256"]
        assert state["part"]["release"]["drawing_current"] is True
        review(other, source, drawing["drawing"]["drawing_sha256"], "rejected")
        release = other.call(CTX, "part_read", {"run_id": "plate"})["part"]["release"]
        assert release["drawing"]["status"] == "accepted" and release["drawing_current"] is False
        assert artifact_bytes(other, released["release"]["artifact"])
        refreshed = other.call(CTX, "export_step", {"run_id": "plate", "expected_revision": 1, "coverage": coverage(source)})
        assert refreshed["release"]["drawing"]["status"] == "rejected"
    finally:
        other.close()


def test_domain_trace_records_drawing_review_bindings(domain):
    service, _, *_ = domain
    rendered = render_and_build(domain)
    reports = call(service, "part_export_review")
    artifact = next(item for item in reports["artifacts"] if item["filename"] == "domain-events.json")
    events = json.loads(artifact_bytes(service, artifact))
    review_event = next(event for event in events if event["operation"] == "drawing_review")
    assert review_event["status"] == "pass"
    assert review_event["drawing_sha256"] == rendered["drawing"]["drawing_sha256"]
    assert review_event["request"]["decision"] == "accepted"
    assert review_event["review"]["candidate_sha256"]
    assert len(review_event["artifacts"]) == 3


def test_failed_worker_job_has_failed_terminal_state(domain):
    service, _, _, _, runner = domain
    runner.fail_operation = "build"
    job = service.call(CTX, "job_submit", {"operation": "build_from_description", "arguments": {"run_id": "plate", "expected_revision": 1}, "idempotency_key": "failed-worker"})
    service.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = service.call(CTX, "job_get", {"job_id": job["job_id"]})
        if current["state"] == "failed":
            break
        time.sleep(0.02)
    assert current["state"] == "failed", current
    assert current["error"]["code"] == "JOB_OPERATION_FAILED"


def test_png_artifact_preview_is_bounded_and_owner_scoped(domain):
    from PIL import Image
    service, *_ = domain
    path = service.store.namespace_root(CTX) / "synthetic.png"
    with Image.new("RGB", (500, 300), "white") as image:
        image.save(path)
    artifact = service.store.artifact_register(CTX, path, "source_preview", "plate", 1, "image/png", "synthetic.png")
    service.settings.server.preview_max_pixels = 10000
    result = service.call(CTX, "artifact_preview", {"artifact_id": artifact["artifact_id"]})
    assert result["preview"]["width_pixels"] * result["preview"]["height_pixels"] <= 10000
    assert base64.b64decode(result["preview"]["data_base64"]).startswith(b"\x89PNG")
    with pytest.raises(DomainError):
        service.call(OTHER, "artifact_preview", {"artifact_id": artifact["artifact_id"]})


def test_domain_schema_errors_do_not_echo_private_input(domain):
    service, *_ = domain
    with pytest.raises(DomainError) as error:
        service.call(CTX, "part_read", {"run_id": str(service.store.root)})
    assert str(service.store.root) not in error.value.message
    assert service.store.root.as_posix() not in error.value.message
    # A value with forward slashes gives the same check on each platform.
    with pytest.raises(DomainError) as error:
        service.call(CTX, "part_read", {"run_id": "/srv/private-customer/secret"})
    assert "secret" not in error.value.message
    assert error.value.target == "/run_id" and "pattern" in error.value.message


def test_worker_error_details_cannot_expose_external_server_paths(domain):
    service, *_ = domain
    public = service._public({"error": {"code": "WORKER_FAILED", "message": "Cannot read /opt/private/config"},
                              "worker": {"work_dir": "/tmp/job", "stderr": "C:/Users/private/file"}})
    assert public["error"]["code"] == "WORKER_FAILED"
    assert "/opt/private" not in json.dumps(public)
    assert "C:/Users/private" not in json.dumps(public)


def test_pdf_diagnostic_log_has_no_macos_or_resolved_storage_paths(domain, monkeypatch, caplog):
    service, source, *_ = domain
    private = (str(service.store.root.resolve()), "/private/var/folders/x", "/Volumes/share")

    def fail(**_):
        raise PdfError("Vector analysis failed: cannot read " + ", ".join(f"{path}/a.pdf" for path in private))

    monkeypatch.setattr(service._backend(CTX)[1], "extract_drawing", fail)
    with pytest.raises(DomainError):
        service.call(CTX, "drawing_extract", {"source_id": source["source_id"]})
    assert "Vector analysis failed" in caplog.text
    for path in private:
        assert path not in caplog.text


def test_export_trace_hashes_match_public_payloads(domain):
    service, *_ = domain
    exported = call(service, "part_export_review")
    artifact = next(item for item in exported["artifacts"] if item["filename"] == "trace.json")
    events = json.loads(artifact_bytes(service, artifact))
    for event in events:
        for field in ("request", "result"):
            if field in event:
                raw = json.dumps(event[field], sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
                assert hashlib.sha256(raw).hexdigest() == event[field + "_sha256"]
    assert events[0]["request_sha256"] != events[0]["recorded_private_request_sha256"]


def test_trace_export_has_one_aggregate_read_limit(domain):
    service, *_ = domain
    cad = service._backend(CTX)[0]
    events = cad._directory("plate") / "domain-events"
    raw = json.dumps({"synthetic_padding": "x" * (7 * 1024 * 1024)}).encode("utf-8")
    for index in range(5):
        (events / f"synthetic-large-{index}.json").write_bytes(raw)
    with pytest.raises(DomainError) as error:
        call(service, "part_export_review")
    assert error.value.code == "TRACE_LIMIT"


def test_failed_step_inspection_removes_private_snapshot(domain):
    service, source, *_ = domain
    render_and_build(domain)
    artifact = call(service, "export_step", coverage=coverage(source))["release"]["artifact"]
    with pytest.raises(DomainError):
        service.call(CTX, "step_inspect", {"artifact_id": artifact["artifact_id"], "expected_sha256": artifact["sha256"]})
    parent = service.store.namespace_root(CTX) / "inspection"
    assert list(parent.iterdir()) == []
    assert artifact_bytes(service, artifact)


def test_rejected_build_keeps_release_and_drawing_review(domain):
    service, source, *_ = domain
    render_and_build(domain)
    call(service, "export_step", coverage=coverage(source))
    before = service.call(CTX, "part_read", {"run_id": "plate"})
    assert before["part"]["release"] and before["drawing"]["review"]
    with pytest.raises(DomainError) as error:
        call(service, "build_code", code="result = None")
    assert error.value.code == "BUILD_CODE_DISABLED"
    after = service.call(CTX, "part_read", {"run_id": "plate"})
    assert after["part"]["release"] == before["part"]["release"]
    assert after["part"]["build"] == before["part"]["build"]
    assert after["drawing"]["review"] == before["drawing"]["review"]


def test_errors_keep_feature_and_field_without_host_paths(domain):
    service, *_ = domain
    error = service._public({"error": {
        "code": "FILLET_EDGE_COUNT", "feature_id": "fillet-1",
        "message": r"Edge count differs at /features/3/edges. See C:\Users\someone\worker\a.py and /tmp/worker/b.py"}})["error"]
    assert error["code"] == "FILLET_EDGE_COUNT" and error["feature_id"] == "fillet-1"
    assert "/features/3/edges" in error["message"]
    assert "someone" not in error["message"] and "/tmp/" not in error["message"]
    with pytest.raises(DomainError) as invalid:
        service.call(CTX, "part_read", {"run_id": 5})
    assert invalid.value.code == "INVALID_ARGUMENT"
    assert invalid.value.target == "/run_id" and "'type'" in invalid.value.message and '"string"' in invalid.value.message


def test_failed_job_keeps_its_public_report(domain):
    service, _, _, _, runner = domain
    runner.fail_operation = "build"
    job = service.call(CTX, "job_submit", {"operation": "build_from_description", "arguments": {"run_id": "plate", "expected_revision": 1}, "idempotency_key": "failed-report"})
    service.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = service.call(CTX, "job_get", {"job_id": job["job_id"]})
        if current["state"] == "failed":
            break
        time.sleep(0.02)
    assert current["state"] == "failed", current
    assert current["result"]["status"] == "fail"
    assert current["result"]["build"]["error"]["code"] == "TEST_WORKER_FAILED"


def test_reads_during_active_operation_return_a_snapshot(domain):
    service, *_ = domain
    with service._run_lock(CTX, "plate"):
        started = time.monotonic()
        part = service.call(CTX, "part_read", {"run_id": "plate"})
        drawing = service.call(CTX, "drawing_read", {"run_id": "plate"})
        elapsed = time.monotonic() - started
    assert elapsed < 5
    assert part["read_mode"] == drawing["read_mode"] == "snapshot_during_active_operation"
    assert part["part"]["revision"] == 1 and part["run_id"] == "plate"
    assert "read_mode" not in service.call(CTX, "part_read", {"run_id": "plate"})


def test_job_submit_schema_error_points_to_the_nested_argument(domain):
    service, *_ = domain
    with pytest.raises(DomainError) as error:
        service.call(CTX, "job_submit", {"operation": "build_from_description", "idempotency_key": "nested-error",
                                         "arguments": {"run_id": "/srv/private/secret", "expected_revision": 1}})
    assert error.value.target == "/arguments/run_id"
    assert "secret" not in error.value.message
