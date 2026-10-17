"""MCP input schemas for explicit drawing observations and measurements."""

_POINT = {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}
_REGION = {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1},
           "minItems": 4, "maxItems": 4}
_REFERENCE = {
    "type": "object", "additionalProperties": False,
    "required": ["dimension_id", "printed_value_mm", "p0", "p1", "source_region", "evidence"],
    "properties": {
        "dimension_id": {"type": "string", "minLength": 1, "maxLength": 500},
        "printed_value_mm": {"type": "number", "exclusiveMinimum": 0}, "p0": _POINT, "p1": _POINT,
        "source_region": _REGION, "evidence": {"const": "printed_dimension"},
    },
}
_EVIDENCE = {
    "type": "object", "additionalProperties": False,
    "required": ["origin", "source_region", "reason", "view_id"],
    "properties": {"origin": {"enum": ["vector", "pixel_observation"]}, "source_region": _REGION,
                   "reason": {"type": "string", "minLength": 1, "maxLength": 500},
                   "view_id": {"type": "string", "minLength": 1, "maxLength": 500}},
}
_BASE = {"path": {"type": "string", "minLength": 1}, "page": {"type": "integer", "minimum": 1}}
_TOLERANCE = {"type": "number", "exclusiveMinimum": 0, "maximum": 0.05, "default": 0.02}

MEASUREMENT_SCHEMAS = {
    "pdf_calibrate": {
        "type": "object", "additionalProperties": False, "required": ["path", "page", "references"],
        "properties": {
            **_BASE, "references": {"type": "array", "items": _REFERENCE, "minItems": 2, "maxItems": 2},
            "coordinate_space": {"enum": ["sheet_mm", "pixels"], "default": "sheet_mm"},
            "relative_tolerance": _TOLERANCE,
            "view_id": {"type": "string", "minLength": 1, "maxLength": 500, "default": "view-1"},
            "crop_context": {
                "type": ["object", "null"], "additionalProperties": False,
                "required": ["full_page_pixels", "pixel_bbox"],
                "properties": {
                    "full_page_pixels": {"type": "array", "items": {"type": "integer", "minimum": 1},
                                         "minItems": 2, "maxItems": 2},
                    "pixel_bbox": {"type": "array", "items": {"type": "integer", "minimum": 0},
                                   "minItems": 4, "maxItems": 4},
                },
            },
        },
    },
    "pdf_measure_distance": {
        "type": "object", "additionalProperties": False,
        "required": ["path", "page", "p0", "p1", "calibration", "evidence"],
        "properties": {**_BASE, "p0": _POINT, "p1": _POINT,
                       "calibration": {"type": "object"}, "evidence": _EVIDENCE},
    },
    "pdf_measure_circle": {
        "type": "object", "additionalProperties": False,
        "required": ["path", "page", "points", "calibration", "evidence"],
        "properties": {**_BASE, "points": {"type": "array", "items": _POINT, "minItems": 3, "maxItems": 256},
                       "calibration": {"type": "object"}, "evidence": _EVIDENCE,
                       "relative_tolerance": _TOLERANCE},
    },
}

MEASUREMENT_DESCRIPTIONS = {
    "pdf_calibrate": "Calibrate one view with two distinct printed dimensions. Prefer vector sheet-mm points. "
                     "For pixel points, supply local crop coordinates and the exact render/crop pixel context. "
                     "Reject inconsistent scales. Never infer part scale from the PDF page size. "
                     "All source regions use normalized displayed-page coordinates.",
    "pdf_measure_distance": "Measure two supplied vector or pixel observations using a calibration from the same "
                            "source hash, page, and view. Return an estimated distance in mm with evidence.",
    "pdf_measure_circle": "Fit 3 to 256 supplied vector or pixel points using a source-bound calibration. "
                          "Return an estimated diameter in mm and fit confidence. A circle does not prove a hole.",
}

MEASUREMENT_METHODS = {"pdf_calibrate": "calibrate", "pdf_measure_distance": "measure_distance",
                       "pdf_measure_circle": "measure_circle"}
