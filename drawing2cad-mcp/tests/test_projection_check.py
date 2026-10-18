"""Synthetic model-to-drawing comparisons."""

import math

import pytest

from drawing2cad_mcp.projection_check import compare_view, limits


def rectangle(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def circle(cx, cy, r, n=96):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]


def plate(hole_x=30.0, width=60.0, height=30.0):
    """A plate with one off-centre hole, in part mm (v up)."""
    return {"visible": [rectangle(0, 0, width, height), circle(hole_x, 20, 4)], "tangent": [], "hidden": []}


def on_sheet(model, scale=2.0, origin=(100.0, 150.0)):
    """Draw a model view on a 1:2 sheet: sheet = origin + (u, -v) / scale."""
    return [[(origin[0] + x / scale, origin[1] - y / scale) for x, y in line] for line in model["visible"]]


def test_correct_part_passes():
    result = compare_view(plate(), on_sheet(plate()), mm_per_sheet_mm=2.0)
    assert result["status"] == "pass", result
    assert result["model_to_drawing"]["max_mm"] < 0.05
    assert result["drawing_to_model"]["coverage"] > 0.99
    assert result["view_origin_sheet_mm"] == pytest.approx([100, 150], abs=0.02)
    assert result["mirror_candidate"] == []


def test_shifted_hole_fails_at_the_hole():
    result = compare_view(plate(hole_x=33), on_sheet(plate()), mm_per_sheet_mm=2.0)
    assert result["status"] == "fail"
    assert result["checks"]["max"] == "fail"
    # The worst points are on the hole, not on the outline: x near 100 + 33 / 2 on the sheet.
    worst = result["worst_points_sheet_mm"][0]
    assert abs(worst["point"][0] - 116.5) < 3 and worst["distance_mm"] > 1.0


def test_swapped_axis_fails():
    swapped = {"visible": [rectangle(0, 0, 30, 60), circle(20, 30, 4)], "tangent": [], "hidden": []}
    result = compare_view(swapped, on_sheet(plate()), mm_per_sheet_mm=2.0)
    assert result["status"] == "fail"
    assert result["checks"]["p95"] == "fail"


def test_mirrored_view_fails_and_names_the_mirror():
    mirrored = {"visible": [[(60 - x, y) for x, y in line] for line in plate(hole_x=15)["visible"]], "tangent": [], "hidden": []}
    result = compare_view(plate(hole_x=15), on_sheet(mirrored), mm_per_sheet_mm=2.0)
    assert result["status"] == "fail"
    assert result["mirror_candidate"] == ["u"]


def test_wrong_scale_fails():
    assert compare_view(plate(), on_sheet(plate()), mm_per_sheet_mm=2.1)["status"] == "fail"


def test_missing_feature_reduces_coverage():
    drawing = on_sheet(plate()) + on_sheet({"visible": [rectangle(5, 3, 25, 11)]})
    result = compare_view(plate(), drawing, mm_per_sheet_mm=2.0)
    assert result["checks"]["coverage"] == "fail"
    assert result["uncovered_points_sheet_mm"]


def test_tangent_edges_count_only_for_coverage():
    model = plate()
    model["tangent"] = [[(0, 5), (60, 5)]]
    assert compare_view(model, on_sheet(plate()), mm_per_sheet_mm=2.0)["status"] == "pass"


def test_hidden_edges_are_compared_only_on_request():
    model = plate()
    model["hidden"] = [[(10, 0), (10, 30)]]
    assert compare_view(model, on_sheet(plate()), mm_per_sheet_mm=2.0)["status"] == "pass"
    assert compare_view(model, on_sheet(plate()), mm_per_sheet_mm=2.0, hidden_lines="compare")["status"] == "fail"


def test_empty_inputs_are_not_tested_and_limits_are_fixed():
    assert compare_view(plate(), [], mm_per_sheet_mm=2.0)["status"] == "not_tested"
    assert limits() == {"p95_mm": 0.3, "max_mm": 1.0, "coverage_min": 0.85, "coverage_distance_mm": 0.3}
    with pytest.raises(ValueError):
        compare_view(plate(), on_sheet(plate()), mm_per_sheet_mm=0)
