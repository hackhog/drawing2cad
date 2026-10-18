"""Synthetic feature tests for the maintained build123d adapter."""

from copy import deepcopy

import pytest

pytest.importorskip("build123d")

from drawing2cad_mcp.cad_kernel import CadBuildError, build
from drawing2cad_mcp.cad_validation import validate_step
from test_part_schema import sample_description


def test_box_candidate_and_reimport(tmp_path):
    description = sample_description()
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    assert result["measured"]["volume_mm3"] == pytest.approx(1000)
    assert result["step"]["products"] == ["Synthetic plate"]
    assert "AUTOMOTIVE_DESIGN" in result["step"]["schemas"][0]
    imported = validate_step(result["candidate_step"], description)
    assert imported["status"] == "pass"
    assert next(item for item in imported["checks"] if item["check"] == "semantic_pmi")["status"] == "not_tested"


@pytest.mark.parametrize("style,extra", [
    ("plain", {}),
    ("counterbore", {"counter_diameter": 6, "counter_depth": 2}),
    ("countersink", {"counter_diameter": 6, "angle": 90}),
])
def test_holes_are_measured_after_import(tmp_path, style, extra):
    description = sample_description()
    description["features"].append({"id": "hole1", "type": "hole", "position": [5, 5, 5], "diameter": 3, "style": style, "evidence_ids": ["drawing"], **extra})
    description["measurements"].append({"id": "hole_diameter", "kind": "hole", "expected": [3], "position": [5, 5, 5], "axis": "Z", "evidence_ids": ["drawing"], "basis": "printed_dimension"})
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    imported = validate_step(result["candidate_step"], description)
    assert imported["status"] == "pass"
    assert any(hole["diameter"] == pytest.approx(3) for hole in imported["measured"]["holes"])


def test_blind_thread_tap_drill(tmp_path):
    description = sample_description()
    description["features"].append({"id": "tap", "type": "hole", "position": [5, 5, 5], "diameter": 3.3, "extent": "blind", "depth": 3, "thread": {"designation": "M4", "pitch": 0.7}, "evidence_ids": ["drawing"]})
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    assert result["measured"]["volume_mm3"] == pytest.approx(1000 - 3.141592653589793 * 1.65**2 * 3)


def test_polygon_pocket_and_additive_cylinder(tmp_path):
    description = sample_description()
    description["measurements"] = []
    description["features"] = [
        {"id": "base", "type": "extrusion", "operation": "base", "points": [[0, 0], [20, 0], [20, 10], [0, 10]], "height": 5, "evidence_ids": ["drawing"]},
        {"id": "boss", "type": "cylinder", "operation": "add", "diameter": 4, "height": 3, "origin": [10, 5, 5], "evidence_ids": ["drawing"]},
        {"id": "pocket", "type": "pocket", "profile": {"shape": "box", "length": 3, "width": 3, "depth": 2}, "origin": [2, 2, 3], "evidence_ids": ["drawing"]},
    ]
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    assert len(result["feature_results"]) == 3
    assert result["measured"]["bbox_size"] == pytest.approx([20, 10, 8])


@pytest.mark.parametrize("kind", ["chamfer", "fillet"])
def test_geometric_edge_selector(tmp_path, kind):
    description = sample_description()
    description["features"].append({"id": "edge_finish", "type": kind, "size": 0.5, "selector": {"geometry": "line", "center_min": [0, 0, 5], "center_max": [20, 10, 5], "expected_count": 4}, "evidence_ids": ["drawing"]})
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    assert result["measured"]["volume_mm3"] < 1000


@pytest.mark.parametrize("feature,code", [
    ({"id": "miss", "type": "hole", "position": [30, 30, 5], "diameter": 2}, "HOLE_ENTRY"),
    ({"id": "above", "type": "hole", "position": [5, 5, 6], "diameter": 2, "extent": "blind", "depth": 3}, "HOLE_ENTRY"),
    ({"id": "inside", "type": "hole", "position": [5, 5, 3], "diameter": 2}, "HOLE_ENTRY"),
    ({"id": "breakthrough", "type": "hole", "position": [5, 5, 5], "diameter": 2, "extent": "blind", "depth": 6}, "BLIND_HOLE_BREAKTHROUGH"),
    ({"id": "separate", "type": "box", "operation": "add", "length": 1, "width": 1, "height": 1, "origin": [30, 0, 0]}, "INVALID_SOLID"),
    ({"id": "finish", "type": "fillet", "size": 1, "selector": {"center_min": [0, 0, 5], "center_max": [20, 10, 5], "expected_count": 1}}, "EDGE_SELECTION"),
])
def test_no_effect_disjoint_and_ambiguous_features_fail(tmp_path, feature, code):
    description = sample_description()
    description["features"].append({**deepcopy(feature), "evidence_ids": ["drawing"]})
    with pytest.raises(CadBuildError) as error:
        build(description, tmp_path)
    assert error.value.code == code
    assert error.value.feature_id == feature["id"]
    assert error.value.checks == [
        {"check": "feature_execution", "feature_id": "base", "status": "pass"},
        {"check": "feature_execution", "feature_id": feature["id"], "status": "fail"},
    ]
