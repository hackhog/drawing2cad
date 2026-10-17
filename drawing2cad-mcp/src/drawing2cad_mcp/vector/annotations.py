"""Find annotation strokes that are not part geometry.

Run this pass after stroke classification and text reading, and before view grouping.
It changes only contour candidates and uses text positions as evidence:

1. Table separators: parallel lines with the same span and text blocks between them.
2. Edge condition symbols (ISO 13715): a small isolated right-angle corner next to a signed value.
3. Parentheses drawn as vectors: short line chains on both sides of a text block.

The rules do not depend on the page rotation.
"""

from __future__ import annotations

import math

from .geometry import Grid, UnionFind, expand, overlaps, point_segment_distance
from .model import Kind, Line, Point, Stroke, TextBlock

_TOUCH = 0.06  # mm: endpoint contact tolerance, as in classify
_SPAN_TOLERANCE = 0.1  # mm
_TABLE_MIN_GAP = 4.0  # mm between table separators
_TABLE_MIN_TEXTS = 3  # stacked text blocks in each column between two separators
_SYMBOL_LEG = (2.0, 8.0)  # mm: leg length of an edge condition symbol
_SYMBOL_TEXT_DISTANCE = 8.0  # mm
_SIGNS = ("+", "-", "−", "±")
_BRACKET_SEGMENT = 1.5  # mm: maximum segment length in a drawn parenthesis
_BRACKET_HEIGHT = (2.0, 6.0)  # mm
_BRACKET_GAP = 2.0  # mm between a parenthesis and its text


def mark_annotations(strokes: list[Stroke], texts: list[TextBlock]) -> None:
    """Set annotation strokes to Kind.ANNOTATION. Wrap text that drawn parentheses enclose."""
    lines = [s for s in strokes if s.kind is Kind.CONTOUR and isinstance(s.geom, Line)]
    if not lines:
        return
    grid = Grid()
    for s in strokes:
        grid.insert(s.id, expand(s.bbox(), _TOUCH))
    by_id = {s.id: s for s in strokes}
    _mark_table_separators([s for s in lines if not _touching(s, strokes, grid, by_id)], texts)
    _mark_edge_symbols(lines, texts, strokes, grid, by_id)
    _mark_parentheses(lines, texts, strokes, grid, by_id)


def _axis(g: Line) -> int | None:
    """Return 0 for a horizontal line, 1 for a vertical line, and None otherwise."""
    if math.isclose(g.p0[1], g.p1[1], abs_tol=0.02):
        return 0
    if math.isclose(g.p0[0], g.p1[0], abs_tol=0.02):
        return 1
    return None


def _inside(box: tuple[float, float, float, float], outer: tuple[float, float, float, float]) -> bool:
    return box[0] >= outer[0] - _TOUCH and box[1] >= outer[1] - _TOUCH and box[2] <= outer[2] + _TOUCH and box[3] <= outer[3] + _TOUCH


def _mark_table_separators(lines: list[Stroke], texts: list[TextBlock]) -> None:
    """Mark free parallel separators with the same span when stacked text fills the columns between them.
    Part edges touch other strokes, so only free lines are candidates."""
    groups: dict[tuple, list[Stroke]] = {}
    for s in lines:
        axis = _axis(s.geom)
        if axis is None:
            continue
        x0, y0, x1, y1 = s.bbox()
        start, end = (y0, y1) if axis == 1 else (x0, x1)
        key = (axis, round(start / _SPAN_TOLERANCE), round(end / _SPAN_TOLERANCE), round(s.width_mm, 3))
        groups.setdefault(key, []).append(s)
    for (axis, *_), group in groups.items():
        if len(group) < 2:
            continue
        # Positions across the separators, in ascending order.
        group.sort(key=lambda s: s.geom.p0[0] if axis == 1 else s.geom.p0[1])
        marked: set[int] = set()
        for a, b in zip(group, group[1:]):
            ax0, ay0, ax1, ay1 = a.bbox()
            bx0, by0, bx1, by1 = b.bbox()
            band = (ax1, ay0, bx0, by1) if axis == 1 else (ax0, ay1, bx1, by0)
            gap = band[2] - band[0] if axis == 1 else band[3] - band[1]
            if gap < _TABLE_MIN_GAP:
                continue
            column = [t for t in texts if _inside(t.bbox, band)]
            # Rows stack along the separators: count distinct text positions on that axis.
            rows = {round((t.bbox[1] if axis == 1 else t.bbox[0]) / 1.0) for t in column}
            if len(rows) >= _TABLE_MIN_TEXTS:
                marked.update((a.id, b.id))
        for s in group:
            if s.id in marked:
                s.kind = Kind.ANNOTATION


def _touching(s: Stroke, strokes: list[Stroke], grid: Grid, by_id: dict[int, Stroke]) -> set[int]:
    """Return the IDs of other strokes that touch an endpoint of this line."""
    out: set[int] = set()
    for e in s.geom.endpoints():
        for i in grid.query((e[0], e[1], e[0], e[1])):
            t = by_id[i]
            if t is s:
                continue
            g = t.geom
            if isinstance(g, Line):
                hit = point_segment_distance(e, g.p0, g.p1)[0] < _TOUCH
            else:
                hit = abs(math.dist(e, g.center) - g.radius) < _TOUCH
            if hit:
                out.add(t.id)
    return out


def _mark_edge_symbols(lines: list[Stroke], texts: list[TextBlock], strokes: list[Stroke], grid: Grid,
                       by_id: dict[int, Stroke]) -> None:
    signed = [t for t in texts if t.text.strip().startswith(_SIGNS)]
    if not signed:
        return
    for a in lines:
        if a.kind is not Kind.CONTOUR or not _SYMBOL_LEG[0] <= a.geom.length <= _SYMBOL_LEG[1]:
            continue
        touching = _touching(a, strokes, grid, by_id)
        if len(touching) != 1:
            continue
        b = by_id[next(iter(touching))]
        if b.kind is not Kind.CONTOUR or not isinstance(b.geom, Line) or _touching(b, strokes, grid, by_id) != {a.id}:
            continue
        if abs(a.geom.length - b.geom.length) > 0.1 * a.geom.length or abs(abs(a.geom.angle - b.geom.angle) - 90.0) > 2.0:
            continue
        corner = [p for p in a.geom.endpoints() if any(math.dist(p, q) < _TOUCH for q in b.geom.endpoints())]
        if not corner:
            continue
        reach = expand((min(a.bbox()[0], b.bbox()[0]), min(a.bbox()[1], b.bbox()[1]),
                        max(a.bbox()[2], b.bbox()[2]), max(a.bbox()[3], b.bbox()[3])), _SYMBOL_TEXT_DISTANCE)
        if any(overlaps(reach, t.bbox) for t in signed):
            a.kind = b.kind = Kind.ANNOTATION


def _chains(lines: list[Stroke]) -> list[list[Stroke]]:
    short = [s for s in lines if s.kind is Kind.CONTOUR and s.geom.length <= _BRACKET_SEGMENT]
    uf = UnionFind(len(short))
    for i, s in enumerate(short):
        for j in range(i + 1, len(short)):
            if any(math.dist(p, q) < _TOUCH for p in s.geom.endpoints() for q in short[j].geom.endpoints()):
                uf.union(i, j)
    return [[short[m] for m in members] for members in uf.groups(range(len(short))).values()]


def _bracket(chain: list[Stroke], strokes: list[Stroke], grid: Grid, by_id: dict[int, Stroke]) -> tuple | None:
    """Return (bbox, long axis) for an isolated, elongated chain of three or more segments."""
    if not 3 <= len(chain) <= 8:
        return None
    ids = {s.id for s in chain}
    if any(_touching(s, strokes, grid, by_id) - ids for s in chain):
        return None
    box = (min(s.bbox()[0] for s in chain), min(s.bbox()[1] for s in chain),
           max(s.bbox()[2] for s in chain), max(s.bbox()[3] for s in chain))
    w, h = box[2] - box[0], box[3] - box[1]
    long_axis = 1 if h >= w else 0
    length, depth = (h, w) if long_axis else (w, h)
    if not _BRACKET_HEIGHT[0] <= length <= _BRACKET_HEIGHT[1] or depth > 0.35 * length:
        return None
    return box, long_axis


def _mark_parentheses(lines: list[Stroke], texts: list[TextBlock], strokes: list[Stroke], grid: Grid,
                      by_id: dict[int, Stroke]) -> None:
    brackets = [(chain, *found) for chain in _chains(lines) if (found := _bracket(chain, strokes, grid, by_id))]
    for text in texts:
        tx0, ty0, tx1, ty1 = text.bbox
        sides: dict[int, list[list[Stroke]]] = {-1: [], 1: []}
        for chain, (x0, y0, x1, y1), axis in brackets:
            if axis == 1:
                overlap = min(y1, ty1) - max(y0, ty0)
                if overlap < 0.5 * min(y1 - y0, ty1 - ty0):
                    continue
                if 0 <= tx0 - x1 + _TOUCH <= _BRACKET_GAP:
                    sides[-1].append(chain)
                elif 0 <= x0 - tx1 + _TOUCH <= _BRACKET_GAP:
                    sides[1].append(chain)
            else:
                overlap = min(x1, tx1) - max(x0, tx0)
                if overlap < 0.5 * min(x1 - x0, tx1 - tx0):
                    continue
                if 0 <= ty0 - y1 + _TOUCH <= _BRACKET_GAP:
                    sides[-1].append(chain)
                elif 0 <= y0 - ty1 + _TOUCH <= _BRACKET_GAP:
                    sides[1].append(chain)
        if not sides[-1] or not sides[1]:
            continue
        for chain in sides[-1][:1] + sides[1][:1]:
            for s in chain:
                s.kind = Kind.ANNOTATION
        # A dimension in parentheses is an auxiliary dimension. Keep that meaning in the text.
        if not text.text.startswith("("):
            text.text = "(" + text.text + ")"


__all__ = ["mark_annotations"]
