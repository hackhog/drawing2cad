"""Acceptance gate of complete-service drawings: review plus a current, passed PDF verification. Fake verifier output."""

import pytest

from drawing2cad_mcp.domain_store import DomainError
from drawing2cad_mcp.drawing_verification import gate
from drawing2cad_mcp.pdf_verifier import MANDATORY_RULES
from test_domain_service import CTX, call, domain  # noqa: F401
from test_drawing_verification_service import prepare


def passing(*extra):
    """A report in which each mandatory rule passes, plus extra findings."""
    findings = [{"rule_id": rule, "status": "pass", "severity": "info", "message": "Synthetic pass.", "feature": None}
                for rule in MANDATORY_RULES]
    return findings + list(extra)


def verify_and_review(service, source, runner, pdf, findings, status="pass", decisions=None):
    runner.findings, runner.report_status = findings, status
    call(service, "drawing_verify", artifact_id=pdf["artifact_id"], expected_sha256=pdf["sha256"])
    digest = service.call(CTX, "drawing_read", {"run_id": "plate"})["drawing"]["drawing_sha256"]
    arguments = {"drawing_sha256": digest, "reviewer": "Synthetic reviewer", "reason": "Synthetic acceptance-gate test.",
                 "source_hashes": [source["sha256"]], "decision": "accepted"}
    if decisions is not None:
        arguments["verification_decisions"] = decisions
    call(service, "drawing_review", **arguments)
    return call(service, "export_step", coverage=coverage(source))["release"]["drawing"]


def coverage(source):
    from test_domain_service import coverage as base
    return base(source)


def test_a_passed_verification_and_an_accepted_review_accept_the_drawing(domain):
    service, source, _, _, runner, pdf = prepare(domain)
    drawing = verify_and_review(service, source, runner, pdf, passing())
    assert drawing["status"] == "accepted", drawing.get("reason")
    assert drawing["verification"]["gate"]["passed"] and drawing["verification"]["validity"] == "current"


@pytest.mark.parametrize("status", ["fail", "not_tested"])
def test_a_failed_or_untested_mandatory_rule_blocks(domain, status):
    service, source, _, _, runner, pdf = prepare(domain)
    findings = [item if item["rule_id"] != "MODEL-01" else {**item, "status": status} for item in passing()]
    drawing = verify_and_review(service, source, runner, pdf, findings, status="fail" if status == "fail" else "pass")
    assert drawing["status"] == "unverified"
    assert [item["rule_id"] for item in drawing["verification"]["gate"]["blocking"]] == ["MODEL-01"]


def test_needs_review_blocks_until_the_identified_review_decides_it(domain):
    service, source, _, _, runner, pdf = prepare(domain)
    review_item = {"rule_id": "GPS-01", "status": "needs_review", "severity": "minor", "message": "Outside the profile.", "feature": "profile"}
    blocked = verify_and_review(service, source, runner, pdf, passing(review_item), status="needs_review")
    assert blocked["status"] == "unverified"
    accepted = verify_and_review(service, source, runner, pdf, passing(review_item), status="needs_review",
                                 decisions=[{"rule_id": "GPS-01", "feature": "profile", "reason": "The customer standard applies."}])
    assert accepted["status"] == "accepted", accepted.get("reason")
    assert [item["rule_id"] for item in accepted["verification"]["gate"]["reviewed"]] == ["GPS-01"]


def test_a_decision_must_name_an_open_review_finding(domain):
    service, source, _, _, runner, pdf = prepare(domain)
    with pytest.raises(DomainError) as error:
        verify_and_review(service, source, runner, pdf, passing(),
                          decisions=[{"rule_id": "MODEL-01", "feature": None, "reason": "Not possible for a pass or a fail."}])
    assert error.value.code == "REVIEW_DECISION_INVALID"


def test_a_change_after_the_verification_or_the_review_invalidates_the_acceptance(domain):
    service, source, _, spec, runner, pdf = prepare(domain)
    assert verify_and_review(service, source, runner, pdf, passing())["status"] == "accepted"
    path = service.store._path(CTX, "artifacts", pdf["artifact_id"])
    data = bytearray(path.read_bytes())
    data[-10] ^= 0xFF
    path.write_bytes(bytes(data))
    stale = service.call(CTX, "part_read", {"run_id": "plate"})["part"]["release"]
    assert stale["drawing_current"] is False


def test_a_new_verification_needs_a_new_review(domain):
    service, source, _, _, runner, pdf = prepare(domain)
    assert verify_and_review(service, source, runner, pdf, passing())["status"] == "accepted"
    # A new report with other content has another hash. The earlier review does not cover it.
    runner.findings = passing({"rule_id": "TEXT-03", "status": "pass", "severity": "info", "message": "Another note.", "feature": "note_1"})
    call(service, "drawing_verify", artifact_id=pdf["artifact_id"], expected_sha256=pdf["sha256"])
    drawing = call(service, "export_step", coverage=coverage(source))["release"]["drawing"]
    assert drawing["status"] == "unverified" and "review" in drawing["reason"]


def test_the_gate_needs_a_current_verification_of_the_profile():
    findings = [{"rule_id": "GPS-03", "status": "not_applicable", "message": "No frame is outside the profile.", "feature": None}]
    base = {"validity": "current", "profile": "drawing2cad-verify-1", "findings": findings, "covered_rules": list(MANDATORY_RULES)}
    assert gate(base, [])["passed"]
    assert not gate(None, [])["passed"]
    assert not gate({**base, "validity": "stale", "reason": "pdf_sha256"}, [])["passed"]
    assert not gate({**base, "profile": "drawing2cad-verify-0"}, [])["passed"]
    assert not gate({**base, "findings": [{**findings[0], "message": ""}]}, [])["passed"]


def test_a_failed_report_blocks_also_without_a_mandatory_failure():
    base = {"validity": "current", "profile": "drawing2cad-verify-1", "findings": [], "status": "fail", "covered_rules": list(MANDATORY_RULES)}
    result = gate(base, [])
    assert not result["passed"] and result["blocking"][0]["rule_id"] == "REPORT"
    assert "TEXT-LIMIT" in MANDATORY_RULES


def test_a_missing_candidate_makes_the_verification_stale_without_an_error(domain):
    service, source, _, _, runner, pdf = prepare(domain)
    assert verify_and_review(service, source, runner, pdf, passing())["status"] == "accepted"
    cad = service._backend(CTX)[0]
    built = cad._load(cad._directory("plate"))["build"]
    cad._candidate(built["build"]).unlink()
    read = service.call(CTX, "drawing_read", {"run_id": "plate"})
    assert read["verification"]["validity"] == "stale" and read["acceptance"]["status"] == "unverified"
    assert service.call(CTX, "part_read", {"run_id": "plate"})["part"]["release"]["drawing_current"] is False


def test_repeated_reads_reuse_the_verified_file_hashes(domain, monkeypatch, tmp_path):
    import hashlib

    service = domain[0]
    path = tmp_path / "file.pdf"
    path.write_bytes(b"synthetic content")
    digest = hashlib.sha256(b"synthetic content").hexdigest()
    assert service._file_has(path, digest)

    def no_hash(*args, **kwargs):
        raise AssertionError("The file was hashed again.")
    monkeypatch.setattr("drawing2cad_mcp.domain_service.hashlib.sha256", no_hash)
    assert service._file_has(path, digest)
    monkeypatch.undo()
    # A changed file has another size or ctime, so the service hashes it again.
    path.write_bytes(b"changed content!!")
    assert not service._file_has(path, digest)


def test_a_report_without_a_mandatory_rule_does_not_pass():
    base = {"validity": "current", "profile": "drawing2cad-verify-1", "findings": [], "status": "pass",
            "covered_rules": [rule for rule in MANDATORY_RULES if rule != "UNITS-01"]}
    result = gate(base, [])
    assert not result["passed"] and [item["rule_id"] for item in result["blocking"]] == ["UNITS-01"]


def test_a_record_of_a_changed_input_is_never_current():
    from drawing2cad_mcp.drawing_verification import status

    binding = {"pdf_sha256": "a" * 64, "candidate_sha256": "changed"}
    assert status({"binding": binding}, dict(binding))["validity"] == "stale"


def test_an_input_change_during_the_verification_gives_no_record(domain):
    service, source, _, _, runner, pdf = prepare(domain)
    runner.findings = passing()
    cad = service._backend(CTX)[0]
    built = cad._load(cad._directory("plate"))["build"]
    candidate = cad._candidate(built["build"])
    runner.during = lambda: candidate.write_bytes(candidate.read_bytes() + b"changed")
    with pytest.raises(DomainError) as error:
        call(service, "drawing_verify", artifact_id=pdf["artifact_id"], expected_sha256=pdf["sha256"])
    assert error.value.code == "VERIFICATION_INPUT_CHANGED"
    assert service.call(CTX, "drawing_read", {"run_id": "plate"})["verification"] is None


def test_a_new_report_makes_the_recorded_release_drawing_outdated(domain):
    service, source, _, _, runner, pdf = prepare(domain)
    blocked = [item if item["rule_id"] != "MODEL-01" else {**item, "status": "fail"} for item in passing()]
    assert verify_and_review(service, source, runner, pdf, blocked, status="fail")["status"] == "unverified"
    runner.findings = [item if item["rule_id"] != "DIM-01" else {**item, "status": "fail"} for item in passing()]
    call(service, "drawing_verify", artifact_id=pdf["artifact_id"], expected_sha256=pdf["sha256"])
    assert service.call(CTX, "part_read", {"run_id": "plate"})["part"]["release"]["drawing_current"] is False


def test_dim_03_is_not_applicable_without_round_features():
    from drawing2cad_mcp.pdf_verifier import Report, check_round_dimensions

    report = Report()
    view = {"id": "front", "kind": "orthographic", "dimensions": [], "scale": 1.0}
    model = {"geometry": [{"type": "line", "style": "visible", "start": [0, 0], "end": [10, 0], "id": "l"}]}
    check_round_dimensions(report, [view], {"front": model}, set())
    assert [(item["rule_id"], item["status"]) for item in report.findings] == [("DIM-03", "not_applicable")]


def test_dim_03_accepts_a_round_feature_that_feat_02_sized():
    from drawing2cad_mcp.pdf_verifier import Report, check_round_dimensions

    view = {"id": "top", "kind": "orthographic", "dimensions": [], "scale": 1.0, "frame": [0, 0, 20, 20]}
    model = {"geometry": [{"type": "circle", "style": "visible", "center": [0, 0], "radius": 3.0, "id": "c"}]}
    for sized, status in ((set(), "fail"), ({3.0}, "pass")):
        report = Report()
        check_round_dimensions(report, [view], {"top": model}, sized)
        assert [item["status"] for item in report.findings if item["rule_id"] == "DIM-03"] == [status]
