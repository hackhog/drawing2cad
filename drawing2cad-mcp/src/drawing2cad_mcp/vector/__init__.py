"""Deterministic vector analysis for technical drawings.

Read drawing paths, classify strokes, and group views.
The results describe the sheet, not the physical part.
"""

from __future__ import annotations

from pathlib import Path
import math

import pymupdf

from .classify import classify
from .coordinates import display_rotation
from .model import Drawing, Kind, TextBlock
from .reader import read_pdf
from .template import PT_TO_MM, in_drawing_area
from .text import read_blocks
from .views import group_views


def extract(pdf: Path, page_number: int = 1) -> Drawing:
    strokes, glyphs, sheet, raster = read_pdf(pdf, page_number)
    classify(strokes)
    views = group_views(strokes, raster)
    texts = read_blocks(glyphs, strokes)
    with pymupdf.open(pdf) as document:
        page = document[page_number - 1]
        rotation = page.rotation
        # Native text is a separate candidate source, not OCR. Existing glyph
        # candidates remain unchanged for PDFs that contain outlined text only.
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    box = tuple(value * PT_TO_MM for value in span["bbox"])
                    if span["text"].strip() and in_drawing_area(box):
                        dx, dy = line["dir"]
                        texts.append(TextBlock(len(texts) + 1, box, 0, span["text"],
                                               -math.degrees(math.atan2(dy, dx)) % 360,
                                               1.0, "native_pdf_text"))
    return display_rotation(Drawing(pdf.name, sheet, strokes, texts, views, raster), rotation)


__all__ = ["Drawing", "Kind", "extract"]
