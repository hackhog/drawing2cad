"""Tolerance source bindings use registered PDF bytes and page coordinates."""

from copy import deepcopy
import hashlib

import pytest
from pypdf import PdfWriter

from drawing2cad_mcp.cad_service import CadError
from test_cad_service import setup_service


def _tolerance_setup(setup_service):
    service, runner, description, source = setup_service
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with open(source["path"], "wb") as stream:
        writer.write(stream)
    digest = hashlib.sha256(open(source["path"], "rb").read()).hexdigest()
    source["sha256"] = digest
    description["schema_version"] = "1.3"
    description["evidence"][0]["source"].update(source_sha256=digest, coordinate_system="normalized_displayed",
                                                  region=[0.1, 0.1, 0.2, 0.2])
    description["tolerances"] = [{"id": "length_tol", "kind": "deviation", "raw_text": "20 +0.2/-0.1",
                                  "evidence_ids": ["drawing"], "confidence": 0.9,
                                  "resolution": "resolved", "scope": "parameter", "parameter_name": "length",
                                  "unit": "mm", "printed_nominal": 20,
                                  "lower_deviation": -0.1, "upper_deviation": 0.2}]
    return service, description, source


def test_tolerance_requires_existing_construction_pdf_page(setup_service):
    service, description, source = _tolerance_setup(setup_service)
    service.part_create(run_id="valid", description=description, sources=[source])
    page = deepcopy(description)
    page["evidence"][0]["source"]["page"] = 2
    with pytest.raises(CadError) as error:
        service.part_create(run_id="missingpage", description=page, sources=[source])
    assert error.value.code == "TOLERANCE_PAGE_MISSING"


def test_tolerance_rejects_source_hash_role_and_unbounded_region(setup_service):
    service, description, source = _tolerance_setup(setup_service)
    wrong_hash = deepcopy(description)
    wrong_hash["evidence"][0]["source"]["source_sha256"] = "0" * 64
    with pytest.raises(CadError) as error:
        service.part_create(run_id="wronghash", description=wrong_hash, sources=[source])
    assert error.value.code == "EVIDENCE_SOURCE_MISMATCH"

    wrong_region = deepcopy(description)
    wrong_region["evidence"][0]["source"]["coordinate_system"] = "pdf_points"
    with pytest.raises(CadError) as error:
        service.part_create(run_id="wrongregion", description=wrong_region, sources=[source])
    assert error.value.code == "TOLERANCE_REGION_REQUIRED"

    verification_pdf = source["path"].replace("part.pdf", "verification.pdf")
    with open(source["path"], "rb") as source_stream, open(verification_pdf, "wb") as output:
        output.write(source_stream.read() + b"\n% verification copy")
    verify_digest = hashlib.sha256(open(verification_pdf, "rb").read()).hexdigest()
    verification = {"path": verification_pdf, "sha256": verify_digest, "role": "verification", "source_id": "verify"}
    wrong_role = deepcopy(description)
    wrong_role["evidence"].append({"id": "verify_ev", "status": "explicit", "reason": "Verification only.",
                                   "source": {"source_id": "verify", "source_sha256": verify_digest,
                                              "page": 1, "view": "front", "coordinate_system": "normalized_displayed",
                                              "region": [0.1, 0.1, 0.2, 0.2]}})
    wrong_role["tolerances"][0]["evidence_ids"] = ["verify_ev"]
    with pytest.raises(CadError) as error:
        service.part_create(run_id="wrongrole", description=wrong_role, sources=[source, verification])
    assert error.value.code == "VERIFICATION_SOURCE_USED_FOR_CONSTRUCTION"
