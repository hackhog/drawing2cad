"""Compare a projected model with the strokes of a drawing view.

The model edges are in part millimeters in the view plane: u to the right, v up.
The drawing strokes are in sheet millimeters: x to the right, y down, origin at the top left.
The view scale converts sheet millimeters to part millimeters. A translation aligns the two,
because the view origin on the sheet is not known. Rotation is not searched.

The pass limits are fixed in this module. A caller cannot change them.
This module needs numpy. The restricted CAD worker supplies it with the CAD dependencies.
"""

from __future__ import annotations

import math
from contextlib import contextmanager
import json
import sys
import time
from typing import Any

P95_LIMIT_MM = 0.3  # 95 % of model edge points are this close to a drawing edge (part mm)
MAX_LIMIT_MM = 1.0  # The worst model edge point (part mm)
COVERAGE_MIN = 0.85  # Share of drawing edge points within COVERAGE_DISTANCE_MM of a model edge
COVERAGE_DISTANCE_MM = 0.3
DISTANCE_CAP_MM = 10.0  # Larger distances are reported as this value
SAMPLE_STEP_MM = 0.25
MAX_POINTS = 20_000
MAX_SEGMENTS = 20_000
_REGISTER_POINTS = 1500
_WORST_COUNT = 12
_INDEX_PAIRS = 200_000


@contextmanager
def _stage(name):
    """Record fixed phase names in the bounded worker log, including an incomplete phase."""
    started = time.monotonic()
    print("D2C_PROJECTION:" + json.dumps({"stage": name, "event": "started"}), file=sys.stderr, flush=True)
    try:
        yield
    except BaseException:
        event = "failed"
        raise
    else:
        event = "completed"
    finally:
        print("D2C_PROJECTION:" + json.dumps({"stage": name, "event": event,
              "duration_seconds": round(time.monotonic() - started, 6)}), file=sys.stderr, flush=True)


def _segments(polylines):
    import numpy as np
    pieces = [(a, b) for line in polylines for a, b in zip(line, line[1:]) if a != b]
    if len(pieces) > MAX_SEGMENTS:
        raise ValueError(f"A view has more than {MAX_SEGMENTS} edge segments.")
    if not pieces:
        return np.zeros((0, 2)), np.zeros((0, 2))
    data = np.asarray(pieces, dtype=float)
    return data[:, 0, :], data[:, 1, :]


def _sample(polylines, step=SAMPLE_STEP_MM):
    """Return points along the polylines at about the given spacing, at most about MAX_POINTS.
    The spacing increases before the points are made, so that a long edge cannot exhaust the memory."""
    import numpy as np
    total = sum(math.hypot(x1 - x0, y1 - y0) for line in polylines for (x0, y0), (x1, y1) in zip(line, line[1:]))
    step = max(step, total / MAX_POINTS)
    points = []
    for line in polylines:
        for (x0, y0), (x1, y1) in zip(line, line[1:]):
            count = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / step))
            points.extend((x0 + (x1 - x0) * i / count, y0 + (y1 - y0) * i / count) for i in range(count))
        if line:
            points.append(tuple(line[-1]))
    data = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(data) > MAX_POINTS:
        data = data[:: math.ceil(len(data) / MAX_POINTS)]
    return data


def _distances(points, starts, ends, offset=(0.0, 0.0), index=None):
    """Return the distance from each point to the nearest segment, and the nearest location on it."""
    import numpy as np
    if index is not None:
        return index.distances(points, offset)
    if len(points) == 0 or len(starts) == 0:
        return np.full(len(points), DISTANCE_CAP_MM), np.zeros((len(points), 2))
    shifted = points + np.asarray(offset)
    direction = ends - starts
    length2 = np.maximum((direction ** 2).sum(axis=1), 1e-18)
    best = np.full(len(shifted), np.inf)
    nearest = np.zeros_like(shifted)
    chunk = max(1, 1_000_000 // max(1, len(starts)))
    for begin in range(0, len(shifted), chunk):
        block = shifted[begin:begin + chunk]
        # Separate coordinates avoid the larger point-by-segment-by-coordinate arrays.
        dx = block[:, 0, None] - starts[None, :, 0]
        dy = block[:, 1, None] - starts[None, :, 1]
        t = np.clip((dx * direction[None, :, 0] + dy * direction[None, :, 1]) / length2[None, :], 0.0, 1.0)
        foot_x = starts[None, :, 0] + t * direction[None, :, 0]
        foot_y = starts[None, :, 1] + t * direction[None, :, 1]
        distance2 = (block[:, 0, None] - foot_x) ** 2 + (block[:, 1, None] - foot_y) ** 2
        closest = distance2.argmin(axis=1)
        rows = np.arange(len(block))
        best[begin:begin + chunk] = np.sqrt(distance2[rows, closest])
        nearest[begin:begin + chunk, 0] = foot_x[rows, closest]
        nearest[begin:begin + chunk, 1] = foot_y[rows, closest]
    return np.minimum(best, DISTANCE_CAP_MM), nearest


class _SegmentIndex:
    """Use midpoint bounds to exclude segments that cannot contain a nearest point."""

    def __init__(self, starts, ends, tree_type):
        import numpy as np
        self.starts, self.ends = starts, ends
        self.direction = ends - starts
        self.length2 = np.maximum((self.direction ** 2).sum(axis=1), 1e-18)
        half_length = np.sqrt(self.length2) / 2
        # Long segments remain candidates. They must not enlarge the short-segment search radius.
        self.short = np.flatnonzero(half_length <= 1.0)
        self.long = np.flatnonzero(half_length > 1.0).tolist()
        self.radius = float(half_length[self.short].max())
        self.coordinate_scale = float(np.maximum(np.abs(starts), np.abs(ends)).max())
        self.tree = tree_type(starts[self.short] + self.direction[self.short] / 2)

    def distances(self, points, offset):
        import numpy as np
        shifted = points + np.asarray(offset)
        distances = np.empty(len(points))
        nearest = np.zeros_like(shifted)
        chunk = min(256, max(1, _INDEX_PAIRS // len(self.starts)))
        for begin in range(0, len(points), chunk):
            block = shifted[begin:begin + chunk]
            midpoint_distance, _ = self.tree.query(block)
            # A nearest midpoint is on a segment. Its distance is an upper bound for the exact distance.
            # Every better segment has a midpoint within that bound plus its half length.
            # Include rounding of midpoints and distance bounds at large coordinate offsets.
            padding = 8 * np.finfo(float).eps * np.maximum(self.coordinate_scale, np.abs(block).max(axis=1))
            radius = np.nextafter(midpoint_distance + self.radius + padding, np.inf)
            counts = self.tree.query_ball_point(block, radius, return_length=True) + len(self.long)
            if int(counts.sum()) > _INDEX_PAIRS:
                distances[begin:begin + chunk], nearest[begin:begin + chunk] = _distances(block, self.starts, self.ends)
                continue
            candidates = self.tree.query_ball_point(block, radius)
            candidates = [sorted(self.short[items].tolist() + self.long) for items in candidates]
            indices = np.concatenate(candidates)
            rows = np.repeat(np.arange(len(block)), counts)
            starts, direction = self.starts[indices], self.direction[indices]
            relative = block[rows] - starts
            t = np.clip((relative * direction).sum(axis=1) / self.length2[indices], 0.0, 1.0)
            foot = starts + t[:, None] * direction
            distance2 = ((block[rows] - foot) ** 2).sum(axis=1)
            first = np.r_[0, np.cumsum(counts)[:-1]]
            best = np.minimum.reduceat(distance2, first)
            # Sorted segment indices preserve the all-pairs search order when distances are equal.
            positions = np.minimum.reduceat(np.where(distance2 == best[rows], np.arange(len(indices)), len(indices)), first)
            distances[begin:begin + chunk] = np.minimum(np.sqrt(best), DISTANCE_CAP_MM)
            nearest[begin:begin + chunk] = foot[positions]
        return distances, nearest


def _segment_index(starts, ends):
    import numpy as np
    if len(starts) < 128 or np.count_nonzero(((ends - starts) ** 2).sum(axis=1) <= 4) < 128:
        return None
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        return None
    return _SegmentIndex(starts, ends, cKDTree)


def _register(model, starts, ends, start, points=_REGISTER_POINTS, index=None):
    """Refine a translation with trimmed nearest-segment pairs."""
    import numpy as np
    subset = model[:: max(1, len(model) // points)]
    offset = np.asarray(start, dtype=float)
    for _ in range(40):
        distance, nearest = _distances(subset, starts, ends, offset, index)
        keep = distance <= np.quantile(distance, 0.8)
        step = (nearest[keep] - (subset[keep] + offset)).mean(axis=0)
        offset = offset + step
        if math.hypot(*step) < 1e-5:
            break
    return offset


def _evaluate(deviation_lines, coverage_lines, drawing_points, drawing_starts, drawing_ends, orientation="direct", drawing_index=None):
    import numpy as np
    model = _sample(deviation_lines)
    if len(model) == 0:
        return None
    every = _sample(deviation_lines + coverage_lines)
    # Start from nine alignments of the bounding boxes (low edges, centres, high edges) and keep the best fit.
    # One start can stop in a local minimum, for example when long parallel edges slide along each other.
    low, high = every.min(axis=0), every.max(axis=0)
    d_low, d_high = drawing_points.min(axis=0), drawing_points.max(axis=0)
    choices = [(d_low - low), ((d_low + d_high) - (low + high)) / 2, (d_high - high)]
    # The score is the mean distance, limited to 2 mm, so that a few unmatched edges do not dominate.
    probe = model[:: max(1, len(model) // 400)]
    best = None
    with _stage(orientation + "_alignment"):
        for sx in choices:
            for sy in choices:
                candidate = _register(model, drawing_starts, drawing_ends, (sx[0], sy[1]), points=400, index=drawing_index)
                score = float(np.minimum(_distances(probe, drawing_starts, drawing_ends, candidate, drawing_index)[0], 2.0).mean())
                if best is None or score < best[0] - 1e-9:
                    best = (score, candidate)
        offset = _register(model, drawing_starts, drawing_ends, best[1], index=drawing_index)
    with _stage(orientation + "_comparison"):
        distance, _ = _distances(model, drawing_starts, drawing_ends, offset, drawing_index)
        model_starts, model_ends = _segments([[(x + offset[0], y + offset[1]) for x, y in line]
                                              for line in deviation_lines + coverage_lines])
        coverage_distance, _ = _distances(drawing_points, model_starts, model_ends, index=_segment_index(model_starts, model_ends))
    covered = coverage_distance <= COVERAGE_DISTANCE_MM
    worst = np.argsort(-distance)[:_WORST_COUNT]
    uncovered = drawing_points[~covered]
    return {
        "offset": offset, "p95": float(np.quantile(distance, 0.95)), "max": float(distance.max()),
        "coverage": float(covered.mean()),
        "worst": [((model[i] + offset).tolist(), float(distance[i])) for i in worst],
        "uncovered": uncovered[:: max(1, len(uncovered) // _WORST_COUNT)][:_WORST_COUNT].tolist(),
    }


def _mirror(lines, axis):
    if axis == "u":
        return [[(-x, y) for x, y in line] for line in lines]
    return [[(x, -y) for x, y in line] for line in lines]


def compare_view(model: dict[str, list], drawing_lines: list[list[tuple[float, float]]], *,
                 mm_per_sheet_mm: float) -> dict[str, Any]:
    """Compare one view.

    model: polylines in part mm with keys visible and tangent. Hidden model edges are not compared.
    drawing_lines: visible contour polylines in sheet mm (y down) inside the view region.
    Tangent edges count for coverage only, because drawings often omit them.
    """
    if not isinstance(mm_per_sheet_mm, (int, float)) or not math.isfinite(mm_per_sheet_mm) or mm_per_sheet_mm <= 0:
        raise ValueError("mm_per_sheet_mm must be positive.")
    deviation_lines = list(model.get("visible", []))
    coverage_lines = list(model.get("tangent", []))
    s = float(mm_per_sheet_mm)
    drawing_part = [[(x * s, -y * s) for x, y in line] for line in drawing_lines]
    drawing_starts, drawing_ends = _segments(drawing_part)
    drawing_points = _sample(drawing_part)
    if not deviation_lines or len(drawing_points) == 0:
        return {"status": "not_tested", "reason": "The model projection or the drawing view has no edges to compare.",
                "limits": limits()}

    drawing_index = _segment_index(drawing_starts, drawing_ends)
    result = _evaluate(deviation_lines, coverage_lines, drawing_points, drawing_starts, drawing_ends, drawing_index=drawing_index)
    checks = {"p95": result["p95"] <= P95_LIMIT_MM, "max": result["max"] <= MAX_LIMIT_MM,
              "coverage": result["coverage"] >= COVERAGE_MIN}
    mirror = []
    for axis in ("u", "v"):
        other = _evaluate(_mirror(deviation_lines, axis), _mirror(coverage_lines, axis),
                          drawing_points, drawing_starts, drawing_ends, "mirror_" + axis, drawing_index)
        if other is not None and other["p95"] <= P95_LIMIT_MM and other["p95"] < 0.5 * result["p95"]:
            mirror.append(axis)
    offset = result["offset"]

    def sheet(point):
        return [round(float(point[0]) / s, 3), round(-float(point[1]) / s, 3)]

    return {
        "status": "pass" if all(checks.values()) else "fail",
        "model_to_drawing": {"p95_mm": round(result["p95"], 4), "max_mm": round(result["max"], 4),
                             "max_capped": result["max"] >= DISTANCE_CAP_MM},
        "drawing_to_model": {"coverage": round(result["coverage"], 4)},
        "checks": {name: "pass" if ok else "fail" for name, ok in checks.items()},
        "mirror_candidate": mirror,
        "view_origin_sheet_mm": sheet(offset),
        "worst_points_sheet_mm": [{"point": sheet(point), "distance_mm": round(distance, 4)} for point, distance in result["worst"]],
        "uncovered_points_sheet_mm": [sheet(point) for point in result["uncovered"]],
        "limits": limits(),
        "overlay": {"model": [[sheet((x + offset[0], y + offset[1])) for x, y in line]
                              for line in deviation_lines + coverage_lines],
                    "drawing": [[[round(x, 3), round(y, 3)] for x, y in line] for line in drawing_lines]},
    }


def limits() -> dict[str, float]:
    return {"p95_mm": P95_LIMIT_MM, "max_mm": MAX_LIMIT_MM, "coverage_min": COVERAGE_MIN,
            "coverage_distance_mm": COVERAGE_DISTANCE_MM}
