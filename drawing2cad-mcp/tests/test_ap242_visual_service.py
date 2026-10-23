"""Test inspection boundaries with fake output; this is not CAD acceptance."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from drawing2cad_mcp.domain_store import DomainError
from test_domain_service import CTX, OTHER, domain
from test_m3_service import ReplayRunner


class VisualRunner(ReplayRunner):
    def __init__(self, storage, description):
        super().__init__(storage, description)
        self.visual_hash_bad = False
        self.artifact_hash_bad = False
        self.path_bad = False

    def run(self, operation, *, input_step=None, description=None, **kwargs):
        if operation != "ap242_visual":
            return super().run(operation, input_step=input_step, description=description, **kwargs)
        assert description is None and not kwargs
        self.calls.append(operation)
        if self.fail_operation == operation:
            return {"status": "fail", "error": {"code": "SYNTHETIC_RENDER_FAILURE", "message": "Injected failure."}}
        directory = self.storage / uuid4().hex
        directory.mkdir(parents=True)
        artifacts = []
        for name, media, role in [("ap242-inspection.pdf", "application/pdf", "ap242_visual_inspection"),
                                  ("ap242-inspection.png", "image/png", "ap242_visual_overview"),
                                  ("ap242-inspection-detail.png", "image/png", "ap242_visual_detail")]:
            path = directory / name
            path.write_bytes(b"Synthetic service-boundary test; not a real rendering.")
            artifacts.append({"path": str(path.parent / "wrong.png" if self.path_bad else path),
                              "bytes": path.stat().st_size, "sha256": "0" * 64 if self.artifact_hash_bad else hashlib.sha256(path.read_bytes()).hexdigest(),
                              "media_type": media, "role": role})
        return {"status": "pass", "source_sha256": "0" * 64 if self.visual_hash_bad else hashlib.sha256(input_step.read_bytes()).hexdigest(),
                "source_bytes": input_step.stat().st_size, "artifacts": artifacts,
                "worker": {"worker_id": directory.name, "work_dir": str(directory)},
                "visual_review": "not_tested", "target_cad_opening": "not_tested"}


def prepare(domain, *, build=True, profile="ap242"):
    service, _, description, _, _ = domain
    cad = service._backend(CTX)[0]
    runner = VisualRunner(cad.runner.storage, description)
    cad.runner = runner
    if build:
        result = service.call(CTX, "build_from_description", {"run_id": "plate", "expected_revision": 1,
                                                            "export_profile": profile})
        assert result["status"] == "pass"
    runner.calls.clear()
    return service, cad, runner


def artifact(service, cad):
    path = cad._directory("plate") / "synthetic.step"
    path.write_bytes(b"Synthetic STEP placeholder for ownership tests.")
    return service.store.artifact_register(CTX, path, "released_step", "plate", 1, "model/step", "part.step")


def test_candidate_inspection_before_release_keeps_model_state(domain):
    service, cad, runner = prepare(domain)
    before = deepcopy(cad._load(cad._directory("plate")))
    result = service.call(CTX, "part_render_pmi", {"run_id": "plate", "expected_revision": 1})
    assert result["status"] == "pass" and result["released"] is False
    assert result["source_sha256"] == before["build"]["candidate_sha256"]
    assert result["description_sha256"] == before["description_sha256"]
    assert result["inspection"]["visual_review"] == "not_tested"
    assert len(result["artifacts"]) == 4
    assert all(item["run_id"] == "plate" and item["revision"] == 1 for item in result["artifacts"])
    assert cad._load(cad._directory("plate")) == before
    assert runner.calls == ["ap242_visual"]
    assert '"path"' not in json.dumps(result) and '"work_dir"' not in json.dumps(result)
    events = [json.loads(path.read_text()) for path in (cad._directory("plate") / "domain-events").glob("*.json")]
    event = next(item for item in events if item["operation"] == "part_render_pmi")
    assert event["status"] == "pass" and event["source_sha256"] == result["source_sha256"]
    assert event["artifacts"] == result["artifacts"]


@pytest.mark.parametrize("case,code", [("unbuilt", "VALIDATED_BUILD_REQUIRED"),
                                      ("ap214", "AP242_PROFILE_REQUIRED"),
                                      ("stale", "REVISION_CONFLICT"),
                                      ("changed", "CANDIDATE_CHANGED")])
def test_candidate_requires_current_unmodified_ap242_build(domain, case, code):
    service, cad, runner = prepare(domain, build=case != "unbuilt", profile="ap214" if case == "ap214" else "ap242")
    if case == "changed":
        Path(cad._load(cad._directory("plate"))["build"]["candidate_path"]).write_bytes(b"changed")
    with pytest.raises(DomainError) as failure:
        service.call(CTX, "part_render_pmi", {"run_id": "plate", "expected_revision": 2 if case == "stale" else 1})
    assert failure.value.code == code
    assert runner.calls == []


def test_other_principal_cannot_inspect_candidate_or_artifact(domain):
    service, cad, runner = prepare(domain)
    stored = artifact(service, cad)
    with pytest.raises(DomainError) as failure:
        service.call(OTHER, "part_render_pmi", {"run_id": "plate", "expected_revision": 1})
    assert failure.value.code == "NOT_FOUND"
    with pytest.raises(DomainError):
        service.call(OTHER, "step_render_pmi", {"artifact_id": stored["artifact_id"], "expected_sha256": stored["sha256"]})
    assert runner.calls == []


def test_artifact_inspection_requires_exact_hash(domain):
    service, cad, runner = prepare(domain)
    stored = artifact(service, cad)
    with pytest.raises(DomainError) as failure:
        service.call(CTX, "step_render_pmi", {"artifact_id": stored["artifact_id"], "expected_sha256": "0" * 64})
    assert failure.value.code == "ARTIFACT_HASH_MISMATCH" and runner.calls == []
    result = service.call(CTX, "step_render_pmi", {"artifact_id": stored["artifact_id"], "expected_sha256": stored["sha256"]})
    assert result["status"] == "pass" and result["source_artifact_id"] == stored["artifact_id"]
    assert result["source_sha256"] == stored["sha256"]


@pytest.mark.parametrize("flag,code", [("visual_hash_bad", "INSPECTION_HASH_MISMATCH"),
                                      ("artifact_hash_bad", "INTEGRITY_ERROR"),
                                      ("path_bad", "INVALID_WORKER_ARTIFACT")])
def test_worker_cannot_publish_unbound_or_changed_inspection(domain, flag, code):
    service, cad, runner = prepare(domain)
    before = service.store.artifact_list(CTX, run_id="plate")["items"]
    assert len(before) == 1 and before[0]["role"] == "step_candidate"
    setattr(runner, flag, True)
    with pytest.raises(DomainError) as failure:
        service.call(CTX, "part_render_pmi", {"run_id": "plate", "expected_revision": 1})
    assert failure.value.code == code
    assert service.store.artifact_list(CTX, run_id="plate")["items"] == before


def test_failed_inspection_is_not_published(domain):
    service, cad, runner = prepare(domain)
    before = service.store.artifact_list(CTX, run_id="plate")["items"]
    assert len(before) == 1 and before[0]["role"] == "step_candidate"
    runner.fail_operation = "ap242_visual"
    result = service.call(CTX, "part_render_pmi", {"run_id": "plate", "expected_revision": 1})
    assert result["status"] == "fail" and "artifacts" not in result
    assert service.store.artifact_list(CTX, run_id="plate")["items"] == before
