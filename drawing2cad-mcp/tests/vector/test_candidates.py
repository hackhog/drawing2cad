"""Test conservative geometry candidates and displayed evidence locations."""

from hashlib import sha256

import pymupdf
import pytest

from drawing2cad_mcp.vector import extract
from drawing2cad_mcp.vector.export import to_dict
from drawing2cad_mcp.vector.model import Arc, Drawing, Kind, Stroke, TextBlock
from drawing2cad_mcp.vector.template import PT_TO_MM


def test_circles_are_not_reported_as_verified_holes():
    drawing = Drawing("synthetic", (420, 297), [
        Stroke(1, Arc((100, 100), 10, 0, 360), 0.25, 1, Kind.CONTOUR),
        Stroke(2, Arc((140, 100), 10, 0, 180), 0.25, 2, Kind.CONTOUR),
        Stroke(3, Arc((180, 100), 10, 0, 360), 0.1, 3, Kind.CENTERLINE),
    ], [], [], None)
    circles = to_dict(drawing)["circle_candidates"]
    assert len(circles) == 2  # A semicircle is not a hole candidate.
    assert circles[0]["hole_candidate"] is True
    assert circles[0]["diameter_sheet_mm"] == 20
    assert circles[0]["semantic_status"] == "unverified"
    assert circles[1]["hole_candidate"] is False


def test_dimension_candidates_keep_uncertain_text_and_locations():
    drawing = Drawing("synthetic", (420, 297), [], [
        TextBlock(1, (100, 100, 110, 105), 4, "Ø2,5", 0, 0.81),
        TextBlock(2, (120, 100, 130, 105), 3, "45°", 0, 0.93),
        TextBlock(3, (140, 100, 150, 105), 3, "1?5", 0, 0),
    ], [], None)
    data = to_dict(drawing)
    assert len(data["dimension_candidates"]) == 2
    assert data["dimension_candidates"][0]["value"] == 2.5
    assert data["dimension_candidates"][0]["unit"] == "unspecified"
    assert data["dimension_candidates"][0]["confidence"] == 0.81
    assert data["dimension_candidates"][0]["geometry_association"] is None
    assert data["text_blocks"][2]["text"] == "1?5"


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotated_native_dimension_and_circle_share_display_coordinates(tmp_path, rotation):
    path = tmp_path / "circle.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=420 / PT_TO_MM, height=297 / PT_TO_MM)
        page.draw_circle((300, 300), 30, color=(0, 0, 0), width=0.7)
        page.insert_text((330, 300), "60", fontsize=10)
        page.set_rotation(rotation)
        doc.save(path)
    before = sha256(path.read_bytes()).hexdigest()
    data = to_dict(extract(path))
    assert sha256(path.read_bytes()).hexdigest() == before
    assert len(data["circle_candidates"]) == 1
    circle = data["circle_candidates"][0]
    assert circle["diameter_sheet_mm"] == pytest.approx(60 * PT_TO_MM, abs=0.01)
    dimension = data["dimension_candidates"][0]
    assert dimension["value"] == 60
    assert dimension["method"] == "native_pdf_text"
    assert data["text_blocks"][0]["angle_deg"] == (-rotation) % 360
    assert all(0 <= value <= 1 for value in dimension["bbox_normalized"])
    width, height = data["sheet_size_mm"]
    assert all(0 <= value <= bound for value, bound in zip(circle["center_sheet_mm"], (width, height)))
