"""Test the original BCT drawing regression fixtures.

The fixtures remain under resources/Drawing2CAD.
Tests skip when the drawing files are absent.
Expected view counts are manually reviewed reference values.
"""

from pathlib import Path

import pytest

from drawing2cad_mcp.vector import Kind, extract
from drawing2cad_mcp.vector.model import Line

# Original regression drawings remain separate from the runtime package.
_ROOT = Path(__file__).resolve().parents[3]
SAMPLES = _ROOT / "resources" / "Drawing2CAD"

# Part -> (view count including shaded image, cutting plane present)
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
        pytest.skip(f"Regression drawing is absent: {pdf}")
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
    """At a scale of 2:1, diameters 20 and 30 give sheet radii of 20 and 30 mm."""
    drawing = extract(_pdf("Flansch"))
    radii = {round(s.geom.radius, 2) for s in drawing.strokes if getattr(s.geom, "is_circle", False)
             and s.kind is Kind.CONTOUR}
    assert {20.0, 30.0} <= radii


def test_maschinenteil_split_arrowhead_is_arrow():
    """The 25.5-degree dimension arrowhead spans two consecutive PDF paths.
    One leg and the fill strokes precede the other leg and the base."""
    drawing = extract(_pdf("Maschinenteil"))
    head = [s for s in drawing.strokes
            if isinstance(s.geom, Line) and all(59.7 <= x <= 62.45 and 47.9 <= y <= 51.0 for x, y in s.geom.endpoints())]
    assert len(head) == 22 and len({s.path_id for s in head}) == 2
    assert all(s.kind is Kind.ARROW for s in head)
    assert not any(s.kind is Kind.UNCLEAR for s in drawing.strokes)
