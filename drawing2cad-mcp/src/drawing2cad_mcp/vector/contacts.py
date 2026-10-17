"""Find strokes that touch or cross a line anywhere along its length."""

from __future__ import annotations

import math

from .geometry import Grid, expand, point_segment_distance
from .model import Arc, Line, Point, Stroke

TOUCH = 0.06  # mm


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_cross(p: Point, q: Point, r: Point, s: Point) -> bool:
    """Return whether two segments cross at interior points."""
    d1, d2 = _cross(r, s, p), _cross(r, s, q)
    d3, d4 = _cross(p, q, r), _cross(p, q, s)
    return d1 * d2 < 0 and d3 * d4 < 0


def _line_meets(g: Line, other) -> bool:
    if isinstance(other, Line):
        if any(point_segment_distance(e, g.p0, g.p1)[0] < TOUCH for e in other.endpoints()):
            return True
        if any(point_segment_distance(e, other.p0, other.p1)[0] < TOUCH for e in g.endpoints()):
            return True
        return _segments_cross(g.p0, g.p1, other.p0, other.p1)
    arc: Arc = other
    if any(point_segment_distance(e, g.p0, g.p1)[0] < TOUCH for e in arc.endpoints()):
        return True
    if any(abs(math.dist(e, arc.center) - arc.radius) < TOUCH for e in g.endpoints()):
        return True
    # Count a crossing of the full circle as contact. This is conservative for arcs.
    near = point_segment_distance(arc.center, g.p0, g.p1)[0]
    far = max(math.dist(arc.center, e) for e in g.endpoints())
    return near < arc.radius < far


def contacts(s: Stroke, strokes: list[Stroke], grid: Grid) -> set[int]:
    """Return the IDs of other strokes that touch or cross this line at any point.
    The grid indexes stroke IDs that equal list positions."""
    g = s.geom
    out: set[int] = set()
    for i in grid.query(expand(g.bbox(), TOUCH)):
        t = strokes[i]
        if t is not s and _line_meets(g, t.geom):
            out.add(t.id)
    return out


__all__ = ["TOUCH", "contacts"]
