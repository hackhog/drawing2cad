"""Find annotation strokes that are not part geometry.

Run this pass after stroke classification and text reading, and before view grouping.
It changes only contour candidates and uses text positions as evidence:

1. Table separators: free parallel lines with the same span and stacked text between them.
2. Edge condition symbols (ISO 13715): a small free right-angle corner next to a signed value.
3. Parentheses drawn as vectors: open, curved chains of short lines on both sides of a text block.

A free stroke has no contact with other strokes at its ends, along its length, or at a crossing.
The rules do not depend on the page rotation.
"""

from __future__ import annotations

import math

from .contacts import TOUCH, contacts
from .geometry import Grid, UnionFind, expand, overlaps
from .model import Kind, Line, Point, Stroke, TextBlock

_SPAN_TOLERANCE = 0.1  # mm
_TABLE_MIN_GAP = 4.0  # mm between table separators
_TABLE_MIN_ROWS = 3  # stacked text rows in each column between two separators
_SYMBOL_LEG = (2.0, 8.0)  # mm: leg length of an edge condition symbol
_SYMBOL_TEXT_DISTANCE = 8.0  # mm
_SIGNS = ("+", "-", "−", "±")
_BRACKET_SEGMENT = 1.5  # mm: maximum segment length in a drawn parenthesis
_BRACKET_HEIGHT = (2.0, 6.0)  # mm: chord length of a drawn parenthesis
_BRACKET_BULGE = (0.08, 0.35)  # bulge depth divided by chord length
_BRACKET_GAP = 2.0  # mm between a parenthesis and its text


def mark_annotations(strokes: list[Stroke], texts: list[TextBlock]) -> None:
    """Set annotation strokes to Kind.ANNOTATION. Wrap text that drawn parentheses enclose.
    Stroke IDs must equal their list positions."""
    lines = [s for s in strokes if s.kind is Kind.CONTOUR and isinstance(s.geom, Line)]
    if not lines:
        return
    grid = Grid()
    for s in strokes:
        grid.insert(s.id, expand(s.bbox(), TOUCH))
    touching = {s.id: contacts(s, strokes, grid) for s in lines}
    _mark_table_separators([s for s in lines if not touching[s.id]], texts)
    _mark_edge_symbols(lines, texts, strokes, touching)
    _mark_parentheses(lines, texts, touching)


def _axis(g: Line) -> int | None:
    """Return 0 for a horizontal line, 1 for a vertical line, and None otherwise."""
    if math.isclose(g.p0[1], g.p1[1], abs_tol=0.02):
        return 0
    if math.isclose(g.p0[0], g.p1[0], abs_tol=0.02):
        return 1
    return None


def _inside(box: tuple[float, float, float, float], outer: tuple[float, float, float, float]) -> bool:
    return box[0] >= outer[0] - TOUCH and box[1] >= outer[1] - TOUCH and box[2] <= outer[2] + TOUCH and box[3] <= outer[3] + TOUCH


def _mark_table_separators(lines: list[Stroke], texts: list[TextBlock]) -> None:
    """Mark free parallel separators with the same span when stacked text fills the columns between them."""
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
            rows = {round(t.bbox[1] if axis == 1 else t.bbox[0]) for t in column}
            if len(rows) >= _TABLE_MIN_ROWS:
                marked.update((a.id, b.id))
        for s in group:
            if s.id in marked:
                s.kind = Kind.ANNOTATION


def _mark_edge_symbols(lines: list[Stroke], texts: list[TextBlock], strokes: list[Stroke],
                       touching: dict[int, set[int]]) -> None:
    signed = [t for t in texts if t.text.strip().startswith(_SIGNS)]
    if not signed:
        return
    for a in lines:
        if a.kind is not Kind.CONTOUR or not _SYMBOL_LEG[0] <= a.geom.length <= _SYMBOL_LEG[1]:
            continue
        if len(touching[a.id]) != 1:
            continue
        b = strokes[next(iter(touching[a.id]))]
        if b.kind is not Kind.CONTOUR or not isinstance(b.geom, Line) or touching.get(b.id) != {a.id}:
            continue
        if abs(a.geom.length - b.geom.length) > 0.1 * a.geom.length or abs(abs(a.geom.angle - b.geom.angle) - 90.0) > 2.0:
            continue
        # The legs meet at a shared end, not at an interior point.
        if not any(math.dist(p, q) < TOUCH for p in a.geom.endpoints() for q in b.geom.endpoints()):
            continue
        box = (min(a.bbox()[0], b.bbox()[0]), min(a.bbox()[1], b.bbox()[1]),
               max(a.bbox()[2], b.bbox()[2]), max(a.bbox()[3], b.bbox()[3]))
        if any(overlaps(expand(box, _SYMBOL_TEXT_DISTANCE), t.bbox) for t in signed):
            a.kind = b.kind = Kind.ANNOTATION


def _chains(lines: list[Stroke], touching: dict[int, set[int]]) -> list[list[Stroke]]:
    """Group short contour lines that touch only each other."""
    short = {s.id: s for s in lines if s.kind is Kind.CONTOUR and s.geom.length <= _BRACKET_SEGMENT}
    ids = list(short)
    index = {i: n for n, i in enumerate(ids)}
    uf = UnionFind(len(ids))
    for i in ids:
        for j in touching[i]:
            if j in short:
                uf.union(index[i], index[j])
    groups = [[short[ids[m]] for m in members] for members in uf.groups(range(len(ids))).values()]
    # A chain touches no stroke outside itself.
    return [g for g in groups if all(touching[s.id] <= {t.id for t in g} for s in g)]


def _key(p: Point) -> tuple[int, int]:
    return round(p[0] / TOUCH), round(p[1] / TOUCH)


def _open_path(chain: list[Stroke]) -> list[Point] | None:
    """Return the ordered points of an open, non-branching chain, or None."""
    adjacency: dict[tuple[int, int], list[tuple[tuple[int, int], Point]]] = {}
    points: dict[tuple[int, int], Point] = {}
    for s in chain:
        a, b = s.geom.p0, s.geom.p1
        ka, kb = _key(a), _key(b)
        points.setdefault(ka, a)
        points.setdefault(kb, b)
        adjacency.setdefault(ka, []).append((kb, b))
        adjacency.setdefault(kb, []).append((ka, a))
    ends = [k for k, n in adjacency.items() if len(n) == 1]
    if len(ends) != 2 or any(len(n) > 2 for n in adjacency.values()):
        return None  # Closed outline, branch, or rounding mismatch.
    path, previous, current = [points[ends[0]]], None, ends[0]
    while True:
        following = [k for k, _ in adjacency[current] if k != previous]
        if not following:
            break
        previous, current = current, following[0]
        path.append(points[current])
    return path if len(path) == len(chain) + 1 else None


def _bracket(chain: list[Stroke]) -> tuple[tuple[float, float, float, float], int, int] | None:
    """Return (bbox, long axis, bulge side) for an open, consistently curved chain.
    The bulge side is -1 or +1 along the short axis."""
    if not 3 <= len(chain) <= 8:
        return None
    path = _open_path(chain)
    if path is None:
        return None
    (ax, ay), (bx, by) = path[0], path[-1]
    chord = math.dist(path[0], path[-1])
    if not _BRACKET_HEIGHT[0] <= chord <= _BRACKET_HEIGHT[1]:
        return None
    # Signed distances of the interior points from the chord: one side only, and a moderate depth.
    offsets = [((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / chord for px, py in path[1:-1]]
    if not (all(o > 0 for o in offsets) or all(o < 0 for o in offsets)):
        return None
    depth = max(abs(o) for o in offsets)
    if not _BRACKET_BULGE[0] <= depth / chord <= _BRACKET_BULGE[1]:
        return None
    long_axis = 1 if abs(by - ay) >= abs(bx - ax) else 0
    if abs(by - ay if long_axis else bx - ax) < 0.9 * chord:
        return None  # The chord must follow a sheet axis.
    box = (min(p[0] for p in path), min(p[1] for p in path), max(p[0] for p in path), max(p[1] for p in path))
    # The bulge side on the short axis: compare the deepest point with the chord.
    deepest = max(path[1:-1], key=lambda p: abs(((bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax))))
    short_coordinate = deepest[0] - (ax + bx) / 2 if long_axis else deepest[1] - (ay + by) / 2
    return box, long_axis, (1 if short_coordinate > 0 else -1)


def _mark_parentheses(lines: list[Stroke], texts: list[TextBlock], touching: dict[int, set[int]]) -> None:
    brackets = [(chain, *found) for chain in _chains(lines, touching) if (found := _bracket(chain))]
    for text in texts:
        tx0, ty0, tx1, ty1 = text.bbox
        before: list[list[Stroke]] = []
        after: list[list[Stroke]] = []
        for chain, (x0, y0, x1, y1), axis, bulge in brackets:
            lo, hi, tlo, thi = (y0, y1, ty0, ty1) if axis == 1 else (x0, x1, tx0, tx1)
            if min(hi, thi) - max(lo, tlo) < 0.5 * min(hi - lo, thi - tlo):
                continue
            near_end, far_end, text_start, text_end = (x1, x0, tx0, tx1) if axis == 1 else (y1, y0, ty0, ty1)
            # An opening parenthesis bulges away from the text, toward the lower coordinate.
            if bulge < 0 and 0 <= text_start - near_end + TOUCH <= _BRACKET_GAP:
                before.append(chain)
            elif bulge > 0 and 0 <= far_end - text_end + TOUCH <= _BRACKET_GAP:
                after.append(chain)
        if not before or not after:
            continue
        for chain in (before[0], after[0]):
            for s in chain:
                s.kind = Kind.ANNOTATION
        # A dimension in parentheses is an auxiliary dimension. Keep that meaning in the text.
        if not text.text.startswith("("):
            text.text = "(" + text.text + ")"


__all__ = ["mark_annotations"]
