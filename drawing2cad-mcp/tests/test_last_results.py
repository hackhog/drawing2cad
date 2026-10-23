"""Test diagnostic result retention without changing release acceptance."""

from copy import deepcopy
import json

import pytest

from drawing2cad_mcp import drawing_verification
from drawing2cad_mcp.domain_service import DomainService
from drawing2cad_mcp.domain_store import DomainError
from test_cad_service import coverage
from test_domain_service import CTX, OTHER, artifact_bytes, call, domain  # noqa: F401
from test_drawing_verification_service import prepare


def read(service):
    return service.call(CTX, "part_read", {"run_id": "plate"})


def test_no_validated_build_has_no_step(domain):
    service, _, _, _, runner = domain
    runner.fail_operation = "build"
    assert call(service, "build_from_description")["status"] == "fail"
    result = read(service)["last_results"]
    assert result["step"] is None and result["no_step_reason"]
    assert result["failed_phase"] is None
    assert read(service)["part"]["release"] is None
    assert service.call(CTX, "artifact_list", {"run_id": "plate"})["items"] == []


def test_failed_verification_keeps_downloadable_unreleased_results(domain):
    service, _, _, _, runner, pdf = prepare(domain)
    runner.findings = [{"rule_id": rule, "status": "fail", "severity": "major", "message": "Synthetic failure.", "feature": None}
                       for rule in ("DIM-06", "FEAT-02")]
    runner.findings += [{"rule_id": rule, "status": "pass", "severity": "major", "message": "Synthetic pass.", "feature": None}
                        for rule in drawing_verification.MANDATORY_RULES if rule not in {"DIM-06", "FEAT-02"}]
    call(service, "drawing_verify", artifact_id=pdf["artifact_id"], expected_sha256=pdf["sha256"])
    result = read(service)
    last = result["last_results"]
    assert result["part"]["release"] is None
    assert last["released"] is False and last["failed_phase"] == "drawing"
    assert last["step"]["build_revision"] == 1 and last["step"]["validation"]["status"] == "pass"
    assert last["step"]["artifact"]["role"] == "step_candidate"
    assert last["drawing"]["verification"]["status"] == "fail"
    assert {item["media_type"] for item in last["drawing"]["artifacts"]} == {"application/pdf", "image/vnd.dxf"}
    assert {item["role"] for item in last["drawing"]["verification"]["artifacts"]} == {"drawing_verification_report", "drawing_verification_preview"}
    assert "DIM-06" in last["reason"] and "FEAT-02" in last["reason"]
    artifacts = [last["step"]["artifact"], *last["drawing"]["artifacts"], *last["drawing"]["verification"]["artifacts"]]
    for artifact in artifacts:
        assert artifact["released"] is False and artifact["release_status"] == "not_released" and artifact["reason"]
        assert artifact_bytes(service, artifact)
    assert str(service.store.root) not in json.dumps(last)
    assert service.call(CTX, "drawing_read", {"run_id": "plate"})["last_results"] == last


def test_previous_valid_results_survive_failures_update_and_restart(domain):
    service, _, description, spec, runner, pdf = prepare(domain)
    runner.findings = [{"rule_id": rule, "status": "fail", "severity": "major", "message": "Retained failure.", "feature": None}
                       for rule in ("DIM-06", "FEAT-02")]
    runner.findings += [{"rule_id": rule, "status": "pass", "severity": "major", "message": "Synthetic pass.", "feature": None}
                        for rule in drawing_verification.MANDATORY_RULES if rule not in {"DIM-06", "FEAT-02"}]
    call(service, "drawing_verify", artifact_id=pdf["artifact_id"], expected_sha256=pdf["sha256"])
    before = read(service)["last_results"]

    def assert_historical_findings(last):
        verification = last["drawing"]["verification"]
        assert verification["status"] == "fail" and verification["validity"] == "stale"
        assert {item["rule_id"] for item in verification["blocking"]} >= {"DIM-06", "FEAT-02"}
        assert "stale" in last["reason"] and "earlier results" in last["reason"]
        assert "DIM-06" in last["reason"] and "FEAT-02" in last["reason"]
        artifacts = [last["step"]["artifact"], *last["drawing"]["artifacts"], *verification["artifacts"]]
        assert all(item["released"] is False and item["release_status"] == "not_released" for item in artifacts)
        assert last["released"] is False and last["failed_phase"] == "drawing"
    runner.fail_operation = "build"
    assert call(service, "build_from_description")["status"] == "fail"
    assert_historical_findings(read(service)["last_results"])
    runner.fail_operation = "drawing"
    assert call(service, "drawing_render", drawing_spec=spec)["status"] == "fail"
    assert_historical_findings(read(service)["last_results"])
    changed = deepcopy(description)
    changed["name"] = "Changed synthetic name"
    call(service, "part_update", description=changed)
    other = DomainService(service.settings)
    try:
        last = read(other)["last_results"]
        assert last["step"]["artifact"]["artifact_id"] == before["step"]["artifact"]["artifact_id"]
        assert last["step"]["build_revision"] == 1 and last["step"]["current_revision"] is False
        assert {i["artifact_id"] for i in last["drawing"]["artifacts"]} == {i["artifact_id"] for i in before["drawing"]["artifacts"]}
        assert_historical_findings(last)
        assert read(other)["part"]["release"] is None
        assert artifact_bytes(other, last["step"]["artifact"])
    finally:
        other.close()


def test_candidate_download_is_owner_scoped_and_detects_corruption(domain):
    service, _, _, _, _ = domain
    call(service, "build_from_description")
    artifact = read(service)["last_results"]["step"]["artifact"]
    with pytest.raises(DomainError):
        service.call(OTHER, "artifact_read", {"artifact_id": artifact["artifact_id"]})
    service.store._path(CTX, "artifacts", artifact["artifact_id"]).write_bytes(b"changed")
    with pytest.raises(DomainError) as error:
        artifact_bytes(service, artifact)
    assert error.value.code == "INTEGRITY_ERROR"


def test_candidate_copy_survives_worker_change_and_stays_separate_from_release(domain):
    service, source, _, _, _ = domain
    call(service, "build_from_description")
    candidate = read(service)["last_results"]["step"]["artifact"]
    release = call(service, "export_step", coverage=coverage(source))["release"]
    assert release["artifact"]["role"] == "released_step"
    assert service.call(CTX, "drawing_read", {"run_id": "plate"})["release"]["artifact"] == release["artifact"]
    assert release["artifact"]["artifact_id"] != candidate["artifact_id"]
    assert release["sha256"] == candidate["sha256"]
    assert all(item["role"] != "step_candidate" for item in release["drawing"]["artifacts"])
    cad = service._backend(CTX)[0]
    state = cad._load(cad._directory("plate"))
    cad._candidate(state["build"]["build"]).write_bytes(b"changed worker output")
    assert artifact_bytes(service, candidate)
    assert read(service)["last_results"]["step"]["artifact"]["released"] is False


@pytest.mark.parametrize("fault", ["validation", "agreement", "path"])
def test_invalid_build_never_publishes_candidate(domain, fault):
    service, _, _, _, runner = domain
    if fault == "validation":
        runner.fail_import_measurement = True
    elif fault == "agreement":
        runner.wrong_import_volume = True
    else:
        runner.path_override = service.store.root / "foreign.step"
    if fault == "path":
        with pytest.raises(DomainError):
            call(service, "build_from_description")
    else:
        assert call(service, "build_from_description")["status"] == "fail"
    assert read(service)["last_results"]["step"] is None
    assert service.call(CTX, "artifact_list", {"run_id": "plate"})["items"] == []


def test_snapshot_reads_expose_last_results_without_publishing_new_artifacts(domain):
    service, _, _, _, _ = domain
    call(service, "build_from_description")
    last = read(service)["last_results"]
    artifacts = service.call(CTX, "artifact_list", {"run_id": "plate"})
    with service._run_lock(CTX, "plate"):
        part = read(service)
        drawing = service.call(CTX, "drawing_read", {"run_id": "plate"})
    assert part["read_mode"] == drawing["read_mode"] == "snapshot_during_active_operation"
    assert part["last_results"] == drawing["last_results"] == last
    assert service.call(CTX, "artifact_list", {"run_id": "plate"}) == artifacts



def test_failed_render_records_drawing_phase_without_a_completed_drawing(domain):
    service, _, description, spec, runner = domain
    call(service, "build_from_description")
    assert read(service)["last_results"]["failed_phase"] is None
    runner.fail_operation = "drawing"
    assert call(service, "drawing_render", drawing_spec=spec)["status"] == "fail"
    last = read(service)["last_results"]
    assert last["failed_phase"] == "drawing" and last["drawing"] is None
    changed = deepcopy(description)
    changed["name"] = "Changed after failed render"
    call(service, "part_update", description=changed)
    assert read(service)["last_results"]["failed_phase"] == "drawing"


@pytest.mark.parametrize("fault", ["json", "shape", "top_array", "step_array", "drawing_array", "verification_array",
                                 "binding_array", "review_array", "ids_array", "missing", "foreign", "mismatch", "bytes"])
def test_unavailable_diagnostics_do_not_hide_a_current_release(domain, fault):
    service, source, _, _, _ = domain
    call(service, "build_from_description")
    released = call(service, "export_step", coverage=coverage(source))["release"]["artifact"]
    cad = service._backend(CTX)[0]
    directory = cad._directory("plate")
    path = directory / "last-results.json"
    record = json.loads(path.read_text())
    if fault == "json":
        path.write_text('{"private": "/secret/invalid"')
    elif fault == "shape":
        path.write_text('{"drawing": {"artifacts": ["invalid"]}}')
    elif fault.endswith("_array"):
        malformed = {"top_array": [], "step_array": {"step": []}, "drawing_array": {"drawing": []},
                     "verification_array": {"drawing": {"verification": []}},
                     "binding_array": {"drawing": {"verification": {"binding": []}}},
                     "review_array": {"drawing": {"review": []}},
                     "ids_array": {"drawing": {"verification": {"artifact_ids": [42]}}}}[fault]
        if isinstance(malformed, dict) and isinstance(malformed.get("drawing"), dict):
            malformed["drawing"].update(part_revision=1, drawing_sha256="0" * 64, artifacts=[])
        path.write_text(json.dumps(malformed))
    elif fault == "missing":
        record["step"]["artifact"]["artifact_id"] = "art_" + "0" * 32
        path.write_text(json.dumps(record))
    elif fault == "foreign":
        foreign_path = service.store.namespace_root(OTHER) / "foreign.step"
        foreign_path.parent.mkdir(parents=True, exist_ok=True)
        foreign_path.write_bytes(b"foreign candidate")
        other_artifact = service.store.artifact_register(OTHER, foreign_path,
            "step_candidate", "plate", 1, "model/step", "foreign.step")
        record["step"]["artifact"] = other_artifact
        path.write_text(json.dumps(record))
    elif fault == "mismatch":
        record["step"]["artifact"]["sha256"] = "0" * 64
        path.write_text(json.dumps(record))
    else:
        service.store._path(CTX, "artifacts", record["step"]["artifact"]["artifact_id"]).unlink()
    for tool in ("part_read", "drawing_read"):
        result = service.call(CTX, tool, {"run_id": "plate"})
        release_view = result["part"]["release"] if tool == "part_read" else result["release"]
        assert release_view["artifact"] == released
        assert release_view["released_artifact_ids"] == [released["artifact_id"]]
        last = result["last_results"]
        assert last["released"] is False and last["failed_phase"] is None
        assert last["step"] is None and last["drawing"] is None
        assert last["error"]["code"] == "RESULTS_UNAVAILABLE"
        assert last["reason"] == "Retained diagnostic results are unavailable."
        assert last["no_step_reason"] == "The retained model result is unavailable."
        assert "/secret/invalid" not in json.dumps(last)


def test_unverified_reason_has_no_agent_instruction(domain):
    service, _, _, spec, _ = domain
    call(service, "build_from_description")
    call(service, "drawing_render", drawing_spec=spec)
    reason = read(service)["last_results"]["reason"]
    assert "not been verified" in reason and "Call " not in reason


@pytest.mark.parametrize("fault", ["copy", "hash", "size"])
def test_candidate_publication_failure_does_not_fail_validated_build(domain, monkeypatch, fault):
    service, source, _, _, _ = domain
    original = service.store.artifact_register

    def registration(ctx, path, role, *args):
        if role == "step_candidate":
            if fault == "copy":
                raise OSError("/private/copy failed")
            if fault == "size":
                raise DomainError("LIMIT_EXCEEDED", "/private/candidate too large")
            return {**original(ctx, path, role, *args), "sha256": "0" * 64}
        return original(ctx, path, role, *args)

    monkeypatch.setattr(service.store, "artifact_register", registration)
    built = call(service, "build_from_description")
    assert built["status"] == "pass"
    assert built["last_results"]["error"]["code"] == "RESULTS_UNAVAILABLE"
    assert "/private" not in json.dumps(built["last_results"])
    release = call(service, "export_step", coverage=coverage(source))
    assert release["status"] == "pass" and release["release"]["artifact"]["role"] == "released_step"
    restarted = DomainService(service.settings)
    try:
        assert read(restarted)["last_results"]["error"]["code"] == "RESULTS_UNAVAILABLE"
    finally:
        restarted.close()


@pytest.mark.parametrize("operation", ["drawing_render", "drawing_verify", "drawing_review"])
def test_result_record_write_failure_does_not_fail_completed_drawing_operation(domain, monkeypatch, operation):
    from test_drawing_acceptance import passing
    service, source, _, spec, runner, pdf = prepare(domain)
    runner.findings, runner.report_status = passing(), "pass"
    if operation == "drawing_review":
        assert call(service, "drawing_verify", artifact_id=pdf["artifact_id"], expected_sha256=pdf["sha256"])["status"] == "pass"
    digest = service.call(CTX, "drawing_read", {"run_id": "plate"})["drawing"]["drawing_sha256"]

    def fail_write(*_args):
        raise OSError("/private/result write failed")

    monkeypatch.setattr(service, "_save_last_results", fail_write)
    if operation == "drawing_render":
        result = call(service, operation, drawing_spec=spec)
    elif operation == "drawing_verify":
        result = call(service, operation, artifact_id=pdf["artifact_id"], expected_sha256=pdf["sha256"])
    else:
        result = call(service, operation, drawing_sha256=digest, reviewer="Synthetic reviewer",
                      source_hashes=[source["sha256"]], decision="accepted", reason="Synthetic review.")
    assert result["status"] == "pass"
    assert result["last_results"]["error"]["code"] == "RESULTS_UNAVAILABLE"
    assert read(service)["last_results"]["step"] is None
    assert service.call(CTX, "drawing_read", {"run_id": "plate"})["last_results"]["error"]["code"] == "RESULTS_UNAVAILABLE"
    assert "/private" not in json.dumps(result["last_results"])
    assert call(service, "export_step", coverage=coverage(source))["status"] == "pass"


def test_corrupt_auxiliary_record_does_not_block_verified_pair_release(domain):
    from test_drawing_acceptance import passing, verify_and_review
    service, source, _, spec, runner, _ = prepare(domain)
    cad = service._backend(CTX)[0]
    (cad._directory("plate") / "last-results.json").write_text("[]")
    rendered = call(service, "drawing_render", drawing_spec=spec)
    assert rendered["status"] == "pass"
    pdf = next(item for item in rendered["drawing"]["artifacts"] if item["media_type"] == "application/pdf")
    assert verify_and_review(service, source, runner, pdf, passing())["status"] == "accepted"
    released = call(service, "export_step", coverage=coverage(source), delivery="complete_service")
    assert released["status"] == "pass" and released["release"]["pair_current"] is True
    assert read(service)["last_results"]["error"]["code"] == "RESULTS_UNAVAILABLE"


@pytest.mark.parametrize("failed_kind", ["build", "drawing"])
def test_auxiliary_failure_stays_latched_after_unrelated_success_and_restart(domain, monkeypatch, failed_kind):
    service, _, _, spec, _ = domain
    assert call(service, "build_from_description")["status"] == "pass"
    assert call(service, "drawing_render", drawing_spec=spec)["status"] == "pass"

    def fail_write(*_args):
        raise OSError("Synthetic unavailable disk")

    monkeypatch.setattr(service, "_save_last_results", fail_write)
    if failed_kind == "build":
        assert call(service, "build_from_description")["status"] == "pass"
    else:
        assert call(service, "drawing_render", drawing_spec=spec)["status"] == "pass"
    monkeypatch.undo()
    if failed_kind == "build":
        assert call(service, "drawing_render", drawing_spec=spec)["status"] == "pass"
    else:
        assert call(service, "build_from_description")["status"] == "pass"
    assert read(service)["last_results"]["error"]["code"] == "RESULTS_UNAVAILABLE"
    restarted = DomainService(service.settings)
    try:
        assert read(restarted)["last_results"]["error"]["code"] == "RESULTS_UNAVAILABLE"
    finally:
        restarted.close()


@pytest.mark.parametrize("operation", ["build_from_description", "drawing_render", "drawing_verify", "drawing_review"])
def test_failed_result_and_marker_writes_remain_unavailable_on_immediate_restart(domain, monkeypatch, operation):
    from test_drawing_acceptance import passing
    service, source, _, spec, runner, pdf = prepare(domain)
    runner.findings, runner.report_status = passing(), "pass"
    if operation == "drawing_review":
        assert call(service, "drawing_verify", artifact_id=pdf["artifact_id"], expected_sha256=pdf["sha256"])["status"] == "pass"
    cad = service._backend(CTX)[0]
    directory = cad._directory("plate")
    previous = (directory / "last-results.json").read_bytes()
    digest = service.call(CTX, "drawing_read", {"run_id": "plate"})["drawing"]["drawing_sha256"]

    def fail_write(*_args):
        raise OSError("Synthetic unavailable result-state file")

    monkeypatch.setattr(service, "_save_last_results", fail_write)
    if operation == "build_from_description":
        result = call(service, operation)
    elif operation == "drawing_render":
        result = call(service, operation, drawing_spec=spec)
    elif operation == "drawing_verify":
        result = call(service, operation, artifact_id=pdf["artifact_id"], expected_sha256=pdf["sha256"])
    else:
        result = call(service, operation, drawing_sha256=digest, reviewer="Synthetic reviewer",
                      source_hashes=[source["sha256"]], decision="accepted", reason="Synthetic review.")
    assert result["status"] == "pass"
    assert result["last_results"]["error"]["code"] == "RESULTS_UNAVAILABLE"
    assert (directory / "last-results.json").read_bytes() == previous
    restarted = DomainService(service.settings)
    try:
        for tool in ("part_read", "drawing_read"):
            last = restarted.call(CTX, tool, {"run_id": "plate"})["last_results"]
            assert last["step"] is None and last["drawing"] is None
            assert last["error"]["code"] == "RESULTS_UNAVAILABLE"
        assert call(restarted, "export_step", coverage=coverage(source))["status"] == "pass"
    finally:
        restarted.close()
