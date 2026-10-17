"""Test rectangle paths and PDF handle closure with synthetic drawings."""

from pathlib import Path

import pymupdf
import pytest

from drawing2cad_mcp.vector import extract
from drawing2cad_mcp.vector import reader
from drawing2cad_mcp.vector.model import Line
from drawing2cad_mcp.vector.template import PT_TO_MM


def _rectangle_pdf(path: Path) -> None:
    with pymupdf.open() as document:
        page = document.new_page(width=420 / PT_TO_MM, height=297 / PT_TO_MM)
        # Both objects are inside the supported drawing area.
        page.draw_rect(pymupdf.Rect(100, 100, 200, 180), color=(0, 0, 0), width=0.4)
        page.draw_rect(pymupdf.Rect(220, 100, 223.75, 101.22), color=None, fill=(0, 0, 0))
        document.save(path)


def test_stroked_rectangle_retains_all_four_edges(tmp_path):
    path = tmp_path / "rectangles.pdf"
    _rectangle_pdf(path)
    strokes, glyphs, sheet, _ = reader.read_pdf(path)

    assert len(strokes) == 4
    assert all(isinstance(stroke.geom, Line) for stroke in strokes)
    assert sorted(stroke.geom.length for stroke in strokes) == pytest.approx(
        sorted([100 * PT_TO_MM, 100 * PT_TO_MM, 80 * PT_TO_MM, 80 * PT_TO_MM])
    )
    assert len(glyphs) == 1
    assert sheet == pytest.approx((420, 297), abs=0.001)


def test_filled_rectangle_has_a_closed_glyph_contour(tmp_path):
    path = tmp_path / "rectangles.pdf"
    _rectangle_pdf(path)
    _, glyphs, _, _ = reader.read_pdf(path)

    assert len(glyphs) == 1
    assert len(glyphs[0].contours) == 1
    contour = glyphs[0].contours[0]
    assert len(contour) == 5
    assert contour[0] == contour[-1]
    # The complete pipeline previously failed on an empty rectangle contour.
    drawing = extract(path)
    assert len(drawing.texts) == 1
    assert drawing.texts[0].glyph_count == 1


def test_filled_quad_has_a_closed_glyph_contour():
    quad = pymupdf.Quad((100, 100), (120, 100), (100, 110), (120, 110))
    contours = reader._contours([("qu", quad)])
    assert len(contours) == 1
    assert len(contours[0]) == 5
    assert contours[0][0] == contours[0][-1]


@pytest.mark.parametrize("fail", [False, True])
def test_pdf_handle_closes_after_read_or_error(tmp_path, monkeypatch, fail):
    path = tmp_path / "rectangles.pdf"
    _rectangle_pdf(path)
    documents = []
    original_open = reader.pymupdf.open

    def tracked_open(*args, **kwargs):
        document = original_open(*args, **kwargs)
        documents.append(document)
        return document

    monkeypatch.setattr(reader.pymupdf, "open", tracked_open)
    if fail:
        def fail_read(page):
            raise ValueError("Synthetic read failure.")

        monkeypatch.setattr(reader, "_read_page", fail_read)
        with pytest.raises(ValueError, match="Synthetic read failure"):
            reader.read_pdf(path)
    else:
        reader.read_pdf(path)
    assert len(documents) == 1
    assert documents[0].is_closed


def test_filled_curve_retains_closed_contour_and_does_not_abort(tmp_path):
    path = tmp_path / "filled-curve.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=420 / PT_TO_MM, height=297 / PT_TO_MM)
        page.draw_circle((150, 150), 2, color=None, fill=(0, 0, 0))
        document.save(path)

    before = path.read_bytes()
    strokes, glyphs, _, _ = reader.read_pdf(path)
    assert strokes == []
    assert len(glyphs) == 1
    contour = glyphs[0].contours[0]
    assert len(contour) == 65
    assert contour[0] == pytest.approx(contour[-1])
    assert len(extract(path).texts) == 1
    assert path.read_bytes() == before


def test_mixed_filled_line_and_curve_retains_subpaths():
    p = pymupdf.Point
    contours = reader._contours([
        ("l", p(100, 100), p(110, 100)),
        ("c", p(110, 100), p(120, 100), p(120, 110), p(110, 110)),
        ("l", p(110, 110), p(100, 100)),
        ("c", p(200, 200), p(201, 200), p(201, 201), p(200, 200)),
    ])
    assert len(contours) == 2
    assert len(contours[0]) == 19
    assert len(contours[1]) == 17
    assert all(contour[0] == contour[-1] for contour in contours)
    assert contours[0][1] == (110 * PT_TO_MM, 100 * PT_TO_MM)


def test_unknown_filled_operation_fails_explicitly():
    with pytest.raises(ValueError, match="unsupported glyph geometry"):
        reader._contours([("unknown",)])
