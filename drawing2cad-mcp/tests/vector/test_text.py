"""Test glyph templates and the original reviewed text regression data.
The 206 expected text blocks were visually reviewed on 2026-10-16.
This historical review is separate from each new test execution."""

import json
from pathlib import Path

import pytest

from drawing2cad_mcp.vector import extract
from drawing2cad_mcp.vector.model import Glyph
from drawing2cad_mcp.vector.text import is_section_bar, load_templates

# Original regression drawings remain separate from the runtime package.
_ROOT = Path(__file__).resolve().parents[3]
SAMPLES = _ROOT / "resources" / "Drawing2CAD"
EXPECTED = json.loads((Path(__file__).parent / "expected_texts.json").read_text(encoding="utf-8"))


def test_templates_cover_dimension_characters():
    chars = {t.char for t in load_templates()}
    assert set("0123456789Ø,R°x-()=:M") <= chars


def test_section_bar_is_not_text_but_hyphen_is():
    def rect(w, h):
        pts = [(0, 0), (w, 0), (w, h), (0, h), (0, 0)]
        return Glyph((0, 0, w, h), [pts])

    assert is_section_bar(rect(10.0, 1.0))  # Section end bar
    assert not is_section_bar(rect(1.32, 0.43))  # Hyphen in A-A


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_texts_match_drawing(name):
    pdf = SAMPLES / name / f"{name}_dwg.pdf"
    if not pdf.exists():
        pytest.skip(f"Regression drawing is absent: {pdf}")
    texts = sorted(t.text for t in extract(pdf).texts)
    assert texts == EXPECTED[name]


def test_filled_triangle_is_an_arrowhead_not_text():
    from drawing2cad_mcp.vector.text import is_filled_arrowhead

    triangle = Glyph((0, 0, 3, 1), [[(0, 0), (3, 0.5), (0, 1), (0, 0)]])
    square = Glyph((0, 0, 1, 1), [[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]])
    assert is_filled_arrowhead(triangle)
    assert not is_filled_arrowhead(square)
