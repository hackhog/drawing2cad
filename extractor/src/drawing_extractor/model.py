"""Datenmodell des Extraktors. Alle Koordinaten in Millimetern auf dem Blatt,
Ursprung oben links, y zeigt nach unten (wie im PDF-Seitenkoordinatensystem)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

Point = tuple[float, float]


class Kind(StrEnum):
    """Bedeutung eines Strichs, wie der Klassifikator sie einordnet."""

    CONTOUR = "contour"  # sichtbare Körperkante
    HATCH = "hatch"  # Schraffur einer Schnittfläche
    CENTERLINE = "centerline"  # Strich-Punkt-Linie (Mittel-/Symmetrielinie, Lochkreis)
    HIDDEN = "hidden"  # Strichlinie (verdeckte Kante)
    DIMENSION = "dimension"  # Maßlinie oder Hinweislinie mit Pfeil
    EXTENSION = "extension"  # Maßhilfslinie
    ARROW = "arrow"  # Maßpfeil (Dreieck samt Füllstrichen)
    CUTTING_PLANE = "cutting_plane"  # Schnittverlauf mit Pfeilen (A-A, B-B …)
    UNCLEAR = "unclear"


@dataclass(slots=True)
class Line:
    p0: Point
    p1: Point

    @property
    def length(self) -> float:
        return math.dist(self.p0, self.p1)

    @property
    def angle(self) -> float:
        """Richtung in Grad, normiert auf [0, 180)."""
        a = math.degrees(math.atan2(self.p1[1] - self.p0[1], self.p1[0] - self.p0[0]))
        return a % 180.0

    def bbox(self) -> tuple[float, float, float, float]:
        (x0, y0), (x1, y1) = self.p0, self.p1
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)

    def endpoints(self) -> tuple[Point, Point]:
        return self.p0, self.p1


@dataclass(slots=True)
class Arc:
    """Kreisbogen von start_deg nach end_deg im mathematisch positiven Sinn
    (im y-nach-unten-System also im Uhrzeigersinn auf dem Bildschirm)."""

    center: Point
    radius: float
    start_deg: float
    sweep_deg: float

    @property
    def is_circle(self) -> bool:
        return abs(self.sweep_deg) >= 359.0

    def point_at(self, deg: float) -> Point:
        a = math.radians(deg)
        return self.center[0] + self.radius * math.cos(a), self.center[1] + self.radius * math.sin(a)

    @property
    def p0(self) -> Point:
        return self.point_at(self.start_deg)

    @property
    def p1(self) -> Point:
        return self.point_at(self.start_deg + self.sweep_deg)

    @property
    def length(self) -> float:
        return abs(math.radians(self.sweep_deg)) * self.radius

    def bbox(self) -> tuple[float, float, float, float]:
        # konservativ: Bounding Box des Vollkreises reicht für Gruppierung
        if self.is_circle:
            cx, cy = self.center
            r = self.radius
            return cx - r, cy - r, cx + r, cy + r
        pts = [self.point_at(self.start_deg + self.sweep_deg * i / 8) for i in range(9)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def endpoints(self) -> tuple[Point, ...]:
        return () if self.is_circle else (self.p0, self.p1)


Geometry = Line | Arc


@dataclass(slots=True)
class Stroke:
    """Ein gezeichnetes Primitiv (Linie oder Bogen) mit seiner Strichstärke."""

    id: int
    geom: Geometry
    width_mm: float
    path_id: int  # Index des PDF-Zeichenpfads, aus dem es stammt
    kind: Kind = Kind.UNCLEAR

    def bbox(self) -> tuple[float, float, float, float]:
        return self.geom.bbox()


@dataclass(slots=True)
class Glyph:
    """Gefüllter Umriss eines Schriftzeichens (die PDFs haben keine Textebene).
    `contours` sind geschlossene Polygone, gefüllt nach der Even-Odd-Regel."""

    bbox: tuple[float, float, float, float]
    contours: list[list[Point]] = field(default_factory=list)


@dataclass(slots=True)
class TextBlock:
    id: int
    bbox: tuple[float, float, float, float]
    glyph_count: int
    text: str = ""  # erkannter Text; "?" steht für ein nicht sicher erkanntes Zeichen
    angle_deg: float = 0.0  # Leserichtung, 0 = waagrecht, 90 = von unten nach oben lesbar


@dataclass(slots=True)
class View:
    id: int
    bbox: tuple[float, float, float, float]
    is_iso: bool
    stroke_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class Drawing:
    source: str
    sheet_size_mm: tuple[float, float]
    strokes: list[Stroke]
    texts: list[TextBlock]
    views: list[View]
    raster_bbox: tuple[float, float, float, float] | None  # eingebettetes 3D-Bild
