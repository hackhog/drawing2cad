"""Pure geometry expectations, independent of CAD construction."""

import math

import pytest

from drawing2cad_mcp.expected_values import compute_expected
from drawing2cad_mcp.part_schema import parse_description
from test_part_schema import sample_description


def _expected(features):
    description = sample_description()
    description["schema_version"] = "1.3"
    description["features"] = features
    description["measurements"] = []
    return compute_expected(parse_description(description))


def _feature(identifier, kind, **fields):
    return {"id": identifier, "type": kind, "evidence_ids": ["drawing"], **fields}


def test_parameter_box_and_per_feature_addition():
    base = _feature("base", "box", operation="base", length=20, width=10, height=5)
    addition = _feature("add", "box", operation="add", origin=[15, 0, 0],
                        length=10, width=10, height=5)
    result = _expected([base, addition])
    assert [row["volume"]["value"] for row in result["features"]] == pytest.approx([1000, 1250])
    assert result["final"]["bbox"]["size"] == pytest.approx([25, 10, 5])


def test_cylinder_on_negative_y_axis():
    body = _feature("body", "cylinder", operation="base", diameter=8,
                    height=12, origin=[3, 15, 4], axis="-Y")
    row = _expected([body])["final"]
    assert row["volume"]["value"] == pytest.approx(math.pi * 4**2 * 12)
    assert row["bbox"]["min"] == pytest.approx([-1, 3, 0])
    assert row["bbox"]["max"] == pytest.approx([7, 15, 8])


def test_cylinder_parameter_reference():
    body = _feature("body", "cylinder", operation="base",
                    diameter={"parameter": "length"}, height=2, axis="-Y")
    row = _expected([body])["final"]
    assert row["volume"]["value"] == pytest.approx(math.pi * 100 * 2)
    assert row["bbox"]["size"] == pytest.approx([20, 2, 20])


def test_reflected_profile_extrusion():
    body = _feature("body", "profile_extrusion", operation="base", axis="-X",
                    origin=[10, 2, 3], height=5, segments=[
                        {"kind": "line", "start": [0, 0], "end": [4, 0]},
                        {"kind": "line", "start": [4, 0], "end": [4, 3]},
                        {"kind": "line", "start": [4, 3], "end": [0, 3]},
                        {"kind": "line", "start": [0, 3], "end": [0, 0]},
                    ])
    row = _expected([body])["final"]
    assert row["volume"]["value"] == pytest.approx(60)
    assert row["bbox"]["min"] == pytest.approx([5, 2, 0])
    assert row["bbox"]["max"] == pytest.approx([10, 6, 3])


def test_overlapping_and_duplicate_circular_holes():
    base = _feature("base", "box", operation="base", length=20, width=20, height=5)
    first = _feature("first", "hole", position=[8, 10, 5], diameter=6)
    second = _feature("second", "hole", position=[12, 10, 5], diameter=6)
    duplicate = _feature("duplicate", "hole", position=[8, 10, 5], diameter=6)
    rows = _expected([base, first, second, duplicate])["features"]
    r, d = 3, 4
    overlap = 2 * r * r * math.acos(d / (2 * r)) - d / 2 * math.sqrt(4 * r * r - d * d)
    assert rows[1]["volume"]["value"] == pytest.approx(2000 - math.pi * r * r * 5)
    assert rows[2]["volume"]["value"] == pytest.approx(2000 - (2 * math.pi * r * r - overlap) * 5)
    assert rows[3]["volume"]["value"] == pytest.approx(rows[2]["volume"]["value"])


def test_three_collinear_overlapping_holes():
    base = _feature("base", "box", operation="base", length=20, width=20, height=5)
    holes = [_feature(f"hole{i}", "hole", position=[6 + 2 * i, 10, 5], diameter=6)
             for i in range(3)]
    row = _expected([base, *holes])["final"]
    r, d = 3, 2
    pair = 2 * r * r * math.acos(d / (2 * r)) - d / 2 * math.sqrt(4 * r * r - d * d)
    assert row["volume"]["value"] == pytest.approx(2000 - (3 * math.pi * r * r - 2 * pair) * 5)


def test_mixed_circular_polygon_cut_and_off_body_tool():
    base = _feature("base", "box", operation="base", length=20, width=20, height=5)
    pocket = _feature("pocket", "pocket", origin=[0, 10, 5], axis="-Z",
                      profile={"shape": "box", "length": 10, "width": 10, "depth": 2})
    hole = _feature("hole", "hole", position=[9, 5, 5], diameter=4)
    away = _feature("away", "cut", origin=[100, 100, 0],
                    profile={"shape": "cylinder", "diameter": 4, "depth": 5})
    rows = _expected([base, pocket, hole, away])["features"]
    assert rows[1]["volume"]["value"] == pytest.approx(1800)
    cap = 4 * math.acos(.5) - math.sqrt(3)
    assert rows[2]["volume"]["value"] == pytest.approx(1800 - math.pi * 4 * 3 - cap * 2)
    assert rows[3]["volume"]["value"] == pytest.approx(rows[2]["volume"]["value"])
    assert rows[3]["bbox"]["size"] == pytest.approx([20, 20, 5])


def test_add_after_cut_restores_material():
    base = _feature("base", "box", operation="base", length=10, width=10, height=5)
    cut = _feature("cut", "cut", origin=[0, 0, 0],
                   profile={"shape": "box", "length": 5, "width": 10, "depth": 5})
    add = _feature("add", "box", operation="add", length=5, width=10, height=5)
    rows = _expected([base, cut, add])["features"]
    assert [row["volume"]["value"] for row in rows] == pytest.approx([500, 250, 500])


def test_signed_x_axis_and_box_common_sweep():
    base = _feature("base", "box", operation="base", length=10, width=10, height=10)
    bore = _feature("bore", "hole", position=[10, 5, 5], axis="-X", diameter=2)
    rows = _expected([base, bore])["features"]
    assert rows[0]["volume"]["value"] == pytest.approx(1000)
    assert rows[1]["volume"]["value"] == pytest.approx(1000 - 10 * math.pi)
    assert rows[1]["bbox"]["size"] == pytest.approx([10, 10, 10])


def test_major_clockwise_arc_area_and_extrema():
    outline = _feature("outline", "profile_extrusion", operation="base", height=2,
                       segments=[
                           {"kind": "three_point_arc", "start": [1, 0], "mid": [0, -1],
                            "end": [0, 1]},
                           {"kind": "line", "start": [0, 1], "end": [1, 0]},
                       ])
    row = _expected([outline])["final"]
    assert row["volume"]["value"] == pytest.approx((3 * math.pi / 4 + .5) * 2)
    assert row["bbox"]["min"] == pytest.approx([-1, -1, 0])
    assert row["bbox"]["max"] == pytest.approx([1, 1, 2])


def test_clockwise_major_arc_extremum_below_negative_full_turn():
    outline = _feature("outline", "profile_extrusion", operation="base", height=2,
                       segments=[
                           {"kind": "three_point_arc", "start": [-1, -1e-6],
                            "mid": [1, 0], "end": [-math.sqrt(.5), -math.sqrt(.5)]},
                           {"kind": "line", "start": [-math.sqrt(.5), -math.sqrt(.5)],
                            "end": [-1, -1e-6]},
                       ])
    row = _expected([outline])["final"]
    assert row["bbox"]["min"][1] == pytest.approx(-1, abs=1e-5)


def test_unsupported_operation_propagates():
    base = _feature("base", "box", operation="base", length=10, width=10, height=5)
    countersink = _feature("sink", "hole", position=[5, 5, 5], diameter=2,
                           style="countersink", counter_diameter=4, angle=90)
    add = _feature("add", "box", operation="add", origin=[10, 0, 0],
                   length=5, width=10, height=5)
    rows = _expected([base, countersink, add])["features"]
    assert rows[0]["volume"]["kind"] == "exact"
    assert all("reason" in row["volume"] and "value" not in row["volume"] for row in rows[1:])


def test_nonparallel_geometry_does_not_claim_exact():
    base = _feature("base", "cylinder", operation="base", diameter=10, height=10)
    bore = _feature("bore", "hole", position=[0, 0, 5], axis="X", diameter=2)
    rows = _expected([base, bore])["features"]
    assert rows[0]["volume"]["kind"] == "exact"
    assert rows[1]["volume"]["kind"] == "bound"
    assert rows[1]["volume"]["lower"] <= rows[0]["volume"]["value"]
    assert rows[1]["volume"]["upper"] == pytest.approx(rows[0]["volume"]["value"])


def test_nonparallel_addition_extends_conservative_bbox():
    base = _feature("base", "cylinder", operation="base", diameter=10, height=10)
    add = _feature("add", "cylinder", operation="add", diameter=4,
                   height=10, axis="X", origin=[0, 0, 5])
    row = _expected([base, add])["final"]
    assert row["volume"]["kind"] == "bound"
    assert row["volume"]["lower"] == pytest.approx(math.pi * 25 * 10)
    assert row["volume"]["upper"] == pytest.approx(math.pi * 25 * 10 + math.pi * 4 * 10)
    assert row["bbox"]["max"][0] == pytest.approx(10)


@pytest.mark.parametrize("axis,position", [
    ("X", [0, 5, 5]), ("-X", [10, 5, 5]),
    ("Y", [5, 0, 5]), ("-Y", [5, 10, 5]),
    ("Z", [5, 5, 0]), ("-Z", [5, 5, 10]),
])
def test_all_signed_hole_axes(axis, position):
    base = _feature("base", "box", operation="base", length=10, width=10, height=10)
    bore = _feature("bore", "hole", position=position, axis=axis, diameter=2)
    row = _expected([base, bore])["final"]
    assert row["volume"]["value"] == pytest.approx(1000 - 10 * math.pi)
    assert row["bbox"]["size"] == pytest.approx([10, 10, 10])


def test_blind_counterbore_and_polygon_cut():
    base = _feature("base", "box", operation="base", length=20, width=20, height=10)
    bore = _feature("bore", "hole", position=[10, 10, 10], diameter=4,
                    extent="blind", depth=6, style="counterbore",
                    counter_diameter=8, counter_depth=2)
    triangle = _feature("triangle", "cut", origin=[0, 4, 10], axis="-Z",
                        profile={"shape": "polygon", "points": [[0, 0], [4, 0], [0, 4]],
                                 "depth": 2})
    rows = _expected([base, bore, triangle])["features"]
    assert rows[1]["volume"]["value"] == pytest.approx(4000 - math.pi * (4 * 6 + 12 * 2))
    assert rows[2]["volume"]["value"] == pytest.approx(rows[1]["volume"]["value"] - 16)


def test_extrusion_and_profile_cut():
    base = _feature("base", "extrusion", operation="base", height=4,
                    points=[[0, 0], [10, 0], [10, 10], [0, 10]])
    cut = _feature("cut", "cut", origin=[0, 0, 0],
                   profile={"shape": "profile", "depth": 4, "segments": [
                       {"kind": "line", "start": [0, 0], "end": [4, 0]},
                       {"kind": "line", "start": [4, 0], "end": [0, 4]},
                       {"kind": "line", "start": [0, 4], "end": [0, 0]},
                   ]})
    rows = _expected([base, cut])["features"]
    assert rows[0]["volume"]["value"] == pytest.approx(400)
    assert rows[1]["volume"]["value"] == pytest.approx(368)


def test_tapered_feature_propagates_unavailable():
    base = _feature("base", "cylinder", operation="base", diameter=10,
                    height=10, taper_angle=1e-12)
    row = _expected([base])["final"]
    assert "reason" in row["volume"] and "value" not in row["volume"]
    assert "base" in row["volume"]["reason"]


def test_chamfer_propagates_unavailable():
    base = _feature("base", "box", operation="base", length=10, width=10, height=5)
    dress = _feature("dress", "chamfer", size=1,
                     selector={"center_min": [0, 0, 0], "center_max": [10, 10, 5],
                               "expected_count": 1})
    add = _feature("add", "box", operation="add", origin=[10, 0, 0],
                   length=5, width=10, height=5)
    rows = _expected([base, dress, add])["features"]
    assert rows[0]["volume"]["kind"] == "exact"
    assert "dress" in rows[1]["volume"]["reason"]
    assert rows[2]["volume"] == rows[1]["volume"]


def test_near_coincident_boundaries_do_not_claim_exact():
    base = _feature("base", "box", operation="base", length=10, width=10, height=5)
    cut = _feature("cut", "cut", origin=[0, 1e-7, 0],
                   profile={"shape": "box", "length": 5, "width": 5, "depth": 5})
    row = _expected([base, cut])["final"]
    assert "reason" in row["volume"] and "value" not in row["volume"]


def test_self_intersecting_profile_with_nonzero_signed_area_is_unavailable():
    body = _feature("body", "extrusion", operation="base", height=2,
                    points=[[0, 0], [5, 5], [0, 5], [4, 0]])
    row = _expected([body])["final"]
    assert "intersects itself" in row["volume"]["reason"]
    assert "value" not in row["volume"]


def test_cumulative_work_limit_returns_bound():
    base = _feature("base", "box", operation="base", length=20, width=20, height=5)
    holes = [_feature(f"h{i}", "hole", position=[10, 10, 5], diameter=2)
             for i in range(25)]
    rows = _expected([base, *holes])["features"]
    assert any(row["volume"].get("kind") == "bound" for row in rows)
    assert rows[-1]["volume"]["kind"] == "bound"
