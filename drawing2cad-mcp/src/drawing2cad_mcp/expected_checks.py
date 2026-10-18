"""Compare calculated reference intervals with geometry and source measurements."""

from __future__ import annotations

import math


ABSOLUTE_TOLERANCE = 1e-5
RELATIVE_TOLERANCE = 1e-7


def _comparison(reference, values, *, field, tolerance=None):
    if reference.get("kind") not in {"exact", "bound"}:
        return {"status": "not_tested", "reason": reference.get("reason", "No calculation rule is available.")}
    if field == "volume":
        low = [reference["value"] if reference["kind"] == "exact" else reference["lower"]]
        high = [reference["value"] if reference["kind"] == "exact" else reference["upper"]]
    else:
        low = reference["size"] if reference["kind"] == "exact" else reference["lower"]
        high = reference["size"] if reference["kind"] == "exact" else reference["upper"]
    tolerances = [max(ABSOLUTE_TOLERANCE, max(abs(a), abs(b)) * RELATIVE_TOLERANCE,
                      tolerance or 0.0) for a, b in zip(low, high)]
    if len(values) != len(low) or not all(math.isfinite(v) for v in values):
        return {"status": "fail", "reason": "The measured values are missing or not finite."}
    differences = [max(a - v, v - b, 0.0) for a, b, v in zip(low, high, values)]
    return {"status": "pass" if all(d <= t for d, t in zip(differences, tolerances)) else "fail",
            "difference": differences, "tolerance": tolerances, "lower": low, "upper": high}


def compare_expected(reference: dict, measured: dict, measurements=()) -> list[dict]:
    """Retain source expectations and report their agreement as separate checks.

    A bound is an interval test, not proof of an exact value. The feature ID
    identifies the state after the corresponding operation.
    """
    checks = []
    for field, actual in (("volume", [measured["volume_mm3"]]), ("bbox", measured["bbox_size"])):
        computed = reference[field]
        common = {"feature_id": reference["feature_id"], "quantity": field,
                  "unit": "mm3" if field == "volume" else "mm", "computed": computed,
                  "build": actual}
        result = _comparison(computed, actual, field=field)
        # Extents must agree in position as well as size.
        if field == "bbox" and computed.get("kind") in {"exact", "bound"}:
            outside = []
            extent_tolerance = []
            for side in ("min", "max"):
                for expected, value in zip(computed[side], measured["bbox_" + side]):
                    if computed["kind"] == "exact":
                        distance = abs(expected - value)
                    else:
                        distance = max(expected - value if side == "min" else value - expected, 0.0)
                    outside.append(distance)
                    extent_tolerance.append(max(ABSOLUTE_TOLERANCE, abs(expected) * RELATIVE_TOLERANCE))
            result.update(extent_difference=outside, extent_tolerance=extent_tolerance)
            if any(not math.isfinite(d) or d > t for d, t in zip(outside, extent_tolerance)):
                result["status"] = "fail"
        checks.append({"check": "computed_" + field, **common, **result})
        for measurement in measurements:
            if measurement.kind != field:
                continue
            result = _comparison(computed, measurement.expected, field=field, tolerance=measurement.tolerance)
            checks.append({"check": "computed_agent_" + field, **common, **result,
                           "measurement_id": measurement.id, "agent_expected": list(measurement.expected),
                           "agent_build_difference": [abs(a - b) for a, b in zip(actual, measurement.expected)],
                           "evidence_ids": list(measurement.evidence_ids), "basis": measurement.basis})
    return checks
