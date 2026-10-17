"""Deterministic vector analysis for technical drawings.

Read drawing paths, classify strokes, and group views.
The results describe the sheet, not the physical part.
"""

from __future__ import annotations

from pathlib import Path

from .classify import classify
from .model import Drawing, Kind
from .reader import read_pdf
from .text import read_blocks
from .views import group_views


def extract(pdf: Path) -> Drawing:
    strokes, glyphs, sheet, raster = read_pdf(pdf)
    classify(strokes)
    views = group_views(strokes, raster)
    return Drawing(pdf.name, sheet, strokes, read_blocks(glyphs, strokes), views, raster)


__all__ = ["Drawing", "Kind", "extract"]
