"""Overlay-PNG zur Sichtkontrolle: Originalzeichnung blass, darüber die Klassen in Farbe
und die erkannten Ansichten als nummerierte Rahmen."""

from __future__ import annotations

from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

from .model import Arc, Drawing, Kind

COLORS: dict[Kind, tuple[int, int, int]] = {
    Kind.CONTOUR: (20, 20, 20),
    Kind.HATCH: (0, 150, 220),
    Kind.CENTERLINE: (0, 170, 80),
    Kind.HIDDEN: (150, 90, 0),
    Kind.DIMENSION: (230, 40, 160),
    Kind.EXTENSION: (240, 140, 200),
    Kind.ARROW: (230, 40, 160),
    Kind.CUTTING_PLANE: (140, 40, 220),
    Kind.UNCLEAR: (255, 0, 0),
}
_VIEW = (255, 120, 0)
_TEXT = (120, 120, 255)


def render_overlay(drawing: Drawing, pdf: Path, out: Path, px_per_mm: float = 4.0) -> None:
    page = pymupdf.open(pdf)[0]
    zoom = px_per_mm * 25.4 / 72.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    base = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    img = Image.blend(Image.new("RGB", base.size, "white"), base, 0.25)
    draw = ImageDraw.Draw(img)

    def px(p: tuple[float, float]) -> tuple[float, float]:
        return p[0] * px_per_mm, p[1] * px_per_mm

    for s in drawing.strokes:
        color = COLORS[s.kind]
        w = 3 if s.kind is Kind.UNCLEAR else 2 if s.kind is Kind.CONTOUR else 1
        g = s.geom
        if isinstance(g, Arc):
            cx, cy = px(g.center)
            r = g.radius * px_per_mm
            box = (cx - r, cy - r, cx + r, cy + r)
            if g.is_circle:
                draw.ellipse(box, outline=color, width=w)
            else:  # PIL zeichnet im Uhrzeigersinn ab 3 Uhr, wie unser y-nach-unten-System
                draw.arc(box, g.start_deg, g.start_deg + g.sweep_deg, fill=color, width=w)
        else:
            draw.line([px(g.p0), px(g.p1)], fill=color, width=w)

    for t in drawing.texts:
        draw.rectangle([px(t.bbox[:2]), px(t.bbox[2:])], outline=_TEXT, width=1)
        x, y = px((t.bbox[0], t.bbox[3]))
        draw.text((x, y + 2), t.text, fill=_TEXT, font_size=16)
    for v in drawing.views:
        x0, y0 = px(v.bbox[:2])
        x1, y1 = px(v.bbox[2:])
        draw.rectangle([x0 - 6, y0 - 6, x1 + 6, y1 + 6], outline=_VIEW, width=3)
        label = f"V{v.id}" + (" iso" if v.is_iso else "")
        draw.text((x0 - 4, y0 - 26), label, fill=_VIEW, font_size=22)

    legend = list(COLORS.items())
    for n, (kind, color) in enumerate(legend):
        y = 12 + n * 24
        draw.rectangle([12, y, 32, y + 16], fill=color)
        draw.text((40, y - 2), kind.value, fill=(0, 0, 0), font_size=18)
    img.save(out)
