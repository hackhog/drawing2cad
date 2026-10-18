"""Calculated references remain separate from source measurements."""

import pytest

from drawing2cad_mcp.expected_checks import compare_expected
from drawing2cad_mcp.part_schema import parse_description
from test_part_schema import sample_description


def reference():
    return {"feature_id": "base", "volume": {"kind": "exact", "value": 1000.0},
            "bbox": {"kind": "exact", "min": [0, 0, 0], "max": [20, 10, 5], "size": [20, 10, 5]}}


def measured():
    return {"volume_mm3": 1000.0, "bbox_min": [0, 0, 0], "bbox_max": [20, 10, 5], "bbox_size": [20, 10, 5]}


def test_exact_comparison_retains_agent_source_evidence():
    part = parse_description(sample_description())
    original = part.model_dump()
    checks = compare_expected(reference(), measured(), part.measurements)
    assert all(row["status"] == "pass" for row in checks)
    assert part.model_dump() == original
    row = checks[-1]
    assert row["agent_expected"] == [20, 10, 5]
    assert row["basis"] == "printed_dimension"
    assert row["measurement_id"] == "overall"
    assert row["feature_id"] == "base"


@pytest.mark.parametrize("field,value", [("volume_mm3", 999), ("bbox_size", [19, 10, 5]),
                                         ("bbox_min", [1, 0, 0]), ("bbox_max", [21, 10, 5])])
def test_wrong_build_value_has_feature_and_difference(field, value):
    actual = measured()
    actual[field] = value
    failures = [row for row in compare_expected(reference(), actual) if row["status"] == "fail"]
    assert failures
    assert all(row["feature_id"] == "base" for row in failures)
    assert all("difference" in row and "tolerance" in row for row in failures)


def test_wrong_agent_value_fails_even_when_build_agrees():
    description = sample_description()
    description["measurements"][0]["expected"][0] = 19
    description["measurements"].append({"id": "volume", "kind": "volume", "expected": [900],
                                      "basis": "independent_measurement", "evidence_ids": ["drawing"]})
    part = parse_description(description)
    checks = compare_expected(reference(), measured(), part.measurements)
    agent = [row for row in checks if "measurement_id" in row]
    assert len(agent) == 2
    assert all(row["status"] == "fail" for row in agent)
    assert all(row["status"] == "pass" for row in checks if "measurement_id" not in row)


def test_bounds_use_interval_membership_and_outer_envelope():
    expected = reference()
    expected["volume"] = {"kind": "bound", "lower": 900, "upper": 1100, "reason": "Synthetic interval."}
    expected["bbox"] = {"kind": "bound", "lower": [0, 0, 0], "upper": [20, 10, 5],
                        "min": [0, 0, 0], "max": [20, 10, 5], "reason": "Synthetic envelope."}
    assert all(row["status"] == "pass" for row in compare_expected(expected, measured()))
    actual = measured()
    actual["volume_mm3"] = 1200
    actual["bbox_min"] = [-1, 0, 0]
    assert all(row["status"] == "fail" for row in compare_expected(expected, actual))


def test_unavailable_rules_are_not_tested_without_a_numeric_value():
    expected = {"feature_id": "finish", "volume": {"reason": "No fillet rule."}, "bbox": {"reason": "No fillet rule."}}
    checks = compare_expected(expected, measured())
    assert all(row["status"] == "not_tested" for row in checks)
    assert all("difference" not in row for row in checks)


def test_comparison_tolerance_is_explicit_and_small_roundoff_passes():
    actual = measured()
    actual["volume_mm3"] += 1e-5
    checks = compare_expected(reference(), actual)
    assert checks[0]["status"] == "pass"
    assert checks[0]["tolerance"] == pytest.approx([1e-4])
