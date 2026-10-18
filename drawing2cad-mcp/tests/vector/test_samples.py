"""Test the original BCT drawing regression fixtures.

The fixtures remain under resources/Drawing2CAD.
Tests skip when the drawing files are absent.
Expected view counts are manually reviewed reference values.
"""

from pathlib import Path
from hashlib import sha256

import pytest
from pypdf import PdfWriter

from drawing2cad_mcp.vector import Kind, extract
from drawing2cad_mcp.vector.model import Line
from drawing2cad_mcp.pdf import PdfService

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


@pytest.mark.parametrize("name,filename", [
    ("Flansch", "Flansch_dwg.pdf"), ("3-Loch-Hebel", "3-Loch-Hebel.pdf"),
    ("Grundplatte", "Grundplatte.pdf"),
])
def test_evaluation_pdf_extraction_keeps_source_and_candidate_evidence(tmp_path, name, filename):
    source = SAMPLES / name / filename
    if not source.exists():
        pytest.skip(f"Evaluation drawing is absent: {source}")
    before = sha256(source.read_bytes()).hexdigest()
    service = PdfService((SAMPLES,), tmp_path / "out", None)
    result = service.extract_drawing(source)
    assert result["source"]["sha256"] == before == sha256(source.read_bytes()).hexdigest()
    assert result["summary"]["strokes"] > 0
    assert result["dimension_candidates"]
    assert all(candidate["semantic_status"] == "unverified" for candidate in result["circle_candidates"])
    assert result["provenance"]["scale_applied"] is False


def test_rotated_flansch_retains_printed_values_and_calibrates_two_diameters(tmp_path):
    source = _pdf("Flansch")
    before = sha256(source.read_bytes()).hexdigest()
    writer = PdfWriter(source)
    writer.pages[0].rotate(90)
    rotated = tmp_path / "flansch-rotated.pdf"
    writer.write(rotated)
    service = PdfService((tmp_path,), tmp_path / "out", None)
    result = service.extract_drawing(rotated)
    references = []
    # These two independently printed diameters are the existing reviewed
    # regression values. Their circles are measured from vector geometry.
    for diameter in (20, 30):
        dimension = next(d for d in result["dimension_candidates"]
                         if d["kind"] == "diameter" and d["value"] == diameter)
        circle = next(c for c in result["circle_candidates"]
                      if abs(c["diameter_sheet_mm"] - diameter * 2) < 0.02)
        x, y = circle["center_sheet_mm"]
        radius = circle["diameter_sheet_mm"] / 2
        references.append({"dimension_id": dimension["id"], "printed_value_mm": diameter,
                           "p0": [x - radius, y], "p1": [x + radius, y],
                           "source_region": dimension["bbox_normalized"], "evidence": "printed_dimension"})
    cal = service.calibrate(rotated, 1, references)["calibration"]
    assert cal["mm_per_coordinate_unit"] == pytest.approx(0.5, abs=0.0002)
    assert sha256(source.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(("folder", "filename", "template", "views", "unclear"), [
    ("Achse", "Achse.pdf", "a4_portrait", 3, 1),
    ("3-Loch-Hebel", "3-Loch-Hebel.pdf", "cax_a3", 2, 1),
    ("Schnittmenge", "Schnittmenge.pdf", "bct_a3", 6, 0),
    ("Trägerplatte V2", "Traegerplatte.pdf", "bct_a3", 4, 1),
    ("Grundplatte", "Grundplatte.pdf", "bct_a3", 5, 2),
])
def test_thick_contours_are_not_cutting_planes(folder, filename, template, views, unclear):
    """The CAx template draws contours with 0.5 mm and has a higher title block.
    Schnittmenge, Trägerplatte V2, and Grundplatte use the ISO 128 line groups 0.7 and 0.5 with 0.35 mm thin lines."""
    pdf = SAMPLES / folder / filename
    if not pdf.exists():
        pytest.skip(f"Regression drawing is absent: {pdf}")
    drawing = extract(pdf)
    assert drawing.template == template
    assert len(drawing.views) == views
    assert sum(s.kind is Kind.UNCLEAR for s in drawing.strokes) <= unclear
    assert sum(s.kind is Kind.CONTOUR for s in drawing.strokes) > sum(s.kind is Kind.CUTTING_PLANE for s in drawing.strokes)
