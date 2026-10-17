"""Evidence gates, durable state, and truthful CAD execution limits."""

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from drawing2cad_mcp.workflow import WorkflowError, WorkflowService


def artifact(path, content):
    path.write_bytes(content)
    return {"path": str(path.resolve()), "sha256": sha256(content).hexdigest()}


@pytest.fixture
def prepared(tmp_path):
    source = artifact(tmp_path / "source.pdf", b"authorized source")
    service = WorkflowService([tmp_path], tmp_path / "out")
    service.call("workflow_create_run", {"run_id": "run", "mode": "new_drawing", "units": "mm",
                                        "sources": [{**source, "role": "construction_source"}]})
    return service, source


def observe(service, source, *, revision=0, uncertainties=None):
    return service.call("workflow_observe", {"run_id": "run", "expected_state_revision": revision,
        "observations": [{"id": "obs1", "source_sha256": source["sha256"], "location": "page 1", "text": "Dimension D1 is visible."}],
        "uncertainties": uncertainties or []})


def drawing(service, tmp_path, *, state_revision=1, revision="A"):
    return service.call("workflow_register_drawing", {"run_id": "run", "expected_state_revision": state_revision,
        "drawing_id": "sheet", "revision": revision, "units": "mm", "dimension_ids": ["D1"],
        "editable": artifact(tmp_path / (revision + ".drawing"), b"editable " + revision.encode()),
        "render": artifact(tmp_path / (revision + ".png"), b"render " + revision.encode())})


def review(service, *, revision=2, findings=None):
    sheet = service.call("workflow_read_run", {"run_id": "run"})["run"]["drawing"]
    return service.call("workflow_review_drawing", {"run_id": "run", "expected_state_revision": revision,
        "drawing_revision": sheet["revision"], "reviewer": "Independent reviewer 1",
        "inspected_render_sha256": sheet["render"]["sha256"], "findings": findings or [],
        "notes": "Inspected the visible dimensions and sheet layout."})


def contract_args(*, revision=3):
    return {"run_id": "run", "expected_state_revision": revision, "revision": "C1", "contract": {
        "units": "mm", "drawing_revision": "A", "parameters": [{"id": "width", "value": 10, "dimension_id": "D1"}],
        "operations": [{"id": "base", "type": "extrusion", "depends_on": [], "parameter_ids": ["width"]}]}}


def fixed(prepared, tmp_path):
    service, source = prepared
    observe(service, source)
    drawing(service, tmp_path)
    review(service)
    service.call("workflow_fix_contract", contract_args())
    return service


def codes(result):
    return {row["code"] for row in result["defects"]}


def test_order_and_cad_backend_fail_closed(prepared, tmp_path):
    service, source = prepared
    early = service.call("workflow_check_readiness", {"run_id": "run", "phase": "export"})
    assert not early["ready"]
    assert {"OBSERVATIONS_REQUIRED", "DRAWING_REQUIRED", "DRAWING_REVIEW_REQUIRED", "CONTRACT_REQUIRED", "CAD_VALIDATION_UNAVAILABLE"} <= codes(early)
    with pytest.raises(WorkflowError, match="gate") as blocked:
        service.call("workflow_fix_contract", contract_args(revision=0))
    assert "DRAWING_REVIEW_REQUIRED" in codes(blocked.value.as_dict())
    service = fixed(prepared, tmp_path)
    for phase in ("build", "drawing_model_check", "export"):
        result = service.call("workflow_check_readiness", {"run_id": "run", "phase": phase})
        assert not result["ready"]
        assert codes(result) == {"CAD_VALIDATION_UNAVAILABLE"}
        assert result["cad_execution"] is False
        assert result["enforcement_scope"] == "managed_evidence_transitions_only"


def test_untrusted_passed_boolean_rejected(prepared, tmp_path):
    service, source = prepared
    observe(service, source)
    drawing(service, tmp_path)
    sheet = service.call("workflow_read_run", {"run_id": "run"})["run"]["drawing"]
    args = {"run_id": "run", "expected_state_revision": 2, "drawing_revision": "A", "reviewer": "reviewer",
            "inspected_render_sha256": sheet["render"]["sha256"], "findings": [], "notes": "Observed sheet", "passed": True}
    with pytest.raises(WorkflowError) as failure:
        service.call("workflow_review_drawing", args)
    assert failure.value.code == "INVALID_ARGUMENTS"


def test_blocking_review_and_uncertainty(prepared, tmp_path):
    service, source = prepared
    uncertainty = {"id": "u1", "status": "unresolved", "mandatory": True, "description": "Missing hole depth",
                   "target": "hole", "marker_id": "U1", "evidence_ids": ["obs1"]}
    observe(service, source, uncertainties=[uncertainty])
    drawing(service, tmp_path)
    with pytest.raises(WorkflowError) as failure:
        review(service)
    assert failure.value.code == "BLOCKING_UNCERTAINTY"
    uncertainty["status"] = "approved_assumption"
    with pytest.raises(WorkflowError) as failure:
        observe(service, source, revision=2, uncertainties=[uncertainty])
    assert failure.value.code == "DECISION_REFERENCE_REQUIRED"
    uncertainty["decision_ref"] = "User decision in request 5"
    observe(service, source, revision=2, uncertainties=[uncertainty])
    drawing(service, tmp_path, state_revision=3, revision="B")
    review(service, revision=4, findings=[{"code": "CLIPPED", "severity": "blocking", "target": "D1",
           "message": "Dimension is clipped.", "required_action": "Move the dimension and render a new revision."}])
    ready = service.call("workflow_check_readiness", {"run_id": "run", "phase": "freeze"})
    assert codes(ready) == {"DRAWING_REVIEW_BLOCKED"}
    assert service.call("workflow_read_run", {"run_id": "run"})["run"]["uncertainties"][0]["status"] == "approved_assumption"


def test_revision_invalidation_and_history(prepared, tmp_path):
    service = fixed(prepared, tmp_path)
    drawing(service, tmp_path, state_revision=4, revision="B")
    state = service.call("workflow_read_run", {"run_id": "run"})["run"]
    assert state["review"] is None and state["contract"] is None
    assert state["events"][2]["data"]["revision"] == "A"
    assert "DRAWING_REVIEW_REQUIRED" in codes(service.call("workflow_check_readiness", {"run_id": "run", "phase": "freeze"}))
    with pytest.raises(WorkflowError) as failure:
        drawing(service, tmp_path, state_revision=5, revision="A")
    assert failure.value.code == "REVISION_REUSED"


def test_stale_source_and_render_hashes(prepared, tmp_path):
    service = fixed(prepared, tmp_path)
    (tmp_path / "A.png").write_bytes(b"changed render")
    ready = service.call("workflow_check_readiness", {"run_id": "run", "phase": "build"})
    assert "ARTIFACT_HASH_MISMATCH" in codes(ready)
    state = service.call("workflow_read_run", {"run_id": "run"})
    assert state["integrity_defects"][0]["code"] == "ARTIFACT_HASH_MISMATCH"
    (tmp_path / "source.pdf").write_bytes(b"changed source")
    assert "SOURCE_HASH_MISMATCH" in codes(service.call("workflow_check_readiness", {"run_id": "run", "phase": "freeze"}))


def test_stale_review_and_contract_references(prepared, tmp_path):
    service, source = prepared
    observe(service, source)
    drawing(service, tmp_path)
    with pytest.raises(WorkflowError) as failure:
        service.call("workflow_review_drawing", {"run_id": "run", "expected_state_revision": 2,
            "drawing_revision": "A", "reviewer": "reviewer", "inspected_render_sha256": "0" * 64,
            "findings": [], "notes": "Review attempt"})
    assert failure.value.code == "DRAWING_REVISION_STALE"
    review(service)
    args = contract_args()
    args["contract"]["drawing_revision"] = "old"
    with pytest.raises(WorkflowError) as failure:
        service.call("workflow_fix_contract", args)
    assert failure.value.code == "DRAWING_REVISION_STALE"


@pytest.mark.parametrize("change,expected", [
    (lambda c: c["parameters"][0].update(dimension_id="missing"), "DIMENSION_MAPPING_INVALID"),
    (lambda c: c["operations"][0].update(depends_on=["missing"]), "DEPENDENCY_INVALID"),
    (lambda c: c["operations"][0].update(depends_on=["base"]), "OPERATION_CYCLE"),
    (lambda c: c.update(units="in"), "UNIT_MISMATCH"),
    (lambda c: c["operations"][0].update(parameter_ids=["missing"]), "PARAMETER_REFERENCE_INVALID"),
    (lambda c: c["parameters"][0].update(value=float("nan")), "INVALID_ARGUMENTS"),
])
def test_contract_defects(prepared, tmp_path, change, expected):
    service, source = prepared
    observe(service, source)
    drawing(service, tmp_path)
    review(service)
    args = contract_args()
    change(args["contract"])
    with pytest.raises(WorkflowError) as failure:
        service.call("workflow_fix_contract", args)
    assert failure.value.code == expected


def test_restart_and_interrupted_write_keep_checkpoint(prepared, tmp_path):
    service = fixed(prepared, tmp_path)
    restarted = WorkflowService([tmp_path], tmp_path / "out")
    before = restarted.call("workflow_read_run", {"run_id": "run"})["run"]
    assert before["state_revision"] == 4
    assert before["drawing"]["revision"] == "A"
    with patch("drawing2cad_mcp.workflow.os.replace", side_effect=OSError("interrupted")):
        with pytest.raises(OSError):
            drawing(restarted, tmp_path, state_revision=4, revision="B")
    assert restarted.call("workflow_read_run", {"run_id": "run"})["run"] == before
    assert not list((tmp_path / "out" / "workflow").glob("*.tmp"))


def concurrent_observe(paths):
    root, source = paths
    service = WorkflowService([root], Path(root) / "out")
    try:
        observe(service, source)
        return "committed"
    except WorkflowError as error:
        return error.code


@pytest.mark.parametrize("executor", [ThreadPoolExecutor, ProcessPoolExecutor])
def test_cross_instance_revision_conflict(prepared, tmp_path, executor):
    _, source = prepared
    with executor(max_workers=2) as pool:
        results = list(pool.map(concurrent_observe, [(str(tmp_path), source)] * 2))
    assert sorted(results) == ["STATE_REVISION_CONFLICT", "committed"]
    service = WorkflowService([tmp_path], tmp_path / "out")
    assert service.call("workflow_read_run", {"run_id": "run"})["run"]["state_revision"] == 1


def test_path_hash_and_role_bounds(prepared, tmp_path):
    service, source = prepared
    bad = deepcopy(source)
    bad["sha256"] = "0" * 64
    with pytest.raises(WorkflowError) as failure:
        service.call("workflow_create_run", {"run_id": "bad", "mode": "new_drawing", "units": "mm",
                                            "sources": [{**bad, "role": "construction_source"}]})
    assert failure.value.code == "SOURCE_HASH_MISMATCH"
    with pytest.raises(WorkflowError) as failure:
        service.call("workflow_read_run", {"run_id": "../run"})
    assert failure.value.code == "INVALID_ARGUMENTS"
    service.call("workflow_create_run", {"run_id": "verification", "mode": "new_drawing", "units": "mm",
                                        "sources": [{**source, "role": "verification_only"}]})
    args = {"run_id": "verification", "expected_state_revision": 0,
            "observations": [{"id": "o", "source_sha256": source["sha256"], "location": "p1", "text": "data"}], "uncertainties": []}
    with pytest.raises(WorkflowError) as failure:
        service.call("workflow_observe", args)
    assert failure.value.code == "SOURCE_ROLE_FORBIDDEN"


def test_corrupt_persisted_state_is_rejected(prepared, tmp_path):
    service, _ = prepared
    (tmp_path / "out" / "workflow" / "run.json").write_text('{"schema_version":1}', encoding="utf8")
    with pytest.raises(WorkflowError) as failure:
        service.call("workflow_read_run", {"run_id": "run"})
    assert failure.value.code == "STATE_INVALID"


def test_changed_drawing_can_be_replaced_by_new_revision(prepared, tmp_path):
    service = fixed(prepared, tmp_path)
    (tmp_path / "A.png").write_bytes(b"modified old render")
    drawing(service, tmp_path, state_revision=4, revision="B")
    state = service.call("workflow_read_run", {"run_id": "run"})
    assert not state["integrity_defects"]
    assert state["run"]["review"] is None
    assert state["run"]["phase"] == "drawing_prepare"
    assert state["run"]["next_phase"] == "drawing_review"


def test_contract_hash_and_phase_survive_restart(prepared, tmp_path):
    service = fixed(prepared, tmp_path)
    state = WorkflowService([tmp_path], tmp_path / "out").call("workflow_read_run", {"run_id": "run"})["run"]
    contract = state["contract"]
    canonical = json.dumps({key: contract[key] for key in ("revision", "contract", "drawing_ref")},
                           sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    assert contract["sha256"] == sha256(canonical).hexdigest()
    assert contract["drawing_ref"]["editable_sha256"] == state["drawing"]["editable"]["sha256"]
    assert contract["drawing_ref"]["render_sha256"] == state["drawing"]["render"]["sha256"]
    assert state["phase"] == "freeze" and state["next_phase"] == "build"
    assert state["toolchain"]["cad_backend"] is None


@pytest.mark.parametrize("change", [
    lambda s: s["events"][0].update(tool="fake"),
    lambda s: s["events"][0].update(state_revision=9),
    lambda s: s.update(drawing="fake"),
    lambda s: s.update(phase="export"),
])
def test_malformed_history_is_rejected(prepared, tmp_path, change):
    service, _ = prepared
    path = tmp_path / "out" / "workflow" / "run.json"
    state = json.loads(path.read_text(encoding="utf8"))
    change(state)
    path.write_text(json.dumps(state), encoding="utf8")
    with pytest.raises(WorkflowError) as failure:
        service.call("workflow_read_run", {"run_id": "run"})
    assert failure.value.code == "STATE_INVALID"


def test_artifact_outside_authorized_roots_is_rejected(tmp_path):
    allowed = tmp_path / "authorized"
    allowed.mkdir()
    source = artifact(tmp_path / "outside.pdf", b"outside authorized sources")
    service = WorkflowService([allowed], tmp_path / "out")
    with pytest.raises(WorkflowError) as failure:
        service.call("workflow_create_run", {"run_id": "outside", "mode": "new_drawing", "units": "mm",
                                            "sources": [{**source, "role": "construction_source"}]})
    assert failure.value.code == "ARTIFACT_PATH_FORBIDDEN"


def test_step_only_mode_cannot_enter_drawing_path(tmp_path):
    source = artifact(tmp_path / "model.step", b"STEP content")
    service = WorkflowService([tmp_path], tmp_path / "out")
    service.call("workflow_create_run", {"run_id": "run", "mode": "import_step", "units": "mm",
                                        "sources": [{**source, "role": "construction_source"}]})
    result = service.call("workflow_check_readiness", {"run_id": "run", "phase": "drawing_prepare"})
    assert not result["ready"]
    assert "MODE_NOT_IMPLEMENTED" in codes(result)


@pytest.mark.parametrize("run_id", ["CON", "nul", "COM1", "LPT9.more"])
def test_reserved_windows_run_names_are_rejected(prepared, run_id):
    service, _ = prepared
    with pytest.raises(WorkflowError) as failure:
        service.call("workflow_read_run", {"run_id": run_id})
    assert failure.value.code == "INVALID_ARGUMENTS"


def test_content_and_manifest_byte_limits(prepared, tmp_path, monkeypatch):
    service, source = prepared
    monkeypatch.setattr("drawing2cad_mcp.workflow.MAX_ARTIFACT_BYTES", 2)
    result = service.call("workflow_check_readiness", {"run_id": "run", "phase": "observe"})
    assert "ARTIFACT_LIMIT" in codes(result)
    monkeypatch.setattr("drawing2cad_mcp.workflow.MAX_ARTIFACT_BYTES", 104857600)
    monkeypatch.setattr("drawing2cad_mcp.workflow.MAX_STATE_BYTES", 2)
    with pytest.raises(WorkflowError) as failure:
        service.call("workflow_read_run", {"run_id": "run"})
    assert failure.value.code == "STATE_INVALID"


def test_initialization_does_not_create_workflow_directory(tmp_path):
    output = tmp_path / "out"
    WorkflowService([tmp_path], output)
    assert not output.exists()


def test_snapshot_cannot_add_unrecorded_observations(prepared, tmp_path):
    service, source = prepared
    path = tmp_path / "out" / "workflow" / "run.json"
    state = json.loads(path.read_text(encoding="utf8"))
    state["observations"] = [{"id": "injected", "source_sha256": source["sha256"], "location": "p1", "text": "injected"}]
    state["next_phase"] = "drawing_prepare"
    path.write_text(json.dumps(state), encoding="utf8")
    with pytest.raises(WorkflowError) as failure:
        service.call("workflow_read_run", {"run_id": "run"})
    assert failure.value.code == "STATE_INVALID"


@pytest.mark.parametrize("change", [
    lambda s: s["contract"]["contract"]["operations"][0].update(depends_on=["unknown"]),
    lambda s: s["contract"]["contract"]["parameters"][0].update(dimension_id="unknown"),
    lambda s: s["sources"][0].update(role="verification_only"),
])
def test_recomputed_hash_does_not_bypass_history_validation(prepared, tmp_path, change):
    service = fixed(prepared, tmp_path)
    path = tmp_path / "out" / "workflow" / "run.json"
    state = json.loads(path.read_text(encoding="utf8"))
    change(state)
    state["contract"]["sha256"] = service._contract_hash(state["contract"])
    path.write_text(json.dumps(state), encoding="utf8")
    with pytest.raises(WorkflowError) as failure:
        service.call("workflow_read_run", {"run_id": "run"})
    assert failure.value.code == "STATE_INVALID"


def test_semantically_invalid_event_and_matching_snapshot_are_rejected(prepared, tmp_path):
    service = fixed(prepared, tmp_path)
    path = tmp_path / "out" / "workflow" / "run.json"
    state = json.loads(path.read_text(encoding="utf8"))
    state["contract"]["contract"]["operations"][0]["depends_on"] = ["unknown"]
    state["events"][-1]["data"]["contract"]["operations"][0]["depends_on"] = ["unknown"]
    state["contract"]["sha256"] = service._contract_hash(state["contract"])
    path.write_text(json.dumps(state), encoding="utf8")
    with pytest.raises(WorkflowError) as failure:
        service.call("workflow_read_run", {"run_id": "run"})
    assert failure.value.code == "STATE_INVALID"


def test_observe_readiness_requires_construction_source(prepared):
    service, source = prepared
    service.call("workflow_create_run", {"run_id": "reference", "mode": "new_drawing", "units": "mm",
                                        "sources": [{**source, "role": "verification_only"}]})
    result = service.call("workflow_check_readiness", {"run_id": "reference", "phase": "observe"})
    assert not result["ready"]
    assert codes(result) == {"CONSTRUCTION_SOURCE_REQUIRED"}
