"""Erzeugt eine Demo-Zeichnung mit unklaren Stellen für den Prüfen-Schritt der Demo-App.

Grundlage ist der Flansch aus den BCT-Samples, der ohne offene Stellen durchläuft. Darauf kommen drei Störungen,
wie sie in alten, von Hand nachbearbeiteten Zeichnungen vorkommen:

1. Korrekturvermerk: eine freie Schlangenlinie zwischen zwei Ansichten
2. Nachgezeichneter Hinweispfeil: schiefes Dreieck mit kurzem Strich neben Ansicht 4
3. Toleranz mit fremdem Zeichen: „38“ wird zu „38 ±1“; das „±“ kennt die NX-Schrift nicht,
   die „1“ ist die echte Glyphe aus dem Blatt (kopiert aus der Maßzahl „10“)

Die Positionen sind auf den Flansch zugeschnitten (Blatt-mm, Ursprung oben links). Das Ergebnis ist erzeugt und gehört
deshalb nach `output/` (ignoriert, kommt nicht ins Docker-Image).

    uv run python scripts/make_demo_drawing.py ../resources/Drawing2CAD/Flansch/Flansch_dwg.pdf ../output/demo/Flansch-Demo_dwg.pdf
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf

PT_PER_MM = 72 / 25.4
BLACK = (0.0, 0.0, 0.0)
CONTOUR_WIDTH_MM = 0.35  # wie die Konturen des Flanschs

# Glyphe „1“ der Maßzahl „10“ rechts oben in Ansicht 4 (Blatt-mm)
GLYPH_ONE_BOX = (338.0, 97.5, 340.0, 101.5)
# Maßzahl „38“ unter Ansicht 1: Unterkante und rechter Rand, dahinter kommt die Toleranz
TEXT_38_RIGHT, TEXT_38_BOTTOM = 121.34, 87.28


def pt(x: float, y: float) -> pymupdf.Point:
    return pymupdf.Point(x * PT_PER_MM, y * PT_PER_MM)


def polyline(page: pymupdf.Page, points: list[tuple[float, float]], closed: bool = False) -> None:
    shape = page.new_shape()
    shape.draw_polyline([pt(*p) for p in points])
    shape.finish(color=BLACK, width=CONTOUR_WIDTH_MM * PT_PER_MM, closePath=closed)
    shape.commit()


def correction_mark(page: pymupdf.Page) -> None:
    """Freihand-Schlangenlinie mit unregelmäßigen Winkeln (keine Schraffur-Schar).

    Unter 20 mm Gesamtlänge, sonst hielte der Extraktor sie für eine eigene Ansicht (views._MIN_VIEW_LENGTH)."""
    polyline(page, [(258, 98), (259.8, 95.6), (261.4, 98.9), (263.6, 96.1), (264.9, 99.6), (267.2, 97.2)])


def crooked_arrow(page: pymupdf.Page) -> None:
    """Schiefe Pfeilspitze (Schenkel 3,6 und 2,4 mm) mit Strich, zeigt auf Ansicht 4, berührt sie aber nicht."""
    tip = (353.5, 150.0)
    polyline(page, [tip, (357.0, 148.6), (355.4, 151.6)], closed=True)
    polyline(page, [(356.2, 150.1), (364.0, 153.8)])  # kurz halten: alles zusammen unter 20 mm


def copy_glyph(page: pymupdf.Page, box: tuple[float, float, float, float], dx: float, dy: float) -> None:
    """Zeichnet die gefüllte Glyphe innerhalb von box (Blatt-mm) um dx/dy versetzt noch einmal."""
    rect = pymupdf.Rect(*pt(box[0], box[1]), *pt(box[2], box[3]))
    glyph = next(d for d in page.get_drawings() if d.get("fill") is not None and rect.contains(d["rect"]))
    offset = pymupdf.Point(dx * PT_PER_MM, dy * PT_PER_MM)
    shape = page.new_shape()
    for item in glyph["items"]:
        if item[0] != "l":  # NX-Glyphen bestehen nur aus Geraden
            raise ValueError(f"unerwartetes Pfadelement {item[0]!r}")
        shape.draw_line(item[1] + offset, item[2] + offset)
    shape.finish(color=None, fill=BLACK, even_odd=glyph.get("even_odd", True), closePath=True)
    shape.commit()


def plus_minus(page: pymupdf.Page, x: float, bottom: float) -> None:
    """„±“ als eine gefüllte Glyphe (Plus oben, Strich unten).

    Die Proportionen sind bewusst so gewählt, dass der Extraktor „?“ liest. Andere ergaben „t“ oder sogar „2“
    („38 ±1“ → „3821“), siehe ADR 0004 (Trade-offs).
    """
    w, t, gap = 2.4, 0.32, 0.2  # Breite, Strichstärke, Abstand Plus → Unterstrich in mm
    cx, cy = x + w / 2, bottom - t - gap - w / 2
    bars = [
        (x, cy - t / 2, x + w, cy + t / 2),  # waagrecht
        (cx - t / 2, cy - w / 2, cx + t / 2, cy + w / 2),  # senkrecht
        (x, bottom - t, x + w, bottom),  # Unterstrich
    ]
    shape = page.new_shape()
    for x0, y0, x1, y1 in bars:  # als Linienzüge wie bei NX, nicht als Rechteck-Elemente
        shape.draw_polyline([pt(x0, y0), pt(x1, y0), pt(x1, y1), pt(x0, y1), pt(x0, y0)])
    shape.finish(color=None, fill=BLACK, even_odd=False)
    shape.commit()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", type=Path, help="Flansch_dwg.pdf aus den Samples")
    ap.add_argument("out", type=Path, help="Ziel-PDF, z. B. ../output/demo/Flansch-Demo_dwg.pdf")
    args = ap.parse_args(argv)

    doc = pymupdf.open(args.src)
    page = doc[0]
    correction_mark(page)
    crooked_arrow(page)
    plus_minus(page, TEXT_38_RIGHT + 1.0, TEXT_38_BOTTOM)
    copy_glyph(page, GLYPH_ONE_BOX, dx=(TEXT_38_RIGHT + 4.0) - GLYPH_ONE_BOX[0] - 0.3, dy=TEXT_38_BOTTOM - 101.22)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(args.out, garbage=3, deflate=True)
    print(f"geschrieben: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
