"""Report measured vector circles and conservative dimension candidates.

A circular outline does not prove a hole. These records require a source review.
Confidence values are rule scores. They are not calibrated probabilities.
"""

from __future__ import annotations

import re

from .model import Arc, Drawing, Kind

_DIMENSION = re.compile(r"^(?P<prefix>[Ø⌀RM])?\s*(?P<value>\d+(?:[.,]\d+)?)\s*(?P<degree>°)?$")


def normalized_box(box, sheet):
    return [round(box[0] / sheet[0], 6), round(box[1] / sheet[1], 6),
            round(box[2] / sheet[0], 6), round(box[3] / sheet[1], 6)]


def circles(drawing: Drawing) -> list[dict]:
    records = []
    for stroke in drawing.strokes:
        geometry = stroke.geom
        if not isinstance(geometry, Arc) or not geometry.is_circle:
            continue
        records.append({
            "id": f"circle-{stroke.id}", "stroke_id": stroke.id,
            "source_path_id": stroke.path_id, "center_sheet_mm": list(geometry.center),
            "diameter_sheet_mm": geometry.radius * 2,
            "bbox_normalized": normalized_box(geometry.bbox(), drawing.sheet_size_mm),
            "geometry_confidence": 0.95,
            "confidence_basis": "Full circular vector path within the arc fit tolerance.",
            "kind": stroke.kind.value,
            "hole_candidate": stroke.kind in (Kind.CONTOUR, Kind.UNCLEAR, Kind.HIDDEN),
            "hole_confidence": 0.5 if stroke.kind is Kind.CONTOUR else 0.25,
            "semantic_status": "unverified",
            "limitations": "A circle can show a hole, boss, outer edge, or symbol. Depth is unknown.",
        })
    return records


def dimensions(drawing: Drawing) -> list[dict]:
    records = []
    for text in drawing.texts:
        match = _DIMENSION.fullmatch(text.text.strip())
        if not match:
            continue
        prefix, degree = match["prefix"], match["degree"]
        kind = "angle" if degree else {"Ø": "diameter", "⌀": "diameter", "R": "radius",
                                       "M": "thread_nominal"}.get(prefix, "linear")
        records.append({
            "id": f"dimension-{text.id}", "text_id": text.id, "text": text.text,
            "value": float(match["value"].replace(",", ".")), "kind": kind,
            "unit": "degree" if degree else "unspecified",
            "bbox_sheet_mm": list(text.bbox),
            "bbox_normalized": normalized_box(text.bbox, drawing.sheet_size_mm),
            "confidence": text.confidence, "method": text.method,
            "semantic_status": "unverified", "geometry_association": None,
        })
    return records
