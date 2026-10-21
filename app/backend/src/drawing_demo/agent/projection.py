"""Present the newest source-projection report without changing its checks or limits."""

from __future__ import annotations

import json
import math
from typing import Any

from ..service import DomainBackend, ServiceError


MAX_REPORT_BYTES = 1024 * 1024


def not_tested(revision: int | None = None, reason: str = "No projection check exists for the current revision.") -> dict[str, Any]:
    return {"status": "not_tested", "revision": revision, "reason": reason, "report_artifact_id": None,
            "overlay_artifact_id": None, "page": None, "sheet_size_mm": None, "views": []}


def _number(value: Any, *, minimum: float = 0) -> float | None:
    return float(value) if type(value) in (int, float) and math.isfinite(value) and value >= minimum else None


def projection_view(report: dict[str, Any], revision: int, sheet: tuple[float, float],
                    report_id: str, overlay_id: str | None) -> dict[str, Any]:
    """Map recorded per-view results. An untested or incomplete view never counts as a pass."""
    views = []
    for view in report.get("views", []):
        region = view.get("region_sheet_mm")
        if (not isinstance(region, list) or len(region) != 4 or any(_number(n) is None for n in region)
                or not (region[0] < region[2] and region[1] < region[3])):
            return not_tested(revision, "The projection report has an invalid view region.")
        model, drawing, limits = view.get("model_to_drawing") or {}, view.get("drawing_to_model") or {}, view.get("limits") or {}
        metrics = {"p95_mm": _number(model.get("p95_mm")), "max_mm": _number(model.get("max_mm")),
                   "coverage": _number(drawing.get("coverage"))}
        bounds = {key: _number(limits.get(key)) for key in ("p95_mm", "max_mm", "coverage_min")}
        complete = all(n is not None for n in (*metrics.values(), *bounds.values()))
        checks = {key: value if value in {"pass", "fail"} else "not_tested"
                  for key, value in ((key, (view.get("checks") or {}).get(key)) for key in ("p95", "max", "coverage"))}
        status = view.get("status") if view.get("status") in {"pass", "fail", "not_tested"} else "not_tested"
        if status == "pass" and (not complete or any(value != "pass" for value in checks.values())):
            status = "not_tested"
        views.append({"view_id": str(view.get("view_id", "View")), "status": status,
                      "reason": view.get("reason"), "region_sheet_mm": region, "metrics": metrics, "limits": bounds,
                      "checks": checks,
                      "max_capped": bool(model.get("max_capped"))})
    status = ("deviates" if any(v["status"] == "fail" for v in views) else
              "matches" if views and report.get("status") == "pass" and all(v["status"] == "pass" for v in views) else "not_tested")
    return {"status": status, "revision": revision, "reason": None if status != "not_tested" else "The projection check is incomplete.",
            "report_artifact_id": report_id, "overlay_artifact_id": overlay_id,
            "page": report["page"], "sheet_size_mm": list(sheet), "views": views}


def projection_result(backend: DomainBackend, listed: list[dict[str, Any]], run_id: str, revision: int,
                      source: dict[str, Any], sheet: tuple[float, float]) -> dict[str, Any]:
    """Read current-revision evidence through the domain service, including its artifact hash checks."""
    reports = [a for a in listed if a["role"] == "projection_report" and a["revision"] == revision]
    if not reports:
        stale = any(a["role"] == "projection_report" for a in listed)
        return not_tested(revision, "The projection check belongs to an older revision." if stale else
                          "No projection check exists for the current revision.")
    selected = reports[-1]
    if selected["size_bytes"] > MAX_REPORT_BYTES:
        return not_tested(revision, "The projection report exceeds the display limit.")
    try:
        _, data = backend.artifact_bytes(selected["artifact_id"])
        report = json.loads(data)
        if (report.get("revision") != revision or report.get("run_id") != run_id
                or report.get("source_sha256") != source["sha256"]):
            return not_tested(revision, "The projection report does not match this revision and source drawing.")
        page = report.get("page")
        if type(page) is not int or page < 1:
            return not_tested(revision, "The projection report has no valid source page.")
        if page != 1:
            info = backend.call("pdf_info", source_id=source["source_id"])
            if info["source"]["sha256"] != source["sha256"]:
                return not_tested(revision, "The source page does not match the projection report.")
            size = info["pages"][page - 1]
            box = size["effective_cropbox_points"]
            sheet = ((box[2] - box[0]) * 25.4 / 72, (box[3] - box[1]) * 25.4 / 72)
            if size["rotation_degrees"] in {90, 270}:
                sheet = sheet[::-1]
        # The MCP registers the overlay immediately before its report, without a stored report-to-overlay link.
        # Stop at the preceding report so that a missing overlay cannot select one from another check.
        overlay = None
        for item in reversed(listed[:listed.index(selected)]):
            if item["role"] == "projection_report":
                break
            if item["role"] == "projection_overlay" and item["revision"] == revision:
                overlay = item["artifact_id"]
                break
        return projection_view(report, revision, sheet, selected["artifact_id"], overlay)
    except (ServiceError, ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
        return not_tested(revision, "The newest projection report could not be read. Repeat the check before accepting source agreement.")
