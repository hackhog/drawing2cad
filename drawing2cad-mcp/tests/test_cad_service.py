"""Service lifecycle tests use fake workers, never claim CAD acceptance."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import uuid

import pytest
from jsonschema import Draft202012Validator

from drawing2cad_mcp.cad_service import CadError, CadService
from drawing2cad_mcp.cad_tools import CAD_SCHEMAS
from drawing2cad_mcp.config import CadSettings
from test_part_schema import sample_description


REQUIRED_CHECKS = ["step_reimport", "solid_validity", "solid_count", "positive_volume", "step_references", "step_product_name", "step_units_mm", "step_schema_present", "drawing_measurements", "overall"]


class FakeRunner:
    def __init__(self, storage):
        self.storage = storage.resolve()
        self.calls = []
        self.fail_operation = None
        self.omit_measurements = False
        self.wrong_import_volume = False
        self.fail_import_measurement = False
        self.same_worker = False
        self.path_override = None
        self.probe_status = "pass"

    def capabilities(self):
        return {"available": True, "profile": "unit-test-fake"}

    def probe(self):
        return {"status": self.probe_status, "checks": [{"check": "fake_probe", "status": self.probe_status}]}

    def run(self, operation, *, description=None, input_step=None, **kwargs):
        self.calls.append(operation)
        identifier = "same" if self.same_worker else uuid.uuid4().hex
        directory = self.storage / identifier
        directory.mkdir(parents=True, exist_ok=True)
        worker = {"worker_id": identifier, "work_dir": str(directory)}
        if self.fail_operation == operation:
            return {"status": "fail", "error": {"code": "TEST_WORKER_FAILED", "message": "Injected failure."}, "worker": worker}
        measured = {"volume_mm3": 1000, "bbox_min": [0, 0, 0], "bbox_max": [20, 10, 5]}
        if operation in {"build", "build_code"}:
            candidate = directory / "candidate.step"
            candidate.write_bytes(b"ISO-10303-21; synthetic unit-test placeholder")
            return {"status": "pass", "candidate_step": str(self.path_override or candidate), "worker": worker, "measured": measured,
                    "checks": [{"check": "fresh_worker_reimport", "status": "not_tested"}]}
        assert operation == "validate"
        if self.wrong_import_volume:
            measured["volume_mm3"] = 123
        checks = [{"check": name, "status": "not_tested" if self.omit_measurements and name == "drawing_measurements" else "pass"} for name in REQUIRED_CHECKS]
        if self.fail_import_measurement:
            next(item for item in checks if item["check"] == "drawing_measurements")["status"] = "fail"
        checks.extend({"check": name, "status": "not_tested"} for name in ["target_cad_open", "semantic_pmi", "independent_step_conformance"])
        return {"status": "fail" if self.fail_import_measurement else "pass", "checks": checks, "worker": worker, "measured": measured, "step": {"sha256": hashlib.sha256(input_step.read_bytes()).hexdigest()}}


@pytest.fixture
def setup_service(tmp_path):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    pdf = source_dir / "part.pdf"
    pdf.write_bytes(b"%PDF-1.7\nSynthetic registration test only.")
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    description = sample_description()
    description["evidence"][0]["source"].update(source_id="drawing", source_sha256=digest)
    source = {"path": str(pdf), "sha256": digest, "role": "construction", "source_id": "drawing"}
    runner = FakeRunner(tmp_path / "output" / "cad" / "workers")
    settings = CadSettings(enabled=True)
    service = CadService([source_dir], tmp_path / "output", settings, runner=runner)
    return service, runner, description, source


def create(setup):
    service, runner, description, source = setup
    result = service.part_create(run_id="example", description=description, sources=[source])
    assert result["revision"] == 1
    return result


def coverage(source):
    return {"reviewer": "Synthetic test reviewer", "source_hashes": [source["sha256"]], "views": {"total": 1, "reviewed": 1}, "features": {"total": 1, "reviewed": 1}, "printed_dimensions": {"total": 3, "reviewed": 3}, "critical_measurement_ids": ["overall"], "reason": "Synthetic lifecycle test; no real source acceptance."}


def test_catalog_schemas_are_valid_and_closed():
    for schema in CAD_SCHEMAS.values():
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
    assert len(json.dumps(CAD_SCHEMAS)) < 20000


def test_profile_extrusion_passes_granular_tool_schema(setup_service):
    from test_profile_features import profile_description

    service, _, _, _ = setup_service
    create(setup_service)
    feature = profile_description()["features"][0]
    for segment in feature["segments"]:
        for key in ("start", "mid", "end"):
            if key in segment:
                segment[key] = [10 if isinstance(value, dict) else value for value in segment[key]]
    arguments = {"run_id": "example", "expected_revision": 1, "feature": feature}
    Draft202012Validator(CAD_SCHEMAS["create_base_body"]).validate(arguments)
    result = service.create_base_body(**arguments)
    assert result["revision"] == 2
    assert service.part_read(run_id="example")["part"]["description"]["features"][0]["type"] == "profile_extrusion"


def test_create_read_restart_and_revision_conflict(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    updated = deepcopy(description)
    updated["parameters"][0]["value"] = 21
    result = service.part_update(run_id="example", expected_revision=1, description=updated)
    assert result["revision"] == 2
    with pytest.raises(CadError, match="current revision") as error:
        service.part_update(run_id="example", expected_revision=1, description=description)
    assert error.value.code == "REVISION_CONFLICT"
    restarted = CadService(service.allowed_roots, service.output_root, service.settings, runner=runner)
    state = restarted.part_read(run_id="example")
    assert state["revision"] == 2 and state["call_count"] == 4
    assert state["part"]["events"][-1]["status"] == "fail"


def test_granular_add_and_revision_invalidation(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    service.build_from_description(run_id="example", expected_revision=1)
    result = service.add_hole(run_id="example", expected_revision=1, feature={"type": "hole", "id": "hole", "position": [5, 5, 5], "diameter": 3, "evidence_ids": ["drawing"]})
    assert result["revision"] == 2
    state = service.part_read(run_id="example")["part"]
    assert state["build"] is None and state["release"] is None
    assert [item["id"] for item in state["description"]["features"]] == ["base", "hole"]


def test_end_to_end_candidate_release_and_report(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    built = service.build_from_description(run_id="example", expected_revision=1)
    assert runner.calls == ["build", "validate"]
    assert built["status"] == "pass" and not built["released"]
    for checks in (built["build"]["build"]["checks"], built["build"]["validation"]["checks"]):
        assert [item["status"] for item in checks if item["check"] == "fresh_worker_reimport"] == ["pass"]
    stored = json.loads((service.storage / "runs" / "example" / "state.json").read_text(encoding="utf-8"))["build"]
    assert stored["build"]["checks"] == built["build"]["build"]["checks"]
    assert stored["validation"]["checks"] == built["build"]["validation"]["checks"]
    released = service.export_step(run_id="example", expected_revision=1, coverage=coverage(source))
    assert released["release"]["schema_version"] == 2
    assert released["release"]["profile"] == "validated_geometry_step"
    assert "metric_acceptance" not in released["release"]
    assert next(item for item in released["checks"] if item["check"] == "target_cad_open")["status"] == "not_tested"
    report = service.part_export_review(run_id="example", expected_revision=1)
    assert {Path(item["path"]).name for item in report["artifacts"]} == {"part.json", "review.md", "review.csv", "coverage.json", "trace.jsonl", "manifest.json"}
    trace = Path(next(item["path"] for item in report["artifacts"] if item["path"].endswith("trace.jsonl")))
    assert len(trace.read_text(encoding="utf-8").splitlines()) == 3
    for artifact in report["artifacts"]:
        assert hashlib.sha256(Path(artifact["path"]).read_bytes()).hexdigest() == artifact["sha256"]


def test_stored_legacy_release_remains_readable_without_new_acceptance_claims(setup_service):
    service, runner, _, source = setup_service
    create(setup_service)
    service.build_from_description(run_id="example", expected_revision=1)
    service.export_step(run_id="example", expected_revision=1, coverage=coverage(source))
    directory = service.storage / "runs" / "example"
    state_path = directory / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    legacy = state["release"]
    legacy.pop("schema_version")
    legacy.update(profile="validated_prototype_step", metric_acceptance="not_tested")
    service._save(directory, state)
    release_bytes = Path(legacy["path"]).read_bytes()

    restarted = CadService(service.allowed_roots, service.output_root, service.settings, runner=runner)
    assert restarted.part_read(run_id="example")["part"]["release"] == legacy
    assert json.loads(state_path.read_text(encoding="utf-8"))["release"] == legacy
    assert Path(legacy["path"]).read_bytes() == release_bytes
    report = restarted.part_export_review(run_id="example", expected_revision=1)
    manifest = next(Path(item["path"]) for item in report["artifacts"] if item["path"].endswith("manifest.json"))
    assert json.loads(manifest.read_text(encoding="utf-8"))["release"] == legacy
    current = restarted.export_step(run_id="example", expected_revision=1, coverage=coverage(source))["release"]
    assert current["schema_version"] == 2 and current["profile"] == "validated_geometry_step"
    assert current["sha256"] == legacy["sha256"]
    assert "metric_acceptance" not in current and "pair" not in current


@pytest.mark.parametrize("mutation,code", [
    (lambda source: source.update(sha256="0" * 64), "SOURCE_HASH_MISMATCH"),
    (lambda source: source.update(source_id="another"), "EVIDENCE_SOURCE_MISMATCH"),
    (lambda source: source.update(role="verification"), "CONSTRUCTION_SOURCE_REQUIRED"),
])
def test_source_bindings_reject_wrong_hash_identity_or_role(setup_service, mutation, code):
    service, runner, description, source = setup_service
    mutation(source)
    with pytest.raises(CadError) as error:
        service.part_create(run_id="example", description=description, sources=[source])
    assert error.value.code == code


def test_verification_evidence_cannot_feed_construction(setup_service):
    service, runner, description, source = setup_service
    verification = Path(source["path"]).with_name("verify.pdf")
    verification.write_bytes(b"%PDF-1.7 verification")
    second = {"path": str(verification), "sha256": hashlib.sha256(verification.read_bytes()).hexdigest(), "role": "verification", "source_id": "verification"}
    description["evidence"][0]["source"].update(source_id="verification", source_sha256=second["sha256"])
    with pytest.raises(CadError) as error:
        service.part_create(run_id="example", description=description, sources=[source, second])
    assert error.value.code == "VERIFICATION_SOURCE_USED_FOR_CONSTRUCTION"


def test_source_change_invalidates_build_attempt_and_is_recorded(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    Path(source["path"]).write_bytes(b"%PDF-1.7 changed")
    with pytest.raises(CadError) as error:
        service.build_from_description(run_id="example", expected_revision=1)
    assert error.value.code == "SOURCE_HASH_MISMATCH"
    assert not runner.calls
    assert service.part_read(run_id="example")["part"]["events"][-1]["error"]["code"] == "SOURCE_HASH_MISMATCH"


@pytest.mark.parametrize("operation", ["build", "validate"])
def test_worker_failure_never_releases(setup_service, operation):
    service, runner, description, source = setup_service
    create(setup_service)
    runner.fail_operation = operation
    failed = service.build_from_description(run_id="example", expected_revision=1)
    assert failed["status"] == "fail"
    assert failed["error"] == {"code": "TEST_WORKER_FAILED", "message": "Injected failure.", "feature_id": None}
    assert failed["feature_id"] is None
    assert all(check["status"] in {"pass", "fail"} for check in failed["checks"])
    if operation == "validate":
        assert failed["checks"]
        checks = failed["build"]["build"]["checks"]
        assert [item["status"] for item in checks if item["check"] == "fresh_worker_reimport"] == ["fail"]
        assert [item["status"] for item in failed["build"]["validation"]["checks"] if item["check"] == "fresh_worker_reimport"] == ["fail"]
    else:
        assert failed["validation"]["status"] == "not_tested"
        assert failed["checks"] == []
    with pytest.raises(CadError) as error:
        service.export_step(run_id="example", expected_revision=1, coverage=coverage(source))
    assert error.value.code == "VALIDATED_BUILD_REQUIRED"


def test_ap242_schema_failure_reports_completed_checks(setup_service, monkeypatch):
    service, runner, _, _ = setup_service
    create(setup_service)
    original = runner.run

    def run(operation, **kwargs):
        result = original(operation, **kwargs)
        if operation == "validate":
            result["step"]["schemas"] = ["AUTOMOTIVE_DESIGN"]
        return result

    monkeypatch.setattr(runner, "run", run)
    failed = service.build_from_description(run_id="example", expected_revision=1, export_profile="ap242")
    assert failed["status"] == "fail"
    assert failed["error"]["code"] == "AP242_SCHEMA_REQUIRED"
    assert failed["feature_id"] is None
    assert {item["phase"] for item in failed["checks"]} == {"build", "validation", "agreement"}
    assert failed["checks"][-1] == {"check": "ap242_schema_header", "status": "fail", "phase": "validation"}


@pytest.mark.parametrize("field,code", [("same_worker", "FRESH_WORKER_REQUIRED"), ("path_override", "INVALID_WORKER_ARTIFACT")])
def test_worker_identity_and_fixed_candidate_path(setup_service, field, code, tmp_path):
    service, runner, description, source = setup_service
    create(setup_service)
    setattr(runner, field, tmp_path / "outside.step" if field == "path_override" else True)
    with pytest.raises(CadError) as error:
        service.build_from_description(run_id="example", expected_revision=1)
    assert error.value.code == code


def test_import_geometry_mismatch_fails(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    runner.wrong_import_volume = True
    result = service.build_from_description(run_id="example", expected_revision=1)
    assert result["status"] == "fail"
    assert result["build"]["agreement"]["status"] == "fail"


def test_failed_import_measurement_preserves_successful_fresh_reimport(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    runner.fail_import_measurement = True
    result = service.build_from_description(run_id="example", expected_revision=1)
    assert result["status"] == "fail"
    assert [item["status"] for item in result["build"]["validation"]["checks"] if item["check"] == "step_reimport"] == ["pass"]
    for checks in (result["build"]["build"]["checks"], result["build"]["validation"]["checks"]):
        assert [item["status"] for item in checks if item["check"] == "fresh_worker_reimport"] == ["pass"]


def test_absent_measurements_and_incomplete_coverage_block_release(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    runner.omit_measurements = True
    service.build_from_description(run_id="example", expected_revision=1)
    with pytest.raises(CadError) as error:
        service.export_step(run_id="example", expected_revision=1, coverage=coverage(source))
    assert error.value.code == "RELEASE_CHECKS_INCOMPLETE"
    runner.omit_measurements = False
    service.build_from_description(run_id="example", expected_revision=1)
    incomplete = coverage(source)
    incomplete["features"]["reviewed"] = 0
    with pytest.raises(CadError) as error:
        service.export_step(run_id="example", expected_revision=1, coverage=incomplete)
    assert error.value.code == "COVERAGE_INCOMPLETE"


def test_candidate_mutation_blocks_release(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    result = service.build_from_description(run_id="example", expected_revision=1)
    Path(result["build"]["candidate_path"]).write_bytes(b"changed")
    with pytest.raises(CadError) as error:
        service.export_step(run_id="example", expected_revision=1, coverage=coverage(source))
    assert error.value.code == "CANDIDATE_CHANGED"


def test_code_requires_enabled_flag_and_current_process_probe(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    with pytest.raises(CadError) as error:
        service.build_code(run_id="example", expected_revision=1, code="result = None")
    assert error.value.code == "BUILD_CODE_DISABLED"
    service.settings.allow_build_code = True
    with pytest.raises(CadError):
        service.build_code(run_id="example", expected_revision=1, code="result = None")
    service.cad_worker_probe()
    built = service.build_code(run_id="example", expected_revision=1, code="result = None")
    assert runner.calls == ["build_code", "validate"]
    assert built["build"]["feature_replay"] == "not_tested"
    assert built["build"]["agreement"]["status"] == "not_tested"


def test_budget_counts_reads_and_failed_revisions(setup_service):
    service, runner, description, source = setup_service
    service.part_create(run_id="example", description=description, sources=[source], step_budget=5)
    for _ in range(3):
        with pytest.raises(CadError):
            service.part_update(run_id="example", expected_revision=99, description=description)
    assert service.part_read(run_id="example")["call_count"] == 5
    assert service.part_read(run_id="example")["call_count"] == 6
    assert service.part_export_review(run_id="example", expected_revision=1)["status"] == "pass"
    with pytest.raises(CadError) as error:
        service.build_from_description(run_id="example", expected_revision=1)
    assert error.value.code == "STEP_BUDGET_EXHAUSTED"


def test_concurrent_updates_have_one_winner(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)

    def update():
        try:
            return service.part_update(run_id="example", expected_revision=1, description=description)["status"]
        except CadError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: update(), range(2)))
    assert sorted(results) == ["REVISION_CONFLICT", "pass"]
    assert service.part_read(run_id="example")["call_count"] == 4


def test_stored_description_tampering_is_rejected(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    path = service.storage / "runs" / "example" / "state.json"
    state = json.loads(path.read_bytes())
    state["description"]["name"] = "Changed"
    path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(CadError) as error:
        service.part_read(run_id="example")
    assert error.value.code == "STATE_INVALID"


def test_compact_tool_schema_still_enforces_full_part_contract(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    with pytest.raises(CadError) as error:
        service.add_hole(run_id="example", expected_revision=1, feature={"type": "hole", "id": "bad", "diameter": 3, "evidence_ids": ["drawing"], "unexpected": "field"})
    assert error.value.code == "PART_INVALID"
    state = service.part_read(run_id="example")
    assert state["revision"] == 1 and state["call_count"] == 3
    assert len(state["part"]["description"]["features"]) == 1


def test_missing_critical_dimension_blocks_attested_coverage(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    service.build_from_description(run_id="example", expected_revision=1)
    review = coverage(source)
    review["critical_measurement_ids"] = ["unmeasured_depth"]
    with pytest.raises(CadError) as error:
        service.export_step(run_id="example", expected_revision=1, coverage=review)
    assert error.value.code == "COVERAGE_MEASUREMENT_MISSING"


def test_rejected_build_keeps_build_and_release(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    service.build_from_description(run_id="example", expected_revision=1)
    service.export_step(run_id="example", expected_revision=1, coverage=coverage(source))
    before = service.part_read(run_id="example")["part"]
    assert before["build"] and before["release"]
    rejected = (
        (lambda: service.build_code(run_id="example", expected_revision=1, code="result = None"), "BUILD_CODE_DISABLED"),
        (lambda: service.build_from_description(run_id="example", expected_revision=1, pmi={}), "PMI_PROFILE_REQUIRED"),
    )
    for attempt, code in rejected:
        with pytest.raises(CadError) as error:
            attempt()
        assert error.value.code == code
    after = service.part_read(run_id="example")["part"]
    assert (after["build"], after["release"], after["source_review"]) == (before["build"], before["release"], before["source_review"])
    assert runner.calls.count("build") == 1 and "build_code" not in runner.calls
