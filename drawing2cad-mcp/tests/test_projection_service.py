"""Service boundary of model_projection_check with fake worker output; this is not CAD acceptance."""

import hashlib
from uuid import uuid4

import pytest

from drawing2cad_mcp.domain_store import DomainError
from test_domain_service import CTX, domain  # noqa: F401
from test_m3_service import ReplayRunner

VIEWS = [{"view_id": "top", "region": [10, 10, 150, 120], "toward_viewer": "+Z", "up": "+Y", "mm_per_sheet_mm": 1.0}]


class ProjectionRunner(ReplayRunner):
    def __init__(self, storage, description):
        super().__init__(storage, description)
        self.received = None
        self.path_bad = False

    def run(self, operation, *, input_step=None, description=None, **kwargs):
        if operation != "projection_check":
            return super().run(operation, input_step=input_step, description=description, **kwargs)
        self.calls.append(operation)
        self.received = {"step": hashlib.sha256(input_step.read_bytes()).hexdigest(),
                         "pdf": hashlib.sha256(kwargs["input_pdf"].read_bytes()).hexdigest(),
                         "page": kwargs["page"], "views": kwargs["views"]}
        directory = self.storage / uuid4().hex
        directory.mkdir(parents=True)
        path = directory / "projection-overlay.png"
        path.write_bytes(b"Synthetic service-boundary test; not a real overlay.")
        return {"status": "pass", "views": [{"view_id": "top", "status": "pass", "model_to_drawing": {"p95_mm": 0.05, "max_mm": 0.1}}],
                "artifacts": [{"name": path.name, "path": str(directory / "other.png" if self.path_bad else path),
                               "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                               "role": "projection_overlay"}],
                "worker": {"worker_id": directory.name, "work_dir": str(directory)}}


def prepare(domain, *, build=True):
    service, source, description, _, _ = domain
    cad = service._backend(CTX)[0]
    runner = ProjectionRunner(cad.runner.storage, description)
    cad.runner = runner
    if build:
        assert service.call(CTX, "build_from_description", {"run_id": "plate", "expected_revision": 1})["status"] == "pass"
    return service, source, cad, runner


def call(service, source, **extra):
    return service.call(CTX, "model_projection_check", {"run_id": "plate", "expected_revision": 1,
                                                        "source_id": source["source_id"], "page": 1, "views": VIEWS, **extra})


def test_projection_check_binds_candidate_source_and_artifacts(domain):
    service, source, cad, runner = prepare(domain)
    result = call(service, source)
    assert result["status"] == "pass" and result["claim"] == "drawing_model_consistency"
    built = cad._load(cad._directory("plate"))["build"]
    assert runner.received["step"] == built["candidate_sha256"] == result["candidate_sha256"]
    assert runner.received["pdf"] == source["sha256"] == result["source_sha256"]
    assert runner.received["views"] == VIEWS
    assert [item["role"] for item in result["artifacts"]] == ["projection_overlay", "projection_report"]


def test_projection_check_requires_a_current_validated_build(domain):
    service, source, _, runner = prepare(domain, build=False)
    with pytest.raises(DomainError) as error:
        call(service, source)
    assert error.value.code == "VALIDATED_BUILD_REQUIRED"
    assert "projection_check" not in runner.calls


def test_projection_check_rejects_a_changed_worker_path(domain):
    service, source, _, runner = prepare(domain)
    runner.path_bad = True
    with pytest.raises(DomainError) as error:
        call(service, source)
    assert error.value.code == "INVALID_WORKER_ARTIFACT"


def test_projection_check_rejects_invalid_views(domain):
    service, source, _, _ = prepare(domain)
    for view in ({**VIEWS[0], "toward_viewer": "+Q"}, {**VIEWS[0], "mm_per_sheet_mm": 0}, {**VIEWS[0], "extra": 1},
                 {**VIEWS[0], "up": "-Z"}, {**VIEWS[0], "region": [150, 10, 10, 120]}, {**VIEWS[0], "hidden_lines": "compare"}):
        with pytest.raises(DomainError):
            call(service, source, views=[view])


def test_worker_timeout_stays_a_failed_unperformed_comparison(domain, monkeypatch):
    service, source, cad, runner = prepare(domain)
    before = cad._load(cad._directory("plate"))
    received = {}

    def timeout(operation, **kwargs):
        received.update(operation=operation, arguments=kwargs)
        return {"status": "fail", "error": {"code": "WORKER_TIMEOUT", "message": "The worker exceeded its configured limit."}}

    monkeypatch.setattr(runner, "run", timeout)
    result = call(service, source)
    assert result["status"] == "fail"
    assert result["error"]["code"] == "WORKER_TIMEOUT"
    assert result["views"] == [] and result["artifacts"] == []
    assert received["operation"] == "projection_check"
    assert "timeout" not in received["arguments"]
    assert cad._load(cad._directory("plate")) == before
