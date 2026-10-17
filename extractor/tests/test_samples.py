"""Regressionstests auf den BCT-Beispielzeichnungen.

Die Zeichnungen werden unter resources/Drawing2CAD (Team-Repo) oder data/samples erwartet;
fehlen sie, werden die Tests übersprungen. Die erwarteten Ansichten sind von Hand gezählt.
"""

from pathlib import Path

import pytest

from drawing_extractor import Kind, extract
from drawing_extractor.model import Line

# Team-Repo: resources/Drawing2CAD, lokale Arbeitskopie: data/samples
_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = next((p for p in (_ROOT / "resources" / "Drawing2CAD", _ROOT / "data" / "samples") if p.is_dir()), _ROOT / "data" / "samples")

# Teil -> (Anzahl Ansichten inkl. 3D-Ansicht, hat Schnittverlauf)
EXPECTED = {
    "Befestigung": (3, False),
    "Dreistern": (4, True),
    "Flansch": (4, True),
    "Fuss": (3, False),
    "Haken": (3, True),
    "Maschinenteil": (5, False),
    "Rotation": (4, True),
    "Trägerplatte": (4, True),
    "Welle": (3, True),
}


def _pdf(name: str) -> Path:
    pdf = SAMPLES / name / f"{name}_dwg.pdf"
    if not pdf.exists():
        pytest.skip(f"Beispielzeichnung fehlt: {pdf}")
    return pdf


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_views_are_grouped(name):
    drawing = extract(_pdf(name))
    views, has_section = EXPECTED[name]
    assert len(drawing.views) == views
    assert sum(v.is_iso for v in drawing.views) == 1
    kinds = {s.kind for s in drawing.strokes}
    assert Kind.DIMENSION in kinds and Kind.ARROW in kinds
    assert (Kind.CUTTING_PLANE in kinds) == has_section


def test_flansch_circles_have_drawing_radii():
    """Flansch, Maßstab 2:1: Ø20 und Ø30 erscheinen als Kreise mit r = 20 und 30 mm auf dem Blatt."""
    drawing = extract(_pdf("Flansch"))
    radii = {round(s.geom.radius, 2) for s in drawing.strokes if getattr(s.geom, "is_circle", False)
             and s.kind is Kind.CONTOUR}
    assert {20.0, 30.0} <= radii


def test_maschinenteil_split_arrowhead_is_arrow():
    """Die Spitze am Winkelmaß 25,5° (Ansicht 1) liegt in zwei aufeinanderfolgenden PDF-Pfaden:
    ein Schenkel und die Füllstriche im einen, zweiter Schenkel und Basis im nächsten."""
    drawing = extract(_pdf("Maschinenteil"))
    head = [s for s in drawing.strokes
            if isinstance(s.geom, Line) and all(59.7 <= x <= 62.45 and 47.9 <= y <= 51.0 for x, y in s.geom.endpoints())]
    assert len(head) == 22 and len({s.path_id for s in head}) == 2
    assert all(s.kind is Kind.ARROW for s in head)
    assert not any(s.kind is Kind.UNCLEAR for s in drawing.strokes)
