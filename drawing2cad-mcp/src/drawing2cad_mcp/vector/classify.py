"""Classify drawing strokes with deterministic rules.

Line width alone does not identify a stroke class reliably.
The rules use geometry and the calibrated drawing profile in this order:

1. Cutting planes: thick strokes or large arrows, with their shafts.
2. Dimension arrows: closed narrow triangles and their fill strokes.
3. Dimension lines: strokes aligned with arrow tips, including continuations.
4. Extension lines: transverse lines with a short free end.
5. Hatching: equally spaced parallel lines.
6. Dashed lines and circles: classify regular dashes or alternating dash lengths.
7. Center marks: thin lines through circle centers, and thin pieces on a centerline carrier.
8. Remaining strokes: contour candidates.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from .contacts import contacts, index_box
from .geometry import Grid, angle_diff, expand, point_segment_distance
from .model import Arc, Kind, Line, Point, Stroke

_TOUCH = 0.06  # mm: endpoint contact tolerance
_CUTTING_PLANE_WIDTH = 0.45  # mm: lower limit for a cutting-plane line
_CUTTING_PLANE_MARGIN = 0.05  # mm above the dominant line width
_ARROW_MAX_SIDE = 10.0  # mm
_ARROW_MAX_BASE = 4.5  # mm
_DIM_ARROW_MAX_BASE = 2.0  # mm; larger arrowheads indicate cutting planes
_EXTENSION_MAX_GAP = 8.0  # mm; gaps occur where extension lines cross dimension lines


@dataclass(slots=True)
class ArrowHead:
    tip: Point
    direction_deg: float  # Axis from base to tip, modulo 180 degrees
    width_mm: float = 0.0  # Line width of the base stroke


def classify(strokes: list[Stroke]) -> list[ArrowHead]:
    """Set the kind of each stroke. Return the detected arrowheads."""
    grid = Grid()
    for s in strokes:
        grid.insert(s.id, expand(s.bbox(), _TOUCH))

    # A cutting plane is thicker than the contour lines of the drawing.
    # Some templates draw part contours with 0.5 mm; those lines are contour candidates.
    cutting_width = max(_CUTTING_PLANE_WIDTH, _contour_width(strokes, grid) + _CUTTING_PLANE_MARGIN)
    for s in strokes:
        if s.width_mm >= cutting_width:
            s.kind = Kind.CUTTING_PLANE

    arrows = _find_arrows(strokes, grid)
    _find_dimension_lines(strokes, grid, arrows)
    _find_extension_lines(strokes, grid, arrows)
    _find_hatching(strokes, grid)
    _find_dashed(strokes)
    _find_center_marks(strokes)
    _extend_centerlines(strokes)
    for s in strokes:
        if s.kind is Kind.UNCLEAR:
            s.kind = Kind.CONTOUR
    return arrows


def _open(s: Stroke) -> bool:
    return s.kind is Kind.UNCLEAR


def _lines(strokes: list[Stroke]) -> list[Stroke]:
    return [s for s in strokes if isinstance(s.geom, Line)]


def _near(grid: Grid, strokes: list[Stroke], p: Point) -> list[Stroke]:
    return [strokes[i] for i in grid.query((p[0], p[1], p[0], p[1]))]


def _same(p: Point, q: Point) -> bool:
    return math.dist(p, q) < _TOUCH


def _in_triangle(p: Point, a: Point, b: Point, c: Point) -> bool:
    """Return whether a point is inside the triangle or within _TOUCH of an edge."""

    def side(p1: Point, p2: Point, p3: Point) -> float:
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1, d2, d3 = side(p, a, b), side(p, b, c), side(p, c, a)
    if not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0)):
        return True
    return min(point_segment_distance(p, u, v)[0] for u, v in ((a, b), (b, c), (c, a))) < _TOUCH


def _same_path(a: Stroke, b: Stroke) -> bool:
    """Accept the same PDF path or an immediately adjacent path.
    NX can divide one arrowhead between two consecutive paths."""
    return abs(a.path_id - b.path_id) <= 1


def _find_arrows(strokes: list[Stroke], grid: Grid) -> list[ArrowHead]:
    arrows: list[ArrowHead] = []
    for base in _lines(strokes):
        g = base.geom
        if not _open(base) or g.length > _ARROW_MAX_BASE:
            continue
        # Find two legs that connect the base endpoints to the same tip.
        legs0 = [s for s in _near(grid, strokes, g.p0) if s is not base and isinstance(s.geom, Line)
                 and _same_path(s, base) and _open(s) and any(_same(e, g.p0) for e in s.geom.endpoints())]
        legs1 = [s for s in _near(grid, strokes, g.p1) if s is not base and isinstance(s.geom, Line)
                 and _same_path(s, base) and _open(s) and any(_same(e, g.p1) for e in s.geom.endpoints())]
        found = None
        for l0 in legs0:
            far0 = l0.geom.p1 if _same(l0.geom.p0, g.p0) else l0.geom.p0
            for l1 in legs1:
                far1 = l1.geom.p1 if _same(l1.geom.p0, g.p1) else l1.geom.p0
                # Require equal leg lengths and a shorter base.
                if l0 is not l1 and _same_path(l0, l1) and _same(far0, far1) and g.length < l0.geom.length <= _ARROW_MAX_SIDE \
                        and abs(l0.geom.length - l1.geom.length) < 0.05 * l0.geom.length:
                    found = (l0, l1, far0)
                    break
            if found:
                break
        if not found:
            continue
        l0, l1, tip = found
        kind = Kind.ARROW if g.length <= _DIM_ARROW_MAX_BASE else Kind.CUTTING_PLANE
        tri = (g.p0, g.p1, tip)
        x0, y0 = min(p[0] for p in tri), min(p[1] for p in tri)
        x1, y1 = max(p[0] for p in tri), max(p[1] for p in tri)
        for i in grid.query((x0, y0, x1, y1)):
            s = strokes[i]
            if _same_path(s, base) and isinstance(s.geom, Line) and _open(s) and all(
                _in_triangle(e, *tri) for e in s.geom.endpoints()
            ):
                s.kind = kind
        mid = ((g.p0[0] + g.p1[0]) / 2, (g.p0[1] + g.p1[1]) / 2)
        direction = math.degrees(math.atan2(tip[1] - mid[1], tip[0] - mid[0])) % 180.0
        if kind is Kind.ARROW:
            arrows.append(ArrowHead(tip, direction, base.width_mm))
        else:
            _mark_section_marker(strokes, grid, tip, direction)
    return arrows


def _mark_section_marker(strokes: list[Stroke], grid: Grid, tip: Point, direction: float) -> None:
    """Mark the section arrow shaft and the short cutting-plane bar at its end."""
    for shaft in _near(grid, strokes, tip):
        g = shaft.geom
        if not (_open(shaft) and isinstance(g, Line) and angle_diff(g.angle, direction) < 2.0
                and point_segment_distance(tip, g.p0, g.p1)[0] < _TOUCH):
            continue
        shaft.kind = Kind.CUTTING_PLANE
        for e in g.endpoints():
            for bar in _near(grid, strokes, e):
                if _open(bar) and isinstance(bar.geom, Line) and angle_diff(bar.geom.angle, direction) > 60.0 \
                        and point_segment_distance(e, bar.geom.p0, bar.geom.p1)[0] < _TOUCH:
                    bar.kind = Kind.CUTTING_PLANE
                    for piece in _collinear_continuations(bar, strokes, grid, max_gap=2.0):
                        piece.kind = Kind.CUTTING_PLANE


def _collinear_continuations(s: Stroke, strokes: list[Stroke], grid: Grid, max_gap: float) -> list[Stroke]:
    """Find unclassified lines on the same carrier within max_gap of an endpoint."""
    g = s.geom
    ang, off = g.angle, _offset(g, g.angle)
    out = []
    for i in grid.query(expand(s.bbox(), max_gap)):
        t = strokes[i]
        if t is s or not _open(t) or not isinstance(t.geom, Line) or abs(t.width_mm - s.width_mm) > 1e-3:
            continue
        if angle_diff(t.geom.angle, ang) > 0.5 or abs(_offset(t.geom, ang) - off) > 0.02:
            continue
        gap = min(math.dist(a, b) for a in g.endpoints() for b in t.geom.endpoints())
        if gap <= max_gap:
            out.append(t)
    return out


def _arc_tangent_deg(arc: Arc, p: Point) -> float:
    radial = math.degrees(math.atan2(p[1] - arc.center[1], p[0] - arc.center[0]))
    return (radial + 90.0) % 180.0


def _find_dimension_lines(strokes: list[Stroke], grid: Grid, arrows: list[ArrowHead]) -> None:
    for arrow in arrows:
        for s in _near(grid, strokes, arrow.tip):
            if not _open(s):
                continue
            g = s.geom
            if isinstance(g, Line):
                hit = point_segment_distance(arrow.tip, g.p0, g.p1)[0] < _TOUCH
                aligned = angle_diff(g.angle, arrow.direction_deg) < 2.0
            else:
                hit = abs(math.dist(arrow.tip, g.center) - g.radius) < _TOUCH
                aligned = angle_diff(_arc_tangent_deg(g, arrow.tip), arrow.direction_deg) < 5.0
            if hit and aligned:
                s.kind = Kind.DIMENSION

    # Extend collinear dimension-line pieces across shared endpoints.
    changed = True
    while changed:
        changed = False
        for s in strokes:
            if s.kind is not Kind.DIMENSION or not isinstance(s.geom, Line):
                continue
            for e in s.geom.endpoints():
                for t in _near(grid, strokes, e):
                    if _open(t) and isinstance(t.geom, Line) and angle_diff(t.geom.angle, s.geom.angle) < 1.0 \
                            and any(_same(e, f) for f in t.geom.endpoints()):
                        t.kind = Kind.DIMENSION
                        changed = True


def _is_free_end(p: Point, owner: Stroke, strokes: list[Stroke], grid: Grid) -> bool:
    """Return whether no other body stroke touches this point."""
    for t in _near(grid, strokes, p):
        if t is owner or t.kind in (Kind.DIMENSION, Kind.ARROW, Kind.EXTENSION, Kind.CUTTING_PLANE):
            continue
        g = t.geom
        if isinstance(g, Line):
            if point_segment_distance(p, g.p0, g.p1)[0] < _TOUCH:
                return False
        elif abs(math.dist(p, g.center) - g.radius) < _TOUCH:
            return False
    return True


def _find_extension_lines(strokes: list[Stroke], grid: Grid, arrows: list[ArrowHead]) -> None:
    anchors: list[tuple[Point, float]] = [(a.tip, a.direction_deg) for a in arrows]
    for s in strokes:
        if s.kind is Kind.DIMENSION and isinstance(s.geom, Line):
            anchors += [(e, s.geom.angle) for e in s.geom.endpoints()]

    for p, dim_dir in anchors:
        for s in _near(grid, strokes, p):
            if not _open(s) or not isinstance(s.geom, Line):
                continue
            g = s.geom
            dist, t = point_segment_distance(p, g.p0, g.p1)
            if dist > _TOUCH or angle_diff(g.angle, dim_dir) < 30.0:
                continue
            # The nearer endpoint must be free, 0.3 to 6 mm beyond the anchor.
            end = g.p0 if t < 0.5 else g.p1
            overshoot = math.dist(p, end)
            if 0.3 <= overshoot <= 6.0 and _is_free_end(end, s, strokes, grid):
                s.kind = Kind.EXTENSION
                _extend_across_gaps(s, strokes, grid)


def _extend_across_gaps(s: Stroke, strokes: list[Stroke], grid: Grid) -> None:
    """Continue extension lines across gaps at other dimension lines.
    A gap before a body contour remains a boundary."""
    todo = [s]
    while todo:
        cur = todo.pop()
        for piece in _collinear_continuations(cur, strokes, grid, _EXTENSION_MAX_GAP):
            a, b = min(((a, b) for a in cur.geom.endpoints() for b in piece.geom.endpoints()),
                       key=lambda ab: math.dist(*ab))
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            crossed = any(
                t.kind is Kind.DIMENSION and isinstance(t.geom, Line)
                and point_segment_distance(mid, t.geom.p0, t.geom.p1)[0] < math.dist(a, b) / 2 + _TOUCH
                for t in _near(grid, strokes, mid)
            )
            if crossed:
                piece.kind = Kind.EXTENSION
                todo.append(piece)


def _offset(g: Line, angle_deg: float) -> float:
    """Return the perpendicular distance of the carrier line from the origin."""
    a = math.radians(angle_deg)
    return -g.p0[0] * math.sin(a) + g.p0[1] * math.cos(a)


def _along(p: Point, angle_deg: float) -> float:
    a = math.radians(angle_deg)
    return p[0] * math.cos(a) + p[1] * math.sin(a)


def _find_hatching(strokes: list[Stroke], grid: Grid) -> None:
    """Find parallel neighbors at equal distances on both sides.
    Also accept two neighbors at distances s and 2s."""
    cands = [s for s in _lines(strokes) if _open(s) and s.geom.length > 0.5]
    by_id = {s.id: s for s in cands}
    hatch: set[int] = set()
    for s in cands:
        g = s.geom
        ang = g.angle
        off = _offset(g, ang)
        lo, hi = sorted((_along(g.p0, ang), _along(g.p1, ang)))
        spacings: list[float] = []
        for i in grid.query(expand(s.bbox(), 5.0)):
            t = by_id.get(i)
            if t is None or t is s or angle_diff(t.geom.angle, ang) > 0.5 or t.width_mm != s.width_mm:
                continue
            tlo, thi = sorted((_along(t.geom.p0, ang), _along(t.geom.p1, ang)))
            if thi < lo or tlo > hi:  # Require overlap along the line direction.
                continue
            d = _offset(t.geom, ang) - off
            if 0.3 < abs(d) <= 5.0:
                spacings.append(d)
        for d in spacings:
            if any(abs(e + d) < 0.1 * abs(d) or abs(e - 2 * d) < 0.1 * abs(d) for e in spacings):
                hatch.add(s.id)
                break
    for i in hatch:
        by_id[i].kind = Kind.HATCH


def _dash_kind(pieces: list[float]) -> Kind:
    """Alternate long and short strokes indicate a centerline.
    Equal dash lengths indicate a hidden line."""
    if len(pieces) >= 3 and max(pieces) > 2.5 * min(pieces):
        return Kind.CENTERLINE
    return Kind.HIDDEN


def _find_dashed(strokes: list[Stroke]) -> None:
    # Group collinear segments with gaps.
    carriers: dict[tuple, list[Stroke]] = defaultdict(list)
    for s in _lines(strokes):
        if _open(s):
            ang = round(s.geom.angle * 2) / 2 % 180.0
            carriers[(ang, round(_offset(s.geom, ang) * 10), round(s.width_mm, 3))].append(s)
    for (ang, _, _), group in carriers.items():
        if len(group) < 3:
            continue
        spans = sorted(
            ((sorted((_along(s.geom.p0, ang), _along(s.geom.p1, ang))), s) for s in group), key=lambda x: x[0]
        )
        # Form runs with gaps up to 4 mm. Overlap is permitted.
        run: list[tuple[list[float], Stroke]] = [spans[0]]
        run_end, gaps = spans[0][0][1], 0
        for item in spans[1:] + [None]:
            if item is not None and item[0][0] - run_end <= 4.0:
                gaps += item[0][0] - run_end >= 0.3
                run.append(item)
                run_end = max(run_end, item[0][1])
                continue
            if len(run) >= 3 and gaps >= 2:
                kind = _dash_kind([hi - lo for (lo, hi), _ in run])
                for _, s in run:
                    s.kind = kind
            if item is not None:
                run, run_end, gaps = [item], item[0][1], 0

    # Group arc segments with the same center and radius.
    circles: dict[tuple, list[Stroke]] = defaultdict(list)
    for s in strokes:
        if isinstance(s.geom, Arc) and _open(s) and not s.geom.is_circle:
            g = s.geom
            circles[(round(g.center[0], 1), round(g.center[1], 1), round(g.radius, 1), round(s.width_mm, 3))].append(s)
    for group in circles.values():
        if len(group) >= 3:
            kind = _dash_kind([s.geom.length for s in group])
            for s in group:
                s.kind = kind


def _find_center_marks(strokes: list[Stroke]) -> None:
    """Classify thin lines through circle centers as center marks."""
    contour_width = _dominant_width(strokes)
    centers = [s.geom.center for s in strokes if isinstance(s.geom, Arc)]
    for s in _lines(strokes):
        if not _open(s) or s.width_mm >= contour_width:
            continue
        g = s.geom
        for c in centers:
            d, t = point_segment_distance(c, g.p0, g.p1)
            if d < _TOUCH and 0.05 < t < 0.95:
                s.kind = Kind.CENTERLINE
                break


_CENTERLINE_REACH = 30.0  # mm along the carrier to the nearest centerline piece
_DASH_LIMIT = 1.2  # A continuation is at most this factor longer than the longest nearby centerline piece.
_MAX_DASH = 25.0  # mm: upper limit for one centerline dash


def _extend_centerlines(strokes: list[Stroke]) -> None:
    """Classify a free dash on the carrier of a nearby centerline as a centerline piece.
    The last dash of a centerline can stand alone, for example where filled dashes end the run.
    A part edge touches or crosses other strokes, or is longer than the dashes; it stays a contour candidate."""
    # A separate index with conservative arc boxes, so that contact checks find tangent arcs.
    grid = Grid()
    for s in strokes:
        grid.insert(s.id, expand(index_box(s), _TOUCH))
    carriers: dict[tuple, list[tuple[float, float]]] = defaultdict(list)
    for s in _lines(strokes):
        if s.kind is Kind.CENTERLINE:
            ang = round(s.geom.angle * 2) / 2 % 180.0
            span = sorted((_along(s.geom.p0, ang), _along(s.geom.p1, ang)))
            carriers[(ang, round(_offset(s.geom, ang) * 10), round(s.width_mm, 3))].append(span)
    if not carriers:
        return
    for s in _lines(strokes):
        if not _open(s):
            continue
        ang = round(s.geom.angle * 2) / 2 % 180.0
        spans = carriers.get((ang, round(_offset(s.geom, ang) * 10), round(s.width_mm, 3)), [])
        lo, hi = sorted((_along(s.geom.p0, ang), _along(s.geom.p1, ang)))
        # Only the nearby run defines the dash length. A distant center mark on the same carrier does not.
        nearby = [b - a for a, b in spans if max(a - hi, lo - b, 0.0) <= _CENTERLINE_REACH]
        if not nearby or s.geom.length > min(_DASH_LIMIT * max(nearby), _MAX_DASH) or contacts(s, strokes, grid):
            continue
        s.kind = Kind.CENTERLINE


_CONTOUR_MIN_WIDTH = 0.3  # mm: thinner lines are dimension, hatch, or center lines


_THICK_TO_THIN = 1.25  # ISO 128 line groups use thick lines twice as wide as thin lines. The margin accepts rounded widths.
_MIN_ARROWHEADS = 4  # Two dimensions. Fewer arrow-like triangles do not identify the thin width.


def _arrow_width(strokes: list[Stroke], grid: Grid) -> float:
    """Return the line width of most arrowhead strokes, or 0 if there is none.
    Arrowheads are thin lines in each ISO 128 line group. A width counts only with several arrowheads, so that
    one filled arrow-like triangle in contour width does not decide. The trial run does not change the stroke kinds."""
    kinds = [s.kind for s in strokes]
    arrows = _find_arrows(strokes, grid)
    heads: dict[float, int] = defaultdict(int)
    for arrow in arrows:
        heads[round(arrow.width_mm, 3)] += 1
    count: dict[float, int] = defaultdict(int)
    for s, kind in zip(strokes, kinds):
        if s.kind is Kind.ARROW and heads[round(s.width_mm, 3)] >= _MIN_ARROWHEADS:
            count[round(s.width_mm, 3)] += 1
        s.kind = kind
    return max(count, key=count.__getitem__) if count else 0.0


def _contour_width(strokes: list[Stroke], grid: Grid | None = None) -> float:
    """Return the thick line width with the greatest total length. Part contours use this width.
    Thin lines are excluded, because hatching and dimensions can have a greater total length.
    In thicker line groups (for example 0.35 mm thin and 0.5 mm thick), the thin width is above 0.3 mm.
    The arrowhead width then identifies the thin lines."""
    minimum = _CONTOUR_MIN_WIDTH
    if grid is not None:
        minimum = max(minimum, _THICK_TO_THIN * _arrow_width(strokes, grid))
    total: dict[float, float] = defaultdict(float)
    for s in strokes:
        if s.width_mm >= minimum:
            total[round(s.width_mm, 3)] += s.geom.length
    if not total:
        return _contour_width(strokes) if grid is not None else 0.0
    return max(total, key=total.__getitem__)


def _dominant_width(strokes: list[Stroke]) -> float:
    """Return the width with the greatest total length among unclassified strokes."""
    total: dict[float, float] = defaultdict(float)
    for s in strokes:
        if _open(s):
            total[round(s.width_mm, 3)] += s.geom.length
    return max(total, key=total.__getitem__) if total else 0.0
