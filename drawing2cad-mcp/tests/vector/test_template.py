"""Test the drawing-area profiles with synthetic PDF paths."""

import pymupdf

from drawing2cad_mcp.vector.template import (A4_PORTRAIT_AREA, AREA_NAMES, BCT_A3_AREA, CAX_A3_AREA, PT_TO_MM,
                                             drawing_area, in_drawing_area)


def _line(x0, y0, x1, y1):
    """One PDF line item in millimeters, converted to points."""
    return {"items": [("l", pymupdf.Point(x0 / PT_TO_MM, y0 / PT_TO_MM), pymupdf.Point(x1 / PT_TO_MM, y1 / PT_TO_MM))]}


def test_a4_portrait_sheet_uses_the_a4_frame_and_title_block():
    area = drawing_area((210.0, 297.0), [])
    assert area == A4_PORTRAIT_AREA and AREA_NAMES[area] == "a4_portrait"
    assert in_drawing_area((60, 60, 100, 100), area)
    assert not in_drawing_area((100, 240, 120, 250), area)  # Title block
    assert not in_drawing_area((5, 5, 15, 15), area)  # Outside the frame


def test_segmented_cax_title_block_line_selects_the_cax_profile():
    pieces = [_line(243, 233, 273, 233), _line(273, 233, 318, 233), _line(318, 233, 410.0, 233)]
    area = drawing_area((420.0, 297.0), pieces)
    assert area == CAX_A3_AREA and AREA_NAMES[area] == "cax_a3"
    assert not in_drawing_area((300, 236, 320, 240), area)


def test_a3_without_the_cax_line_keeps_the_bct_profile():
    assert drawing_area((420.0, 297.0), [_line(243, 233, 300, 233)]) == BCT_A3_AREA
    assert in_drawing_area((300, 236, 320, 240), BCT_A3_AREA)
