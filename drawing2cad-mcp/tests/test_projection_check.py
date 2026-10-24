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


class ObservedTree:
    """Record candidate counts without changing the spatial search or its production limits."""

    def __init__(self, tree, long_segments):
        self.tree = tree
        self.long_segments = long_segments
        self.count_requests = 0
        self.list_requests = 0
        self.materialized_pairs = []

    def query(self, *args, **kwargs):
        return self.tree.query(*args, **kwargs)

    def query_ball_point(self, *args, **kwargs):
        result = self.tree.query_ball_point(*args, **kwargs)
        if kwargs.get("return_length"):
            self.count_requests += 1
        else:
            self.list_requests += 1
            self.materialized_pairs.append(sum(map(len, result)) + len(result) * self.long_segments)
        return result


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


def test_hidden_edges_are_not_compared():
    model = plate()
    model["hidden"] = [[(10, 0), (10, 30)]]
    assert compare_view(model, on_sheet(plate()), mm_per_sheet_mm=2.0)["status"] == "pass"


def test_long_edges_keep_the_point_limit():
    from drawing2cad_mcp.projection_check import MAX_POINTS, _sample
    points = _sample([[(0, 0), (10_000_000, 0)]])
    assert len(points) <= MAX_POINTS + 2


def test_empty_inputs_are_not_tested_and_limits_are_fixed():
    assert compare_view(plate(), [], mm_per_sheet_mm=2.0)["status"] == "not_tested"
    assert limits() == {"p95_mm": 0.3, "max_mm": 1.0, "coverage_min": 0.85, "coverage_distance_mm": 0.3}
    with pytest.raises(ValueError):
        compare_view(plate(), on_sheet(plate()), mm_per_sheet_mm=0)


def test_nearest_segments_match_an_independent_scalar_search():
    import numpy as np
    from drawing2cad_mcp.projection_check import DISTANCE_CAP_MM, _distances

    random = np.random.default_rng(42)
    starts = random.uniform(-20, 20, (53, 2))
    ends = starts + random.uniform(-10, 10, (53, 2))
    ends[0] = starts[0]
    points = np.vstack([random.uniform(-35, 35, (47, 2)), starts, (starts + ends) / 2])
    offset = (3.0, -7.0)
    distances, nearest = _distances(points, starts, ends, offset)
    for index, point in enumerate(points + offset):
        candidates = []
        for start, end in zip(starts, ends):
            dx, dy = end - start
            t = min(1.0, max(0.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy)
                             / max(dx * dx + dy * dy, 1e-18)))
            foot = start + t * (end - start)
            candidates.append((math.dist(point, foot), foot))
        expected_distance, expected_nearest = min(candidates, key=lambda item: item[0])
        assert distances[index] == pytest.approx(min(expected_distance, DISTANCE_CAP_MM), abs=1e-12)
        assert nearest[index] == pytest.approx(expected_nearest, abs=1e-12)


def test_projection_stage_log_records_failure_without_input_data(capsys):
    import json
    from drawing2cad_mcp.projection_check import _stage

    with pytest.raises(ValueError):
        with _stage("direct_alignment"):
            raise ValueError("private input data")
    lines = capsys.readouterr().err.splitlines()
    events = [json.loads(line.removeprefix("D2C_PROJECTION:")) for line in lines]
    assert [event["event"] for event in events] == ["started", "failed"]
    assert all(event["stage"] == "direct_alignment" for event in events)
    assert events[-1]["duration_seconds"] >= 0
    assert "private input data" not in "".join(lines)


def test_nearest_segments_cross_the_matrix_chunk_boundary():
    import numpy as np
    from drawing2cad_mcp.projection_check import _distances

    starts = np.column_stack((np.arange(5003) * 3.0, np.zeros(5003)))
    ends = starts + (0.0, 1.0)
    expected = starts[np.linspace(0, 5002, 207, dtype=int)] + (0.0, 0.5)
    distances, nearest = _distances(expected + (0.25, 0.0), starts, ends)
    assert distances == pytest.approx(np.full(207, 0.25))
    assert nearest == pytest.approx(expected)


@pytest.mark.parametrize("dense_fallback", [False, True])
def test_segment_index_preserves_exact_distances_and_nearest_points(monkeypatch, dense_fallback):
    import numpy as np
    from drawing2cad_mcp import projection_check as comparison

    pytest.importorskip("scipy.spatial")
    random = np.random.default_rng(66)
    starts = random.uniform(-20, 20, (350, 2))
    ends = starts + random.uniform(-0.5, 0.5, (350, 2))
    # Include long segments, zero length segments, and equal-distance segments in their original order.
    starts[:4] = [(0, 0), (0, 0), (-50, -50), (5, 5)]
    ends[:4] = [(1, 0), (1, 0), (50, 50), (5, 5)]
    points = np.vstack([random.uniform(-100, 100, (57, 2)), starts, ends, (starts + ends) / 2])
    index = comparison._segment_index(starts, ends)
    assert index is not None
    if dense_fallback:
        monkeypatch.setattr(comparison, "_INDEX_PAIRS", 1)
    expected_distance, expected_nearest = comparison._distances(points, starts, ends, (2.0, -3.0))
    distance, nearest = comparison._distances(points, starts, ends, (2.0, -3.0), index=index)
    assert distance == pytest.approx(expected_distance, abs=1e-12)
    assert nearest == pytest.approx(expected_nearest, abs=1e-12)


def test_segment_index_is_optional(monkeypatch):
    import numpy as np
    import sys
    from drawing2cad_mcp.projection_check import _segment_index

    monkeypatch.setitem(sys.modules, "scipy.spatial", None)
    starts = np.zeros((150, 2))
    assert _segment_index(starts, starts + 0.25) is None


@pytest.mark.parametrize("origin", [0.0, float(2 ** 40), float(-(2 ** 40))])
def test_segment_index_keeps_short_segments_at_large_offsets(origin):
    import numpy as np
    from drawing2cad_mcp.projection_check import _distances, _segment_index

    pytest.importorskip("scipy.spatial")
    spacing = np.spacing(float(2 ** 40))
    starts = np.column_stack((origin + np.arange(150) * spacing * 4, np.full(150, origin)))
    ends = starts + (spacing, spacing * 2)
    points = np.vstack([starts, ends, starts + (spacing * 2, spacing * 3), starts - (spacing, spacing)])
    index = _segment_index(starts, ends)
    expected_distance, expected_nearest = _distances(points, starts, ends)
    distance, nearest = _distances(points, starts, ends, index=index)
    assert distance == pytest.approx(expected_distance, abs=1e-15)
    assert nearest == pytest.approx(expected_nearest, abs=1e-15, rel=0)


def test_segment_index_preserves_distance_thresholds():
    import numpy as np
    from drawing2cad_mcp.projection_check import _distances, _segment_index

    pytest.importorskip("scipy.spatial")
    starts = np.column_stack((np.arange(150) * 3.0, np.zeros(150)))
    ends = starts + (1.0, 0.0)
    heights = np.array([0.3 - 1e-10, 0.3, 0.3 + 1e-10, 1 - 1e-10, 1, 1 + 1e-10, 10 - 1e-10, 10, 10 + 1e-10])
    points = np.column_stack((np.full(len(heights), 0.5), heights))
    expected, expected_nearest = _distances(points, starts, ends)
    actual, nearest = _distances(points, starts, ends, index=_segment_index(starts, ends))
    assert np.array_equal(actual, expected)
    assert np.array_equal(nearest, expected_nearest)
    for threshold in (0.3, 1.0, 10.0):
        assert np.array_equal(actual <= threshold, expected <= threshold)


def test_indexed_view_result_matches_all_pairs_result(monkeypatch):
    from drawing2cad_mcp import projection_check as comparison

    pytest.importorskip("scipy.spatial")
    model = plate(hole_x=15)
    model["visible"][1] = circle(15, 20, 4, n=192)
    drawing = on_sheet({"visible": [[(60 - x, y) for x, y in line] for line in model["visible"]]})
    indexed = compare_view(model, drawing, mm_per_sheet_mm=2)
    monkeypatch.setattr(comparison, "_segment_index", lambda starts, ends: None)
    assert compare_view(model, drawing, mm_per_sheet_mm=2) == indexed
    assert indexed["status"] == "fail" and indexed["mirror_candidate"] == ["u"]


def test_dense_candidates_use_the_production_fallback_before_list_allocation():
    import numpy as np
    from drawing2cad_mcp.projection_check import _INDEX_PAIRS, _distances, _segment_index, _segments

    pytest.importorskip("scipy.spatial")
    starts, ends = _segments([circle(0, 0, 1, n=1024)])
    points = np.zeros((256, 2))
    assert len(points) * len(starts) > _INDEX_PAIRS
    index = _segment_index(starts, ends)
    assert index is not None
    observed = ObservedTree(index.tree, len(index.long))
    index.tree = observed
    expected_distance, expected_nearest = _distances(points, starts, ends)
    distance, nearest = _distances(points, starts, ends, index=index)
    assert np.array_equal(distance, expected_distance)
    assert np.array_equal(nearest, expected_nearest)
    assert observed.count_requests == 1
    assert observed.list_requests == 0


def test_representative_arcs_and_long_lines_select_the_index_and_reduce_work():
    import numpy as np
    from drawing2cad_mcp.projection_check import _INDEX_PAIRS, _distances, _segment_index, _segments

    pytest.importorskip("scipy.spatial")
    lines = [circle(0, 0, 50, n=512)]
    for number in range(8):
        angle = 2 * math.pi * number / 8
        lines.append(circle(30 * math.cos(angle), 30 * math.sin(angle), 5, n=256))
    lines.extend([[(100 + 2 * number, -10), (100 + 2 * number, 10)] for number in range(200)])
    starts, ends = _segments(lines)
    index = _segment_index(starts, ends)
    assert index is not None
    assert len(index.long) == 200
    points = (starts[index.short[::4]] + ends[index.short[::4]]) / 2
    observed = ObservedTree(index.tree, len(index.long))
    index.tree = observed
    expected_distance, expected_nearest = _distances(points, starts, ends)
    distance, nearest = _distances(points, starts, ends, index=index)
    assert np.array_equal(distance, expected_distance)
    assert np.array_equal(nearest, expected_nearest)
    expected_blocks = math.ceil(len(points) / 256)
    assert observed.count_requests == observed.list_requests == expected_blocks
    assert max(observed.materialized_pairs) <= _INDEX_PAIRS
    assert sum(observed.materialized_pairs) < len(points) * len(starts) / 4
