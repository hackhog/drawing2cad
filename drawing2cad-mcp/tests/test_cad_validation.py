"""Independent expectations must detect geometric deviations after import."""

from copy import deepcopy

import pytest

pytest.importorskip("build123d")

from drawing2cad_mcp.cad_kernel import build
from drawing2cad_mcp.cad_validation import step_metadata, validate_step
from test_part_schema import sample_description


def test_drawing_expected_value_detects_wrong_build(tmp_path):
    description = sample_description()
    result = build(description, tmp_path)
    wrong = deepcopy(description)
    wrong["measurements"][0]["expected"] = [21, 10, 5]
    validated = validate_step(result["candidate_step"], wrong)
    assert validated["status"] == "fail"
    assert next(item for item in validated["checks"] if item["check"] == "overall")["status"] == "fail"


def test_missing_measurements_are_not_tested(tmp_path):
    description = sample_description()
    description["measurements"] = []
    result = build(description, tmp_path)
    assert next(item for item in result["checks"] if item["check"] == "drawing_measurements")["status"] == "not_tested"


def test_hole_location_and_outer_cylinder_do_not_pass(tmp_path):
    description = sample_description()
    description["features"] = [{"id": "base", "type": "cylinder", "operation": "base", "diameter": 10, "height": 5, "evidence_ids": ["drawing"]}]
    description["measurements"] = []
    result = build(description, tmp_path)
    description["measurements"] = [{"id": "not_a_hole", "kind": "hole", "expected": [10], "position": [0, 0, 5], "axis": "Z", "basis": "printed_dimension", "evidence_ids": ["drawing"]}]
    validated = validate_step(result["candidate_step"], description)
    assert validated["status"] == "fail"
    assert validated["measured"]["holes"] == []


def test_product_identity_is_checked(tmp_path):
    description = sample_description()
    result = build(description, tmp_path)
    metadata = step_metadata(__import__("pathlib").Path(result["candidate_step"]), "Another part")
    assert next(item for item in metadata["checks"] if item["check"] == "step_product_name")["status"] == "fail"


def test_independent_hole_axial_length_detects_wrong_depth(tmp_path):
    description = sample_description()
    description["features"].append({"id": "blind", "type": "hole", "position": [5, 5, 5],
                                    "diameter": 3, "extent": "blind", "depth": 2, "evidence_ids": ["drawing"]})
    result = build(description, tmp_path)
    description["measurements"].append({"id": "blind_depth", "kind": "hole", "expected": [3],
                                        "position": [5, 5, 5], "axis": "Z", "axial_length": 3,
                                        "basis": "printed_dimension", "evidence_ids": ["drawing"]})
    validated = validate_step(result["candidate_step"], description)
    assert validated["status"] == "fail"
    check = next(item for item in validated["checks"] if item["check"] == "blind_depth")
    assert check["actual_axial_lengths"] == pytest.approx([2])
