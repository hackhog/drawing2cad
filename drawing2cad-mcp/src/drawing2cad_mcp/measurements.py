"""Calibrate drawing observations with two independently printed dimensions.

This module measures supplied observations. It does not recognize dimensions or
prove their association with a feature. A calibration applies to one view only.
"""

from __future__ import annotations

import math
from typing import Any


class MeasurementError(ValueError):
    """A measurement has invalid, inconsistent, or incomplete evidence."""


def _number(value: Any, label: str, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise MeasurementError(f"{label} must be a finite number.")
    if abs(value) > 1e12:
        raise MeasurementError(f"{label} exceeds the supported numeric range.")
    if positive and value <= 0:
        raise MeasurementError(f"{label} must be positive.")
    return float(value)


def _point(value: Any) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise MeasurementError("A point must contain two coordinates.")
    return _number(value[0], "x"), _number(value[1], "y")


def _region(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise MeasurementError("source_region must contain four normalized coordinates.")
    left, top, right, bottom = [_number(v, "source_region coordinate") for v in value]
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise MeasurementError("source_region must be inside the displayed page and have a positive area.")
    return [left, top, right, bottom]


def calibration_defects(references: Any) -> list[tuple[str, str]]:
    """Return the semantic defects of calibration references as (JSON Pointer, message).
    The schema checks types and ranges. This check finds defects that the schema cannot express.
    It never raises and never repeats an input value."""
    defects = []
    if not isinstance(references, list):
        return defects
    for index, reference in enumerate(references):
        if not isinstance(reference, dict):
            continue
        p0, p1 = reference.get("p0"), reference.get("p1")
        try:
            if _point(p0) == _point(p1):
                defects.append((f"/references/{index}/p1", "The reference endpoints p0 and p1 are equal. "
                                "Use the two different endpoints of the printed dimension, read from drawing_extract vectors or from a page image with crop_context."))
        except MeasurementError:
            pass
        region = reference.get("source_region")
        if isinstance(region, (list, tuple)) and len(region) == 4 and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in region):
            left, top, right, bottom = region
            if not (left < right and top < bottom):
                defects.append((f"/references/{index}/source_region", "source_region needs left < right and top < bottom. "
                                "source_region is [left, top, right, bottom] as fractions 0..1 of the displayed page, from its top-left corner."))
    return defects


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise MeasurementError(f"{label} must be nonempty text with at most 500 characters.")
    return value


def calibrate(
    source_sha256: str, page: int, references: list[dict], coordinate_space: str = "sheet_mm",
    relative_tolerance: float = 0.02, crop_context: dict | None = None, view_id: str = "view-1",
) -> dict:
    """Return a scale only when two distinct printed references agree.

    The caller must identify both observations as printed dimensions. This
    declaration remains evidence to review, not proof from PDF interpretation.
    """
    if coordinate_space not in ("sheet_mm", "pixels"):
        raise MeasurementError("coordinate_space must be sheet_mm or pixels.")
    _text(view_id, "view_id")
    tolerance = _number(relative_tolerance, "relative_tolerance", True)
    if tolerance > 0.05:
        raise MeasurementError("relative_tolerance must not exceed 0.05.")
    if not isinstance(references, list) or len(references) != 2:
        raise MeasurementError("Exactly two independent printed dimensions are required.")
    defects = calibration_defects(references)
    if defects:
        # Report all reference defects together, so that the agent can correct them in one retry.
        raise MeasurementError(" ".join(f"{target}: {message}" for target, message in defects))
    context = None
    if coordinate_space == "pixels":
        if not isinstance(crop_context, dict):
            raise MeasurementError("Pixel observations require crop_context from the PDF render or crop.")
        size, box = crop_context.get("full_page_pixels"), crop_context.get("pixel_bbox")
        if not isinstance(size, list) or len(size) != 2 or not isinstance(box, list) or len(box) != 4:
            raise MeasurementError("crop_context requires full_page_pixels and pixel_bbox.")
        if any(isinstance(v, bool) or not isinstance(v, int) for v in size + box):
            raise MeasurementError("Pixel context values must be integers.")
        if not (0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1]):
            raise MeasurementError("pixel_bbox must be inside full_page_pixels.")
        context = {"full_page_pixels": size, "pixel_bbox": box}
    elif crop_context is not None:
        raise MeasurementError("crop_context is only valid for pixel observations.")
    normalized = []
    for reference in references:
        if not isinstance(reference, dict) or reference.get("evidence") != "printed_dimension":
            raise MeasurementError("Each reference must declare evidence=printed_dimension.")
        identifier = _text(reference.get("dimension_id"), "dimension_id")
        value = _number(reference.get("printed_value_mm"), "printed_value_mm", True)
        p0, p1 = _point(reference.get("p0")), _point(reference.get("p1"))
        length = math.dist(p0, p1)
        if length <= 1e-9:
            raise MeasurementError("Reference endpoints must be distinct.")
        normalized.append({"dimension_id": identifier, "printed_value_mm": value,
                           "p0": list(p0), "p1": list(p1), "evidence": "printed_dimension",
                           "source_region": _region(reference.get("source_region")),
                           "observed_length": length, "mm_per_coordinate_unit": value / length})
    first, second = normalized
    if (first["dimension_id"] == second["dimension_id"]
            or first["source_region"] == second["source_region"]
            or {tuple(first["p0"]), tuple(first["p1"])} == {tuple(second["p0"]), tuple(second["p1"])}):
        raise MeasurementError("Calibration references must use distinct dimensions, regions, and segments.")
    scales = [reference["mm_per_coordinate_unit"] for reference in normalized]
    error = abs(scales[0] - scales[1]) / max(scales)
    if error > tolerance:
        raise MeasurementError(f"Printed dimensions give inconsistent scales (relative difference {error:.6g}).")
    result = {"schema_version": 1, "source_sha256": source_sha256, "page": page, "view_id": view_id,
              "coordinate_space": coordinate_space, "references": normalized,
              "relative_tolerance": tolerance, "relative_scale_difference": error,
              "mm_per_coordinate_unit": sum(scales) / 2, "crop_context": context,
              "status": "calibrated_from_supplied_observations",
              "limitations": ["Only the named view is calibrated. Do not transfer the scale to another view.",
                              "The supplied printed dimensions and their endpoints require visual verification.",
                              "A measured value is an estimate, not a printed manufacturing dimension."]}
    for reference in normalized:
        _validate_points(result, [reference["p0"], reference["p1"]])
    return result


def validate_calibration(calibration: Any, source_sha256: str, page: int) -> dict:
    """Recalculate supplied scale data and reject a changed source or page."""
    if not isinstance(calibration, dict) or calibration.get("schema_version") != 1:
        raise MeasurementError("A schema version 1 calibration is required.")
    if (calibration.get("source_sha256") != source_sha256 or calibration.get("page") != page
            or isinstance(calibration.get("page"), bool)):
        raise MeasurementError("Calibration source hash or page does not match the current PDF.")
    result = calibrate(source_sha256, page, calibration.get("references"),
                       calibration.get("coordinate_space"), calibration.get("relative_tolerance"),
                       calibration.get("crop_context"), calibration.get("view_id"))
    scale = _number(calibration.get("mm_per_coordinate_unit"), "mm_per_coordinate_unit", True)
    if not math.isclose(scale, result["mm_per_coordinate_unit"], rel_tol=1e-10):
        raise MeasurementError("Calibration scale does not match its printed references.")
    return result


def _validate_points(calibration: dict, points: list) -> None:
    if calibration["coordinate_space"] != "pixels":
        return
    left, top, right, bottom = calibration["crop_context"]["pixel_bbox"]
    if any(not (0 <= p[0] <= right - left and 0 <= p[1] <= bottom - top) for p in points):
        raise MeasurementError("Pixel observations must use local coordinates inside the registered crop.")


def _evidence(evidence: Any, calibration: dict) -> dict:
    if not isinstance(evidence, dict):
        raise MeasurementError("Measurement evidence is required.")
    expected = "vector" if calibration["coordinate_space"] == "sheet_mm" else "pixel_observation"
    if evidence.get("origin") != expected:
        raise MeasurementError(f"This calibration requires evidence origin={expected}.")
    if evidence.get("view_id") != calibration["view_id"]:
        raise MeasurementError("Measurement view_id does not match the calibration.")
    return {"origin": expected, "view_id": calibration["view_id"],
            "source_region": _region(evidence.get("source_region")),
            "reason": _text(evidence.get("reason"), "reason")}


def _base(calibration: dict, evidence: dict) -> dict:
    return {"source_sha256": calibration["source_sha256"], "page": calibration["page"],
            "view_id": calibration["view_id"], "units": "mm", "status": "estimated",
            "calibration": calibration, "evidence": _evidence(evidence, calibration),
            "coordinate_space": calibration["coordinate_space"]}


def distance(calibration: dict, p0: list, p1: list, evidence: dict) -> dict:
    """Convert the distance between two vector or pixel observations to mm."""
    a, b = _point(p0), _point(p1)
    _validate_points(calibration, [a, b])
    observed = math.dist(a, b)
    return {**_base(calibration, evidence), "measurement": "distance", "p0": list(a), "p1": list(b),
            "observed_distance": observed, "distance_mm": observed * calibration["mm_per_coordinate_unit"]}


def circle(calibration: dict, points: list, evidence: dict, relative_tolerance: float = 0.02) -> dict:
    """Fit a circle to 3 to 256 observations. Reject noncircular samples."""
    if not isinstance(points, list) or not 3 <= len(points) <= 256:
        raise MeasurementError("A circle requires 3 to 256 points.")
    pts = [_point(p) for p in points]
    if len(set(pts)) != len(pts):
        raise MeasurementError("Circle observations must be distinct.")
    _validate_points(calibration, pts)
    tolerance = _number(relative_tolerance, "relative_tolerance", True)
    if tolerance > 0.05:
        raise MeasurementError("relative_tolerance must not exceed 0.05.")
    # Center the input to reduce cancellation for large page coordinates.
    mx, my = (sum(p[i] for p in pts) / len(pts) for i in (0, 1))
    centered = [(x - mx, y - my) for x, y in pts]
    xx = sum(x * x for x, _ in centered)
    yy = sum(y * y for _, y in centered)
    xy = sum(x * y for x, y in centered)
    determinant = xx * yy - xy * xy
    if determinant <= max(xx * yy, 1e-30) * 1e-10:
        raise MeasurementError("Circle observations are collinear or numerically unstable.")
    bx = sum(x * (x * x + y * y) for x, y in centered) / 2
    by = sum(y * (x * x + y * y) for x, y in centered) / 2
    center = (mx + (bx * yy - by * xy) / determinant,
              my + (by * xx - bx * xy) / determinant)
    radii = [math.dist(point, center) for point in pts]
    radius = sum(radii) / len(radii)
    residual = max(abs(value - radius) for value in radii) / radius
    if residual > tolerance:
        raise MeasurementError(f"Observations do not fit a circle (relative radial error {residual:.6g}).")
    angles = sorted(math.atan2(y - center[1], x - center[0]) % (2 * math.pi) for x, y in pts)
    gaps = [b - a for a, b in zip(angles, angles[1:] + [angles[0] + 2 * math.pi])]
    coverage = math.degrees(2 * math.pi - max(gaps))
    return {**_base(calibration, evidence), "measurement": "circle", "points": [list(p) for p in pts],
            "center_in_input_coordinates": list(center), "radius_in_input_coordinates": radius,
            "diameter_mm": radius * 2 * calibration["mm_per_coordinate_unit"],
            "relative_radial_error": residual, "angular_coverage_degrees": coverage,
            "confidence": max(0.0, (1 - residual / tolerance) * min(1, coverage / 180)),
            "confidence_basis": "Geometric fit and angular coverage; not a calibrated probability.",
            "semantic_status": "unverified", "limitations": "A circle fit does not prove a hole or its depth."}
