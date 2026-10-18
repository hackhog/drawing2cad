"""PDF tolerance candidates retain source identity and require source review."""

import base64
from hashlib import sha256
from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from jsonschema import Draft202012Validator

from drawing2cad_mcp.config import Settings
from drawing2cad_mcp.domain_service import DomainService
from drawing2cad_mcp.domain_store import AccessContext, DomainError
from drawing2cad_mcp.part_schema import part_validate
from drawing2cad_mcp.pdf import PdfError, PdfService
from drawing2cad_mcp.server import LOCAL_CATALOG
from drawing2cad_mcp.domain_tools import DOMAIN_SCHEMAS
from test_part_schema import sample_description


def _pdf_bytes(text="20 +/- 0.2 mm"):
    writer = PdfWriter()
    page = writer.add_blank_page(width=144, height=216)
    font = writer._add_object(DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                                 NameObject("/Subtype"): NameObject("/Type1"),
                                                 NameObject("/BaseFont"): NameObject("/Helvetica")}))
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 20 120 Td ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _observation(digest, **changes):
    record = {"raw_text": "20 +/- 0.2 mm", "page": 1, "view": "front",
              "region": [0.1, 0.2, 0.5, 0.3], "source_sha256": digest,
              "confidence": 0.8}
    record.update(changes)
    return record


def test_native_pdf_candidate_can_be_bound_to_part_evidence(tmp_path):
    path = tmp_path / "part.pdf"
    path.write_bytes(_pdf_bytes())
    result = PdfService((tmp_path,), tmp_path / "out", None).read_text(path)
    found, = result["tolerance_candidates"]
    assert found["provenance"] == "native_text"
    assert found["location_precision"] == "page"
    assert found["source"]["source_sha256"] == sha256(path.read_bytes()).hexdigest()
    assert found["source"]["source_id"] == found["source"]["source_sha256"]
    assert found["source"]["region"] == [0, 0, 1, 1]
    assert found["association_required"] and found["source_review_required"]
    part = sample_description()
    part["schema_version"] = "1.3"
    part["evidence"].append({"id": "tolEvidence", "status": "explicit", "reason": "Native PDF text; review its page location.",
                             "source": found["source"]})
    part["tolerances"] = [{key: value for key, value in found.items()
                           if key in {"kind", "raw_text", "confidence", "resolution", "unit", "printed_nominal",
                                      "lower_deviation", "upper_deviation"}}
                          | {"id": "tol", "scope": "parameter", "parameter_name": "length", "evidence_ids": ["tolEvidence"]}]
    assert part_validate(part)["status"] == "pass"


def test_truncated_line_does_not_make_resolved_candidate(tmp_path):
    path = tmp_path / "part.pdf"
    path.write_bytes(_pdf_bytes())
    result = PdfService((tmp_path,), tmp_path / "out", None).read_text(path, max_chars=9)
    assert result["tolerance_candidates"] == []
    assert result["pages"][0]["tolerance_last_line_skipped_due_to_truncation"]


@pytest.mark.parametrize("change", [
    {"source_sha256": "0" * 64}, {"page": 2}, {"region": [0.5, 0.2, 0.1, 0.3]},
    {"region": [0.1, 0.2, float("nan"), 0.3]}, {"confidence": float("inf")},
    {"confidence": -0.1}, {"confidence": True}, {"unknown": 1}, {"raw_text": ""},
])
def test_observation_rejects_unbound_or_invalid_input(tmp_path, change):
    path = tmp_path / "part.pdf"
    path.write_bytes(_pdf_bytes())
    observation = _observation(sha256(path.read_bytes()).hexdigest(), **change)
    with pytest.raises(PdfError):
        PdfService((tmp_path,), tmp_path / "out", None).read_text(path, tolerance_observations=[observation])


def test_client_observation_is_distinct_from_native_text(tmp_path):
    path = tmp_path / "part.pdf"
    path.write_bytes(_pdf_bytes("Outline"))
    digest = sha256(path.read_bytes()).hexdigest()
    result = PdfService((tmp_path,), tmp_path / "out", None).read_text(
        path, tolerance_observations=[_observation(digest)])
    found, = result["tolerance_candidates"]
    assert found["provenance"] == "client_observation"
    assert found["source"]["view"] == "front"
    assert found["location_precision"] == "supplied_region"
    assert result["ocr_performed"] is False


def test_client_observation_preserves_unparsed_callout_for_review(tmp_path):
    path = tmp_path / "part.pdf"
    path.write_bytes(_pdf_bytes("Outline"))
    result = PdfService((tmp_path,), tmp_path / "out", None).read_text(
        path, tolerance_observations=[_observation(sha256(path.read_bytes()).hexdigest(),
                                                  raw_text="20 +?/-0.1")])
    found, = result["tolerance_candidates"]
    assert found["kind"] == "unclear"
    assert found["resolution"] == "review_required"
    assert found["raw_text"] == "20 +?/-0.1"


def test_tool_schemas_reject_unknown_observation_fields(tmp_path):
    path = tmp_path / "part.pdf"
    path.write_bytes(_pdf_bytes())
    observation = _observation(sha256(path.read_bytes()).hexdigest(), unknown=True)
    for schema, key in ((LOCAL_CATALOG["pdf_read_text"].input_schema, "path"),
                        (DOMAIN_SCHEMAS["pdf_read_text"], "source_id")):
        request = {key: str(path) if key == "path" else "src_" + "a" * 32,
                   "tolerance_observations": [observation]}
        assert list(Draft202012Validator(schema).iter_errors(request))


def test_domain_route_uses_uploaded_source_id_and_exact_hash(tmp_path):
    settings = Settings.model_validate({"pdf": {"allowed_roots": [str(tmp_path)], "output_root": str(tmp_path / "out")},
                                        "domain": {"enabled": True}})
    service = DomainService(settings)
    ctx = AccessContext("pdf-tolerance-owner")
    raw = _pdf_bytes()
    digest = sha256(raw).hexdigest()
    try:
        begun = service.call(ctx, "upload_begin", {"filename": "source.pdf", "size_bytes": len(raw), "sha256": digest})
        service.call(ctx, "upload_chunk", {"upload_id": begun["upload_id"], "offset": 0,
                                           "data_base64": base64.b64encode(raw).decode("ascii")})
        uploaded = service.call(ctx, "upload_complete", {"upload_id": begun["upload_id"]})
        result = service.call(ctx, "pdf_read_text", {"source_id": uploaded["source_id"]})
        found, = result["tolerance_candidates"]
        assert found["provenance"] == "native_text"
        assert found["source"]["source_id"] == uploaded["source_id"]
        assert found["source"]["source_sha256"] == digest
        assert "path" not in found["source"]
        part = sample_description()
        part["schema_version"] = "1.3"
        part["evidence"][0]["source"] = found["source"]
        part["tolerances"] = [{key: value for key, value in found.items()
                               if key in {"kind", "raw_text", "confidence", "resolution", "unit", "printed_nominal",
                                          "lower_deviation", "upper_deviation"}}
                              | {"id": "tol", "scope": "parameter", "parameter_name": "length", "evidence_ids": ["drawing"]}]
        saved = service.call(ctx, "part_create", {"run_id": "pdf_tolerance", "description": part,
                                                   "sources": [{"source_id": uploaded["source_id"],
                                                                "sha256": digest, "role": "construction"}]})
        assert saved["revision"] == 1
        observed = service.call(ctx, "pdf_read_text", {"source_id": uploaded["source_id"],
                                                       "tolerance_observations": [_observation(digest)]})
        assert any(row["provenance"] == "client_observation" for row in observed["tolerance_candidates"])
        with pytest.raises(DomainError) as error:
            service.call(ctx, "pdf_read_text", {"source_id": uploaded["source_id"],
                                                 "tolerance_observations": [_observation("0" * 64)]})
        assert error.value.code == "PDF_PREPARATION_FAILED"
    finally:
        service.close()
