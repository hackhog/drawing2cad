"""Geometrie-Hilfen: Kreis durch drei Punkte, Bögen zusammenfügen, räumlicher Index."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Iterator

from .model import Arc, Line, Point

BBox = tuple[float, float, float, float]


def circle_through(a: Point, b: Point, c: Point) -> tuple[Point, float] | None:
    """Mittelpunkt und Radius des Kreises durch drei Punkte, None bei Kollinearität."""
    (ax, ay), (bx, by), (cx, cy) = a, b, c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)) / d
    uy = ((ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)) / d
    r = math.dist((ux, uy), a)
    if r > 2000:  # praktisch gerade
        return None
    return (ux, uy), r


def _normalized(arc: Arc) -> Arc:
    """Bogen mit positivem Sweep und Startwinkel in [0, 360)."""
    if arc.sweep_deg < 0:
        return Arc(arc.center, arc.radius, (arc.start_deg + arc.sweep_deg) % 360.0, -arc.sweep_deg)
    return Arc(arc.center, arc.radius, arc.start_deg % 360.0, arc.sweep_deg)


def fit_arcs_into_circles(
    geoms: list[tuple[Line | Arc, float, int]], tol_deg: float = 0.5
) -> list[tuple[Line | Arc, float, int]]:
    """Fügt aneinanderliegende Bogenstücke desselben Pfads zu einem Bogen bzw. Vollkreis
    zusammen. Gestrichelte Kreise bleiben getrennt, weil zwischen ihren Stücken Lücken sind."""
    groups: dict[tuple, list[Arc]] = defaultdict(list)
    out: list[tuple[Line | Arc, float, int]] = []
    for g, width, pid in geoms:
        if isinstance(g, Arc):
            key = (pid, round(width, 3), round(g.center[0], 1), round(g.center[1], 1), round(g.radius, 1))
            groups[key].append(_normalized(g))
        else:
            out.append((g, width, pid))

    for (pid, width, *_), arcs in groups.items():
        arcs.sort(key=lambda a: a.start_deg)
        merged: list[Arc] = []
        for a in arcs:
            if merged and abs((merged[-1].start_deg + merged[-1].sweep_deg) - a.start_deg) < tol_deg:
                last = merged[-1]
                merged[-1] = Arc(last.center, last.radius, last.start_deg, last.sweep_deg + a.sweep_deg)
            else:
                merged.append(a)
        # Überlauf über 0°: letztes Stück an das erste hängen
        if len(merged) > 1:
            first, last = merged[0], merged[-1]
            if abs((last.start_deg + last.sweep_deg) - (first.start_deg + 360.0)) < tol_deg:
                merged[0] = Arc(first.center, first.radius, last.start_deg, last.sweep_deg + first.sweep_deg)
                merged.pop()
        for a in merged:
            if a.sweep_deg >= 359.0:
                a = Arc(a.center, a.radius, 0.0, 360.0)
            out.append((a, width, pid))
    return out


def point_segment_distance(p: Point, a: Point, b: Point) -> tuple[float, float]:
    """Abstand von p zur Strecke ab und Parameter t der Projektion (0 = a, 1 = b)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    ll = dx * dx + dy * dy
    if ll == 0:
        return math.dist(p, a), 0.0
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ll
    tc = min(1.0, max(0.0, t))
    return math.dist(p, (a[0] + tc * dx, a[1] + tc * dy)), t


def angle_diff(a: float, b: float) -> float:
    """Kleinster Winkel zwischen zwei Richtungen in Grad (Richtungen modulo 180°)."""
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def expand(b: BBox, m: float) -> BBox:
    return b[0] - m, b[1] - m, b[2] + m, b[3] + m


def overlaps(a: BBox, b: BBox) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def contains(outer: BBox, inner: BBox) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def union(boxes: Iterable[BBox]) -> BBox:
    bs = list(boxes)
    return min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)


class Grid:
    """Einfacher räumlicher Index: Objekte nach Bounding Box in Rasterzellen einsortiert."""

    def __init__(self, cell: float = 5.0) -> None:
        self.cell = cell
        self.cells: dict[tuple[int, int], list[int]] = defaultdict(list)

    def _keys(self, b: BBox) -> Iterator[tuple[int, int]]:
        c = self.cell
        for i in range(int(b[0] // c), int(b[2] // c) + 1):
            for j in range(int(b[1] // c), int(b[3] // c) + 1):
                yield i, j

    def insert(self, idx: int, b: BBox) -> None:
        for k in self._keys(b):
            self.cells[k].append(idx)

    def query(self, b: BBox) -> set[int]:
        found: set[int] = set()
        for k in self._keys(b):
            found.update(self.cells.get(k, ()))
        return found


class UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra

    def groups(self, members: Iterable[int]) -> dict[int, list[int]]:
        out: dict[int, list[int]] = defaultdict(list)
        for m in members:
            out[self.find(m)].append(m)
        return out
