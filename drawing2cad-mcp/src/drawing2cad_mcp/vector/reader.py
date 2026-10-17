"""Read PDF lines, circular arc candidates, and filled character paths."""

from __future__ import annotations

import math
from pathlib import Path

import pymupdf

from .geometry import circle_through, fit_arcs_into_circles
from .model import Arc, Glyph, Line, Point, Stroke
from .template import PT_TO_MM, in_drawing_area

# Maximum radial error for a fitted circular arc, in millimeters.
_ARC_TOL = 0.02
# Ignore short segments, including duplicate zero-length export segments.
_MIN_LEN = 0.01


def _mm(p: pymupdf.Point) -> Point:
    return p.x * PT_TO_MM, p.y * PT_TO_MM


def _bezier(p0: Point, c1: Point, c2: Point, p3: Point, t: float) -> Point:
    u = 1 - t
    return (
        u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p3[1],
    )


def _bezier_to_geometry(p0: Point, c1: Point, c2: Point, p3: Point) -> list[Line | Arc]:
    """Fit a circular arc where possible. Otherwise, return a polyline."""
    mid = _bezier(p0, c1, c2, p3, 0.5)
    circle = circle_through(p0, mid, p3)
    if circle is not None:
        center, r = circle
        if all(
            abs(math.dist(_bezier(p0, c1, c2, p3, t), center) - r) < _ARC_TOL for t in (0.25, 0.75)
        ):
            a0 = math.degrees(math.atan2(p0[1] - center[1], p0[0] - center[0]))
            am = math.degrees(math.atan2(mid[1] - center[1], mid[0] - center[0]))
            a1 = math.degrees(math.atan2(p3[1] - center[1], p3[0] - center[0]))
            sweep = (a1 - a0) % 360.0
            # Use the curve midpoint to determine sweep direction.
            if (am - a0) % 360.0 > sweep:
                sweep -= 360.0
            return [Arc(center, r, a0, sweep)]
    pts = [_bezier(p0, c1, c2, p3, i / 8) for i in range(9)]
    return [Line(a, b) for a, b in zip(pts, pts[1:])]


def _contours(items: list) -> list[list[Point]]:
    """Separate a filled path into polygon contours."""
    contours: list[list[Point]] = []
    for item in items:
        if item[0] == "re":
            rect = item[1]
            corners = [_mm(rect.tl), _mm(rect.tr), _mm(rect.br), _mm(rect.bl)]
            contours.append(corners + corners[:1])
            continue
        if item[0] == "qu":
            quad = item[1]
            corners = [_mm(quad.ul), _mm(quad.ur), _mm(quad.lr), _mm(quad.ll)]
            contours.append(corners + corners[:1])
            continue
        if item[0] != "l":
            continue
        a, b = _mm(item[1]), _mm(item[2])
        if not contours or math.dist(contours[-1][-1], a) > 1e-6:
            contours.append([a])
        contours[-1].append(b)
    return contours


def read_pdf(path: Path) -> tuple[list[Stroke], list[Glyph], tuple[float, float], tuple | None]:
    """Return strokes, glyphs, sheet size, and the embedded image bounding box.
    Read page one with the calibrated drawing-area profile."""
    with pymupdf.open(path) as doc:
        return _read_page(doc[0])


def _read_page(page: pymupdf.Page) -> tuple[list[Stroke], list[Glyph], tuple[float, float], tuple | None]:
    sheet = (page.rect.width * PT_TO_MM, page.rect.height * PT_TO_MM)

    raster = None
    for img in page.get_images():
        for r in page.get_image_rects(img[0]):
            raster = (r.x0 * PT_TO_MM, r.y0 * PT_TO_MM, r.x1 * PT_TO_MM, r.y1 * PT_TO_MM)

    geoms: list[tuple[Line | Arc, float, int]] = []
    glyphs: list[Glyph] = []
    seen: set[tuple] = set()
    for path_id, d in enumerate(page.get_drawings()):
        if d["type"] == "f":
            r = d["rect"]
            box = (r.x0 * PT_TO_MM, r.y0 * PT_TO_MM, r.x1 * PT_TO_MM, r.y1 * PT_TO_MM)
            if in_drawing_area(box):
                contours = _contours(d["items"])
                if not contours or any(item[0] not in {"l", "re", "qu"} for item in d["items"]):
                    raise ValueError("The filled path contains unsupported glyph geometry.")
                glyphs.append(Glyph(box, contours))
            continue
        width = (d.get("width") or 0.0) * PT_TO_MM
        for item in d["items"]:
            op, pts = item[0], [_mm(p) for p in item[1:] if isinstance(p, pymupdf.Point)]
            if op == "l":
                parts: list[Line | Arc] = [Line(pts[0], pts[1])]
            elif op == "c":
                parts = _bezier_to_geometry(*pts)
            elif op == "qu":
                q = item[1]
                corners = [_mm(q.ul), _mm(q.ur), _mm(q.lr), _mm(q.ll)]
                parts = [Line(a, b) for a, b in zip(corners, corners[1:] + corners[:1])]
            elif op == "re":
                rect = item[1]
                corners = [_mm(rect.tl), _mm(rect.tr), _mm(rect.br), _mm(rect.bl)]
                parts = [Line(a, b) for a, b in zip(corners, corners[1:] + corners[:1])]
            else:
                continue
            for g in parts:
                if isinstance(g, Line):
                    if g.length < _MIN_LEN:
                        continue
                    a, b = sorted([g.p0, g.p1])
                    key = ("l", round(a[0], 2), round(a[1], 2), round(b[0], 2), round(b[1], 2), round(width, 2))
                else:
                    key = ("a", round(g.center[0], 2), round(g.center[1], 2), round(g.radius, 2),
                           round(g.start_deg % 360, 1), round(g.sweep_deg, 1), round(width, 2))
                if key in seen:  # NX can export duplicate segments.
                    continue
                seen.add(key)
                if in_drawing_area(g.bbox()):
                    geoms.append((g, width, path_id))

    strokes = [Stroke(i, g, w, pid) for i, (g, w, pid) in enumerate(fit_arcs_into_circles(geoms))]
    return strokes, glyphs, sheet, raster
