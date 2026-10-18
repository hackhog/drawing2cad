"""Compare description calculations with the maintained worker and MCP service."""

from copy import deepcopy

import pytest

from drawing2cad_mcp.cad_service import CadService
from test_part_schema import sample_description


def test_part_validation_returns_computed_values_without_changing_source():
    description = sample_description()
    original = deepcopy(description)
    result = CadService.part_validate(None, description)
    assert result["status"] == "pass"
    assert result["computed_expected"]["final"]["volume"]["value"] == pytest.approx(1000)
    assert description == original


def test_invalid_description_has_no_computed_values():
    description = sample_description()
    description["features"][0]["height"] = -1
    result = CadService.part_validate(None, description)
    assert result["status"] == "fail"
    assert "computed_expected" not in result


def test_source_dimensions_remain_separate_from_calculated_references():
    description = sample_description()
    description["schema_version"] = "1.4"
    description["dimensions"] = [{"id": "source_length", "printed_text": "20", "nominal": 20,
                                  "evidence_ids": ["drawing"]}]
    original = deepcopy(description)
    result = CadService.part_validate(None, description)
    assert result["status"] == "pass"
    assert "dimension_checks" in result
    assert result["computed_expected"]["final"]["bbox"]["size"] == pytest.approx([20, 10, 5])
    assert description == original


def test_worker_and_fresh_import_report_calculated_checks(tmp_path):
    pytest.importorskip("build123d")
    from drawing2cad_mcp.cad_kernel import build
    from drawing2cad_mcp.cad_validation import validate_step

    description = sample_description()
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    feature = result["feature_results"][0]
    assert all(row["status"] == "pass" for row in feature["computed_checks"])
    imported = validate_step(result["candidate_step"], description)
    assert imported["status"] == "pass"
    assert next(row for row in imported["checks"] if row["check"] == "computed_agent_bbox")["measurement_id"] == "overall"


def test_wrong_agent_volume_blocks_candidate_without_rewriting_evidence(tmp_path):
    pytest.importorskip("build123d")
    from drawing2cad_mcp.cad_kernel import build

    description = sample_description()
    description["measurements"].append({"id": "mass_volume", "kind": "volume", "expected": [999],
                                      "basis": "independent_measurement", "evidence_ids": ["drawing"]})
    original = deepcopy(description)
    result = build(description, tmp_path)
    assert result["status"] == "fail"
    assert result["candidate_step"] is None
    assert result["error"]["code"] == "COMPUTED_EXPECTED_MISMATCH"
    assert result["error"]["feature_id"] == "base"
    assert description == original


def test_wrong_kernel_feature_is_identified_before_export(tmp_path, monkeypatch):
    pytest.importorskip("build123d")
    from drawing2cad_mcp import cad_kernel

    primitive = cad_kernel._primitive

    def wrong_height(feature, part, **kwargs):
        return primitive(feature.model_copy(update={"height": 6}), part, **kwargs)

    monkeypatch.setattr(cad_kernel, "_primitive", wrong_height)
    result = cad_kernel.build(sample_description(), tmp_path)
    assert result["status"] == "fail"
    assert result["candidate_step"] is None
    assert result["error"]["feature_id"] == "base"
    assert result["feature_results"][0]["computed_checks"][0]["difference"] == pytest.approx([200])


def test_import_geometry_mismatch_fails_even_without_agent_bbox(tmp_path):
    pytest.importorskip("build123d")
    from drawing2cad_mcp.cad_kernel import build
    from drawing2cad_mcp.cad_validation import validate_step

    description = sample_description()
    description["measurements"] = []
    result = build(description, tmp_path)
    changed = deepcopy(description)
    changed["features"][0]["height"] = 6
    imported = validate_step(result["candidate_step"], changed)
    assert imported["status"] == "fail"
    assert any(row["check"] == "computed_volume" and row["status"] == "fail"
               and row["feature_id"] == "base" for row in imported["checks"])
