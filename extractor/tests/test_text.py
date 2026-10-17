"""Texterkennung. Die erwarteten Texte (`expected_texts.json`) wurden am 16.10.2026 Block für Block
gegen Ausschnitte der Zeichnung geprüft (alle 206 korrekt)."""

import json
from pathlib import Path

import pytest

from drawing_extractor import extract
from drawing_extractor.model import Glyph
from drawing_extractor.text import is_section_bar, load_templates

# Team-Repo: resources/Drawing2CAD, lokale Arbeitskopie: data/samples
_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = next((p for p in (_ROOT / "resources" / "Drawing2CAD", _ROOT / "data" / "samples") if p.is_dir()), _ROOT / "data" / "samples")
EXPECTED = json.loads((Path(__file__).parent / "expected_texts.json").read_text(encoding="utf-8"))


def test_templates_cover_dimension_characters():
    chars = {t.char for t in load_templates()}
    assert set("0123456789Ø,R°x-()=:M") <= chars


def test_section_bar_is_not_text_but_hyphen_is():
    def rect(w, h):
        pts = [(0, 0), (w, 0), (w, h), (0, h), (0, 0)]
        return Glyph((0, 0, w, h), [pts])

    assert is_section_bar(rect(10.0, 1.0))  # Endbalken eines Schnittverlaufs
    assert not is_section_bar(rect(1.32, 0.43))  # Bindestrich in „A-A“


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_texts_match_drawing(name):
    pdf = SAMPLES / name / f"{name}_dwg.pdf"
    if not pdf.exists():
        pytest.skip(f"Beispielzeichnung fehlt: {pdf}")
    texts = sorted(t.text for t in extract(pdf).texts)
    assert texts == EXPECTED[name]
