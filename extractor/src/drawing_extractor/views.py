"""Gruppiert Körpergeometrie zu Ansichten."""

from __future__ import annotations

import math

from .geometry import BBox, Grid, UnionFind, contains, expand, overlaps, point_segment_distance, union
from .model import Kind, Line, Point, Stroke, View

_BODY = (Kind.CONTOUR, Kind.HATCH, Kind.HIDDEN)
_ATTACHED = (Kind.CENTERLINE,)
_TOUCH = 0.15  # mm
_MIN_VIEW_LENGTH = 20.0  # mm Gesamtlänge; kleinere Gruppen sind Beiwerk (Hinweislinien, Markierungen)
_MIN_VIEW_STROKES = 3
_MIN_VIEW_SIZE = 5.0  # mm; kleinere Gruppen sind z. B. nicht erkannte Pfeile


def _touches(p: Point, s: Stroke) -> bool:
    g = s.geom
    if isinstance(g, Line):
        return point_segment_distance(p, g.p0, g.p1)[0] < _TOUCH
    return abs(math.dist(p, g.center) - g.radius) < _TOUCH


def _mostly_inside(a: BBox, b: BBox) -> bool:
    """Mindestens die Hälfte der kleineren Box liegt in der größeren."""
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix < 0 or iy < 0:
        return False
    # Ausdehnung mindestens 1 mm, damit waagrechte/senkrechte Einzellinien Fläche haben
    def area(x: BBox) -> float:
        return max(x[2] - x[0], 1.0) * max(x[3] - x[1], 1.0)

    return max(ix, 1.0) * max(iy, 1.0) >= 0.5 * min(area(a), area(b))


def group_views(strokes: list[Stroke], raster_bbox: BBox | None) -> list[View]:
    body = [s for s in strokes if s.kind in _BODY]
    idx = {s.id: n for n, s in enumerate(body)}
    grid = Grid()
    for s in body:
        grid.insert(s.id, expand(s.bbox(), _TOUCH))
    by_id = {s.id: s for s in body}

    uf = UnionFind(len(body))
    for s in body:
        for e in s.geom.endpoints():
            for j in grid.query((e[0], e[1], e[0], e[1])):
                t = by_id.get(j)
                if t is not None and t is not s and _touches(e, t):
                    uf.union(idx[s.id], idx[t.id])

    clusters = [[body[i] for i in members] for members in uf.groups(range(len(body))).values()]
    boxes = [union(s.bbox() for s in c) for c in clusters]

    # Gruppen zusammenführen, die überwiegend ineinander liegen (Bohrungen in Platten,
    # Schraffur in Schnitten). Nur Randberührung reicht nicht, sonst kleben Nachbaransichten.
    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                if _mostly_inside(boxes[i], boxes[j]):
                    clusters[i] += clusters.pop(j)
                    boxes[i] = union([boxes[i], boxes.pop(j)])
                    merged = True
                    break
            if merged:
                break

    views: list[View] = []
    leftovers: list[Stroke] = []
    for c, box in sorted(zip(clusters, boxes), key=lambda cb: (round(cb[1][1] / 50), cb[1][0])):
        too_small = max(box[2] - box[0], box[3] - box[1]) < _MIN_VIEW_SIZE
        if too_small or sum(s.geom.length for s in c) < _MIN_VIEW_LENGTH or len(c) < _MIN_VIEW_STROKES:
            leftovers += c
            continue
        is_iso = raster_bbox is not None and overlaps(box, raster_bbox)
        views.append(View(len(views) + 1, box, is_iso, sorted(s.id for s in c)))

    for s in leftovers:
        s.kind = Kind.UNCLEAR

    # Mittellinien der Ansicht zuordnen, in deren (erweiterter) Box sie liegen
    for s in strokes:
        if s.kind not in _ATTACHED:
            continue
        x0, y0, x1, y1 = s.bbox()
        mid = ((x0 + x1) / 2, (y0 + y1) / 2)
        for v in views:
            if contains(expand(v.bbox, 10.0), (mid[0], mid[1], mid[0], mid[1])):
                v.stroke_ids.append(s.id)
                break
    for v in views:
        v.stroke_ids.sort()
    return views


__all__ = ["group_views"]
