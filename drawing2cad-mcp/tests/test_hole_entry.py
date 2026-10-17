"""Hole entry checks distinguish openings from axes, shoulders, and caps."""

from copy import deepcopy

import pytest

pytest.importorskip("build123d")

from drawing2cad_mcp.cad_kernel import build
from drawing2cad_mcp.cad_validation import validate_step
from drawing2cad_mcp.part_schema import part_validate
from test_part_schema import sample_description


def description(*, bottom=False, style="plain", extent="blind", drill=False):
    part = sample_description()
    part["features"][0]["height"] = 10
    part["measurements"][0]["expected"] = [20, 10, 10]
    hole = {"id": "bore", "type": "hole", "position": [5, 5, 0 if bottom else 10],
            "axis": "Z" if bottom else "-Z", "diameter": 3, "extent": extent,
            "style": style, "evidence_ids": ["drawing"]}
    if extent == "blind":
        hole["depth"] = 3
    if style == "counterbore":
        hole.update(counter_diameter=6, counter_depth=1)
    if style == "countersink":
        hole.update(counter_diameter=5, angle=90)
    if drill:
        hole["drill_angle"] = 118
    part["features"].append(hole)
    return part


def measure(part, *, entry=None, axis="-Z", diameter=3):
    result = deepcopy(part)
    item = {"id": "source_hole", "kind": "hole", "position": [5, 5, 5],
            "axis": axis, "expected": [diameter], "basis": "printed_dimension",
            "evidence_ids": ["drawing"]}
    if entry is not None:
        item["entry_position"] = entry
    result["measurements"].append(item)
    return result


def hole_check(result):
    return next(item for item in result["checks"] if item["check"] == "source_hole")


def test_axis_anchor_alone_does_not_claim_entry_verification(tmp_path):
    part = measure(description(bottom=True))
    built = build(part, tmp_path)
    assert built["status"] == "pass"
    check = hole_check(validate_step(built["candidate_step"], part))
    assert check["status"] == "pass"
    assert check["entry_side"] == "not_tested"


@pytest.mark.parametrize("entry,axis,passed", [
    ([5, 5, 0], "Z", True), ([5, 5, 10], "-Z", False),
    ([5, 5, 0], "-Z", False), ([5, 5, 3], "-Z", False),
])
def test_blind_hole_entry_side_direction_and_bottom_cap(tmp_path, entry, axis, passed):
    part = description(bottom=True)
    built = build(part, tmp_path)
    expected = measure(part, entry=entry, axis=axis)
    result = validate_step(built["candidate_step"], expected)
    assert (result["status"] == "pass") is passed
    assert hole_check(result)["entry_side"] == ("pass" if passed else "fail")


@pytest.mark.parametrize("style,drill", [("plain", True), ("counterbore", False), ("countersink", False)])
def test_entry_traverses_cones_and_counterbore_shoulders(tmp_path, style, drill):
    part = measure(description(style=style, drill=drill), entry=[5, 5, 10])
    built = build(part, tmp_path)
    assert built["status"] == "pass", built
    result = validate_step(built["candidate_step"], part)
    assert result["status"] == "pass", result
    assert hole_check(result)["actual_entry_positions"] == [[5, 5, 10]]
    if style == "counterbore":
        part["measurements"][-1]["entry_position"] = [5, 5, 9]
        assert validate_step(built["candidate_step"], part)["status"] == "fail"


def test_opposite_bores_cannot_supply_each_others_diameter_and_entry(tmp_path):
    part = description(bottom=True)
    part["features"].append({"id": "top", "type": "hole", "position": [5, 5, 10],
                              "axis": "-Z", "diameter": 4, "extent": "blind", "depth": 3,
                              "evidence_ids": ["drawing"]})
    built = build(part, tmp_path)
    assert validate_step(built["candidate_step"], measure(part, entry=[5, 5, 10]))["status"] == "fail"
    assert validate_step(built["candidate_step"], measure(part, entry=[5, 5, 10], diameter=4))["status"] == "pass"


@pytest.mark.parametrize("axis,entry", [("-Z", [5, 5, 10]), ("Z", [5, 5, 0])])
def test_through_bore_with_two_chamfers_has_two_supported_entries(tmp_path, axis, entry):
    part = description(extent="through")
    part["features"].append({"id": "rims", "type": "chamfer", "size": 0.5,
                              "selector": {"geometry": "circle", "radius": 1.5,
                                           "center_min": [5, 5, 0], "center_max": [5, 5, 10],
                                           "expected_count": 2}, "evidence_ids": ["drawing"]})
    part = measure(part, entry=entry, axis=axis)
    built = build(part, tmp_path)
    assert built["status"] == "pass", built
    assert validate_step(built["candidate_step"], part)["status"] == "pass"


def test_toroidal_transition_does_not_get_an_unsupported_entry_pass(tmp_path):
    part = description(extent="through")
    part["features"].append({"id": "round_rim", "type": "fillet", "size": 0.5,
                              "selector": {"geometry": "circle", "radius": 1.5,
                                           "center_min": [5, 5, 10], "center_max": [5, 5, 10],
                                           "expected_count": 1}, "evidence_ids": ["drawing"]})
    built = build(part, tmp_path)
    for point in ([5, 5, 10], [5, 5, 9.5]):
        result = validate_step(built["candidate_step"], measure(part, entry=point))
        assert result["status"] == "fail"
        assert hole_check(result)["entry_side"] == "fail"


def test_entry_schema_rejects_other_measurements_and_off_axis_anchors():
    part = description()
    part["measurements"][0]["entry_position"] = [5, 5, 10]
    assert part_validate(part)["status"] == "fail"
    part = measure(description(), entry=[6, 5, 10])
    assert part_validate(part)["status"] == "fail"
