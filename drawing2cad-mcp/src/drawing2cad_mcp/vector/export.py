"""Serialize vector analysis results as JSON-compatible data."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .model import Arc, Drawing, Stroke

SCHEMA_VERSION = 2  # Version 2 adds recognized text and reading direction.


def _r(v: float) -> float:
    return round(v, 3)


def _stroke(s: Stroke) -> dict[str, Any]:
    g = s.geom
    base: dict[str, Any] = {"id": s.id, "kind": s.kind.value, "width_mm": _r(s.width_mm)}
    if isinstance(g, Arc):
        base |= {
            "type": "circle" if g.is_circle else "arc",
            "center": [_r(g.center[0]), _r(g.center[1])],
            "radius": _r(g.radius),
        }
        if not g.is_circle:
            base |= {"start_deg": _r(g.start_deg), "sweep_deg": _r(g.sweep_deg)}
    else:
        base |= {"type": "line", "p0": [_r(g.p0[0]), _r(g.p0[1])], "p1": [_r(g.p1[0]), _r(g.p1[1])]}
    return base


def to_dict(d: Drawing) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source": d.source,
        "units": "mm, sheet coordinates, origin at top left, positive y down",
        "sheet_size_mm": [_r(v) for v in d.sheet_size_mm],
        "raster_image_bbox": [_r(v) for v in d.raster_bbox] if d.raster_bbox else None,
        "summary": {
            "strokes": len(d.strokes),
            "by_kind": dict(sorted(Counter(s.kind.value for s in d.strokes).items())),
            "views": len(d.views),
            "text_blocks": len(d.texts),
        },
        "views": [
            {"id": v.id, "bbox": [_r(x) for x in v.bbox], "is_iso": v.is_iso, "stroke_ids": v.stroke_ids}
            for v in d.views
        ],
        "text_blocks": [
            {"id": t.id, "text": t.text, "angle_deg": t.angle_deg, "bbox": [_r(x) for x in t.bbox],
             "glyph_count": t.glyph_count}
            for t in d.texts
        ],
        "strokes": [_stroke(s) for s in d.strokes],
    }
