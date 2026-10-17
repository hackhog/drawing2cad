"""Vector drawing data in millimeters on the sheet.
The origin is at the top left. The positive y direction points down."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

Point = tuple[float, float]


class Kind(StrEnum):
    """Stroke class assigned by the classification rules."""

    CONTOUR = "contour"  # Visible body edge candidate
    HATCH = "hatch"  # Section hatching
    CENTERLINE = "centerline"  # Dash-dot line or center mark
    HIDDEN = "hidden"  # Hidden edge
    DIMENSION = "dimension"  # Dimension line or leader with an arrow
    EXTENSION = "extension"  # Extension line
    ARROW = "arrow"  # Dimension arrowhead and fill strokes
    CUTTING_PLANE = "cutting_plane"  # Cutting plane with section arrows
    ANNOTATION = "annotation"  # Table separator, edge condition symbol, or drawn parenthesis; not part geometry
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
        """Return the direction in degrees, normalized to [0, 180)."""
        a = math.degrees(math.atan2(self.p1[1] - self.p0[1], self.p1[0] - self.p0[0]))
        return a % 180.0

    def bbox(self) -> tuple[float, float, float, float]:
        (x0, y0), (x1, y1) = self.p0, self.p1
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)

    def endpoints(self) -> tuple[Point, Point]:
        return self.p0, self.p1


@dataclass(slots=True)
class Arc:
    """Circular arc with a start angle and a signed sweep.
    A positive sweep is clockwise in sheet coordinates."""

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
        # A full circle uses its exact bounding box.
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
    """Drawing primitive with its source path and line width."""

    id: int
    geom: Geometry
    width_mm: float
    path_id: int  # Index of the original PDF drawing path
    kind: Kind = Kind.UNCLEAR

    def bbox(self) -> tuple[float, float, float, float]:
        return self.geom.bbox()


@dataclass(slots=True)
class Glyph:
    """Filled character outline from a PDF without a text layer.
    Contours are closed polygons with the even-odd fill rule."""

    bbox: tuple[float, float, float, float]
    contours: list[list[Point]] = field(default_factory=list)


@dataclass(slots=True)
class TextBlock:
    id: int
    bbox: tuple[float, float, float, float]
    glyph_count: int
    text: str = ""  # A question mark indicates an unrecognized character.
    angle_deg: float = 0.0  # Reading direction: 0 horizontal, 90 bottom to top
    confidence: float = 0.0  # Heuristic match score, not a probability.
    method: str = "vector_glyph_template"


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
    raster_bbox: tuple[float, float, float, float] | None  # Embedded shaded image
    rotation_degrees: int = 0
