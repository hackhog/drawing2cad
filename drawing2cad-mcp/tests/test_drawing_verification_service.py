"""Service boundary of drawing_verify with fake verifier output; this is not verification acceptance."""

import hashlib
import json
from copy import deepcopy
from uuid import uuid4

import pytest

from drawing2cad_mcp.domain_store import DomainError
from drawing2cad_mcp.drawing_contract import description_digest
from test_domain_service import CTX, DrawingRunner, call, domain  # noqa: F401


class VerifyingRunner(DrawingRunner):
    def __init__(self, storage):
        super().__init__(storage)
        self.requests = []

    def run(self, operation, *, input_pdf=None, input_image=None, verification=None, **kwargs):
        if operation == "render_pdf_poppler":
            self.calls.append(operation)
            directory = self.storage / uuid4().hex
            directory.mkdir(parents=True)
            page = directory / "page-1.png"
            page.write_bytes(b"Synthetic service-boundary page; not a raster.")
            return {"status": "pass", "pages": [{"page": 1, "path": str(page), "bytes": page.stat().st_size}],
                    "worker": {"worker_id": directory.name, "work_dir": str(directory)}}
        if operation == "verify_drawing_pdf":
            self.calls.append(operation)
            self.requests.append({"request": verification, "pdf": hashlib.sha256(input_pdf.read_bytes()).hexdigest(),
                                  "step": kwargs.get("input_step") is not None, "image": input_image is not None})
            directory = self.storage / uuid4().hex
            directory.mkdir(parents=True)
            body = {"schema_version": "1.0", "verifier_version": "1.0.0", "status": "fail", "mode": verification["mode"],
                    "binding": verification["expected"], "untested_rules": ["STYLE-01"],
                    "findings": [{"rule_id": "VIEW-REQ-01", "status": "fail", "severity": "major", "message": "Synthetic."}],
                    "scope": "Synthetic."}
            artifacts = []
            for name, data in (("verification-report.json", json.dumps(body).encode()), ("verification-preview.png", b"synthetic")):
                path = directory / name
                path.write_bytes(data)
                artifacts.append({"name": name, "path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            return {"status": "pass", "report": body, "artifacts": artifacts,
                    "worker": {"worker_id": directory.name, "work_dir": str(directory)}}
        return super().run(operation, input_pdf=input_pdf, **kwargs)


def prepare(domain):
    service, source, description, spec, _ = domain
    cad = service._backend(CTX)[0]
    runner = VerifyingRunner(cad.runner.storage)
    cad.runner = runner
    drawing = call(service, "drawing_render", drawing_spec=spec)
    assert drawing["status"] == "pass", drawing
    assert call(service, "build_from_description")["status"] == "pass"
    pdf = next(item for item in drawing["drawing"]["artifacts"] if item["media_type"] == "application/pdf")
    return service, source, description, spec, runner, pdf


def test_verification_binds_the_current_pdf_and_stores_a_current_record(domain):
    service, _, _, _, runner, pdf = prepare(domain)
    result = call(service, "drawing_verify", artifact_id=pdf["artifact_id"], expected_sha256=pdf["sha256"])
    assert result["status"] == "fail" and result["mode"] == "bound"
    assert [item["role"] for item in result["artifacts"]] == ["drawing_verification_report", "drawing_verification_preview"]
    sent = runner.requests[-1]
    assert sent["pdf"] == pdf["sha256"] and sent["step"] and sent["image"]
    assert sent["request"]["expected"]["pdf_sha256"] == pdf["sha256"]
    assert {item["rule"] for item in sent["request"]["texts"]} >= {"DIM-01"}
    read = service.call(CTX, "drawing_read", {"run_id": "plate"})
    assert read["verification"]["validity"] == "current" and read["verification"]["status"] == "fail"


def test_changed_pdf_bytes_make_the_report_stale(domain):
    service, _, _, _, _, pdf = prepare(domain)
    call(service, "drawing_verify", artifact_id=pdf["artifact_id"], expected_sha256=pdf["sha256"])
    path = service.store._path(CTX, "artifacts", pdf["artifact_id"])
    data = bytearray(path.read_bytes())
    data[-10] ^= 0xFF
    path.write_bytes(bytes(data))
    read = service.call(CTX, "drawing_read", {"run_id": "plate"})
    assert read["verification"]["validity"] == "stale" and "pdf_sha256" in read["verification"]["reason"]
    with pytest.raises(DomainError) as error:
        call(service, "drawing_verify", artifact_id=pdf["artifact_id"], expected_sha256=pdf["sha256"])
    assert error.value.code == "INTEGRITY_ERROR"


def test_a_part_change_removes_the_drawing_and_its_report(domain):
    service, _, description, _, _, pdf = prepare(domain)
    call(service, "drawing_verify", artifact_id=pdf["artifact_id"], expected_sha256=pdf["sha256"])
    changed = deepcopy(description)
    changed["parameters"][0]["value"] = 70
    changed["measurements"][0]["expected"] = [70, 30, 10]
    assert call(service, "part_update", description=changed)["revision"] == 2
    read = service.call(CTX, "drawing_read", {"run_id": "plate"})
    assert read["drawing"] is None and read["verification"] is None


def test_rejects_wrong_hashes_other_artifacts_and_ambiguous_targets(domain):
    service, source, _, _, runner, pdf = prepare(domain)
    with pytest.raises(DomainError) as error:
        call(service, "drawing_verify", artifact_id=pdf["artifact_id"], expected_sha256="0" * 64)
    assert error.value.code == "ARTIFACT_HASH_MISMATCH"
    dxf = next(item for item in service.call(CTX, "drawing_read", {"run_id": "plate"})["drawing"]["artifacts"]
               if item["media_type"] == "image/vnd.dxf")
    with pytest.raises(DomainError) as error:
        call(service, "drawing_verify", artifact_id=dxf["artifact_id"], expected_sha256=dxf["sha256"])
    assert error.value.code == "STALE_DRAWING"
    with pytest.raises(DomainError) as error:
        call(service, "drawing_verify", artifact_id=pdf["artifact_id"], source_id=source["source_id"], expected_sha256=pdf["sha256"])
    assert error.value.code == "INVALID_ARGUMENT"
    assert "verify_drawing_pdf" not in runner.calls


def test_a_source_pdf_is_verified_without_a_binding(domain):
    service, source, _, _, runner, _ = prepare(domain)
    result = call(service, "drawing_verify", source_id=source["source_id"], expected_sha256=source["sha256"])
    assert result["mode"] == "unbound"
    sent = runner.requests[-1]
    assert sent["request"]["mode"] == "unbound" and not sent["step"] and sent["request"]["views"] == []
    assert service.call(CTX, "drawing_read", {"run_id": "plate"})["verification"] is None


def test_a_new_build_makes_the_report_stale():
    from drawing2cad_mcp.drawing_verification import status

    binding = {"part_revision": 1, "description_sha256": "a" * 64, "candidate_sha256": "b" * 64, "drawing_sha256": "c" * 64,
               "pdf_sha256": "d" * 64}
    stored = {"status": "pass", "binding": binding}
    assert status(stored, binding)["validity"] == "current"
    result = status(stored, {**binding, "candidate_sha256": "e" * 64})
    assert result["validity"] == "stale" and "candidate_sha256" in result["reason"]
