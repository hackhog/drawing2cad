"""Tolerance records preserve source notation and reject unsupported claims."""

from copy import deepcopy

import pytest

from drawing2cad_mcp.part_schema import parse_description, part_validate
from drawing2cad_mcp.tolerances import candidate, parse_tolerance
from test_part_schema import sample_description


def _part():
    part = sample_description()
    part["schema_version"] = "1.3"
    part["tolerances"] = [{"id": "tol", "kind": "deviation", "raw_text": "20 +0.2 +0.1 mm",
                           "evidence_ids": ["drawing"], "confidence": 0.8, "resolution": "resolved",
                           "scope": "parameter", "parameter_name": "length", "unit": "mm",
                           "printed_nominal": 20.0, "lower_deviation": 0.1, "upper_deviation": 0.2}]
    return part


def test_deviation_allows_same_sign_bounds_and_legacy_dump_stays_stable():
    part = _part()
    assert part_validate(part)["status"] == "pass"
    legacy = sample_description()
    assert "tolerances" not in parse_description(legacy).model_dump()
    assert "tolerances" in parse_description(part).model_dump()


@pytest.mark.parametrize("change,code", [
    (lambda d: d.update(schema_version="1.2"), "schema_version"),
    (lambda d: d["tolerances"][0].update(upper_deviation=0.0), "schema"),
    (lambda d: d["tolerances"][0].update(unit="deg"), "parameter_unit"),
    (lambda d: d["tolerances"][0].update(evidence_ids=["missing"]), "unknown_evidence"),
    (lambda d: d["tolerances"][0].update(parameter_name="missing"), "unknown_parameter"),
    (lambda d: d["tolerances"][0].update(confidence=float("nan")), "schema"),
    (lambda d: d["tolerances"][0].update(confidence=1.1), "schema"),
    (lambda d: d["tolerances"][0].update(extra=1), "schema"),
])
def test_bad_tolerance_rejected(change, code):
    part = _part()
    change(part)
    assert code in {defect["code"] for defect in part_validate(part)["defects"]}


def test_limits_fit_general_and_unclear_review():
    part = _part()
    base = part["tolerances"][0]
    part["tolerances"] = [
        {key: value for key, value in base.items() if key not in {"lower_deviation", "upper_deviation", "parameter_name", "printed_nominal"}}
        | {"id": "limits", "kind": "limits", "scope": "part", "lower_limit": 19.9, "upper_limit": 20.1},
        {key: value for key, value in base.items() if key not in {"lower_deviation", "upper_deviation", "parameter_name", "printed_nominal", "unit"}}
        | {"id": "fit", "kind": "fit", "scope": "part", "raw_text": "H7", "designation": "H7"},
        {key: value for key, value in base.items() if key not in {"lower_deviation", "upper_deviation", "parameter_name", "printed_nominal", "unit"}}
        | {"id": "general", "kind": "general", "scope": "part", "raw_text": "ISO 2768-m", "designation": "ISO 2768-m"},
        {key: value for key, value in base.items() if key not in {"lower_deviation", "upper_deviation", "parameter_name", "printed_nominal", "unit"}}
        | {"id": "unclear", "kind": "unclear", "scope": "unassigned", "raw_text": "20 +/- ?", "reason": "Unreadable value.", "resolution": "review_required"},
    ]
    assert "missing_review_flag" in {item["code"] for item in part_validate(part)["defects"]}
    part["review_flags"] = [{"id": "reviewTol", "target_id": "unclear", "status": "open",
                             "reason": "Read the source detail.", "evidence_ids": ["drawing"]}]
    assert part_validate(part)["status"] == "pass"


@pytest.mark.parametrize("raw,unit,hint,kind", [
    ("20 ±0.2 mm", None, None, "deviation"),
    ("20 +/- 0.2", "mm", None, "deviation"),
    ("20 +0.2 +0.1 mm", None, None, "deviation"),
    ("20 +0,2/-0,1 mm", None, None, "deviation"),
    ("LIMITS 19.9..20.1 mm", None, None, "limits"),
    ("19.9..20.1", "mm", "limits", "limits"),
    ("20.1\n19.9", "mm", "limits", "limits"),
    ("H7", None, None, "fit"),
    ("M6", None, None, None),
    ("ABC12", None, None, None),
    ("ISO 2768-m", None, None, "general"),
    ("19.9/20.1", "mm", None, None),
])
def test_literal_parser(raw, unit, hint, kind):
    parsed = parse_tolerance(raw, unit=unit, notation_hint=hint)
    assert (None if parsed is None else parsed["kind"]) == kind


def test_candidate_preserves_location_and_missing_unit_needs_review():
    source = {"source_id": "test-source", "source_sha256": "a" * 64,
              "page": 2, "view": "detail", "region": [0.2, 0.3, 0.4, 0.5],
              "coordinate_system": "normalized_displayed"}
    parsed = candidate("20 ±0.2", source=deepcopy(source), provenance="client_observation", confidence=0.7)
    assert parsed["source"] == source
    assert parsed["resolution"] == "review_required"
    assert parsed["provenance"] == "client_observation"


def test_candidate_can_be_saved_with_source_evidence_and_review_flag():
    part = _part()
    source = {"source_id": "test-source", "source_sha256": "a" * 64,
              "page": 1, "view": "detail", "region": [0.2, 0.3, 0.4, 0.5],
              "coordinate_system": "normalized_displayed"}
    found = candidate("20 ±0.2 mm", source=source, provenance="client_observation", confidence=0.7)
    part["evidence"].append({"id": "tolEvidence", "status": "explicit", "reason": "Source transcription.",
                             "source": found["source"]})
    part["tolerances"] = [{key: value for key, value in found.items() if key not in {"source", "provenance"}}
                          | {"id": "tol", "evidence_ids": ["tolEvidence"], "scope": "parameter",
                             "parameter_name": "length"}]
    assert part_validate(part)["status"] == "pass"
    saved = parse_description(part).model_dump()
    assert saved["tolerances"][0]["lower_deviation"] == -0.2
    assert saved["evidence"][1]["source"]["region"] == (0.2, 0.3, 0.4, 0.5)
