"""Complete-service release: STEP and drawing PDF only as a pair verified against each other. Fake verifier output."""

from copy import deepcopy

import pytest

from drawing2cad_mcp.domain_store import DomainError
from test_domain_service import CTX, call, coverage, domain  # noqa: F401
from test_drawing_acceptance import passing, verify_and_review
from test_drawing_verification_service import prepare


def accepted(domain):
    service, source, description, spec, runner, pdf = prepare(domain)
    drawing = verify_and_review(service, source, runner, pdf, passing())
    assert drawing["status"] == "accepted", drawing.get("reason")
    return service, source, description, runner, pdf


def release(service, source, delivery="complete_service"):
    return call(service, "export_step", coverage=coverage(source), delivery=delivery)["release"]


def corrupt(service, artifact_id):
    path = service.store._path(CTX, "artifacts", artifact_id)
    data = bytearray(path.read_bytes())
    data[-5] ^= 0xFF
    path.write_bytes(bytes(data))


def test_a_complete_service_release_records_one_verified_pair(domain):
    service, source, _, _, pdf = accepted(domain)
    released = release(service, source)
    pair = released["pair"]
    assert released["delivery"] == "complete_service"
    assert pair["step_sha256"] == released["sha256"] == released["artifact"]["sha256"]
    assert pair["pdf_sha256"] == pdf["sha256"] and pair["report_sha256"] and pair["profile"] == "drawing2cad-verify-1"
    view = service.call(CTX, "part_read", {"run_id": "plate"})["part"]["release"]
    assert view["pair_current"] is True and view["pair_reason"] is None


def test_a_drawing_that_is_not_accepted_cannot_be_released_as_a_pair(domain):
    service, source, _, _, _, _ = prepare(domain)
    with pytest.raises(DomainError) as error:
        release(service, source)
    assert error.value.code == "RELEASE_PAIR_REQUIRED"
    # The STEP-only release keeps its policy and records no pair.
    step_only = release(service, source, "step_only")
    assert step_only["delivery"] == "step_only" and step_only["pair"] is None


def test_a_pair_from_different_revisions_fails(domain):
    service, source, description, _, _ = accepted(domain)
    changed = deepcopy(description)
    changed["parameters"][0]["value"] = 70
    changed["measurements"][0]["expected"] = [70, 30, 10]
    assert call(service, "part_update", description=changed)["revision"] == 2
    assert service.call(CTX, "build_from_description", {"run_id": "plate", "expected_revision": 2})["status"] == "pass"
    with pytest.raises(DomainError) as error:
        service.call(CTX, "export_step", {"run_id": "plate", "expected_revision": 2, "coverage": coverage(source),
                                          "delivery": "complete_service"})
    assert error.value.code == "RELEASE_PAIR_REQUIRED"


def test_a_pair_from_another_build_of_the_same_revision_fails(domain):
    service, source, _, _, _ = accepted(domain)
    cad = service._backend(CTX)[0]
    candidate = cad._candidate(cad._load(cad._directory("plate"))["build"]["build"])
    # A new build of the same revision gives other candidate bytes. The verification belongs to the earlier bytes.
    candidate.write_bytes(candidate.read_bytes() + b"\nsynthetic other build")
    with pytest.raises(DomainError) as error:
        release(service, source)
    assert error.value.code == "RELEASE_PAIR_REQUIRED"


@pytest.mark.parametrize("target", ["step", "pdf"])
def test_a_changed_file_after_the_release_makes_the_delivery_stale(domain, target):
    service, source, _, _, pdf = accepted(domain)
    released = release(service, source)
    corrupt(service, released["artifact"]["artifact_id"] if target == "step" else pdf["artifact_id"])
    view = service.call(CTX, "part_read", {"run_id": "plate"})["part"]["release"]
    assert view["pair_current"] is False and ("STEP" if target == "step" else "PDF") in view["pair_reason"]


def test_a_new_review_after_the_release_makes_the_pair_not_current(domain):
    service, source, _, _, _ = accepted(domain)
    released = release(service, source)
    assert released["pair_current"] is True
    digest = service.call(CTX, "drawing_read", {"run_id": "plate"})["drawing"]["drawing_sha256"]
    call(service, "drawing_review", drawing_sha256=digest, reviewer="Another reviewer", reason="Synthetic second review.",
         source_hashes=[source["sha256"]], decision="accepted")
    view = service.call(CTX, "part_read", {"run_id": "plate"})["part"]["release"]
    assert view["pair_current"] is False


def test_a_pdf_change_during_the_release_fails(domain, monkeypatch):
    service, source, _, _, pdf = accepted(domain)
    cad = service._backend(CTX)[0]
    original = cad.call

    def export_then_change(name, arguments):
        result = original(name, arguments)
        corrupt(service, pdf["artifact_id"])
        return result
    monkeypatch.setattr(cad, "call", export_then_change)
    with pytest.raises(DomainError) as error:
        release(service, source)
    assert error.value.code == "RELEASE_PAIR_REQUIRED"
