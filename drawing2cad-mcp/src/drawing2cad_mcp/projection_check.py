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


def _distances(points, starts, ends, offset=(0.0, 0.0)):
    """Return the distance from each point to the nearest segment, and the nearest location on it."""
    import numpy as np
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
        relative = block[:, None, :] - starts[None, :, :]
        t = np.clip((relative * direction[None, :, :]).sum(axis=2) / length2[None, :], 0.0, 1.0)
        foot = starts[None, :, :] + t[:, :, None] * direction[None, :, :]
        distance2 = ((block[:, None, :] - foot) ** 2).sum(axis=2)
        index = distance2.argmin(axis=1)
        rows = np.arange(len(block))
        best[begin:begin + chunk] = np.sqrt(distance2[rows, index])
        nearest[begin:begin + chunk] = foot[rows, index]
    return np.minimum(best, DISTANCE_CAP_MM), nearest


def _register(model, starts, ends, start, points=_REGISTER_POINTS):
    """Refine a translation with trimmed nearest-segment pairs."""
    import numpy as np
    subset = model[:: max(1, len(model) // points)]
    offset = np.asarray(start, dtype=float)
    for _ in range(40):
        distance, nearest = _distances(subset, starts, ends, offset)
        keep = distance <= np.quantile(distance, 0.8)
        step = (nearest[keep] - (subset[keep] + offset)).mean(axis=0)
        offset = offset + step
        if math.hypot(*step) < 1e-5:
            break
    return offset


def _evaluate(deviation_lines, coverage_lines, drawing_points, drawing_starts, drawing_ends):
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
    for sx in choices:
        for sy in choices:
            candidate = _register(model, drawing_starts, drawing_ends, (sx[0], sy[1]), points=400)
            score = float(np.minimum(_distances(probe, drawing_starts, drawing_ends, candidate)[0], 2.0).mean())
            if best is None or score < best[0] - 1e-9:
                best = (score, candidate)
    offset = _register(model, drawing_starts, drawing_ends, best[1])
    distance, _ = _distances(model, drawing_starts, drawing_ends, offset)
    model_starts, model_ends = _segments([[(x + offset[0], y + offset[1]) for x, y in line]
                                          for line in deviation_lines + coverage_lines])
    coverage_distance, _ = _distances(drawing_points, model_starts, model_ends)
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

    result = _evaluate(deviation_lines, coverage_lines, drawing_points, drawing_starts, drawing_ends)
    checks = {"p95": result["p95"] <= P95_LIMIT_MM, "max": result["max"] <= MAX_LIMIT_MM,
              "coverage": result["coverage"] >= COVERAGE_MIN}
    mirror = []
    for axis in ("u", "v"):
        other = _evaluate(_mirror(deviation_lines, axis), _mirror(coverage_lines, axis),
                          drawing_points, drawing_starts, drawing_ends)
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
