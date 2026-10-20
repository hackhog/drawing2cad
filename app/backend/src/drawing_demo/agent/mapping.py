"""Map domain part state, artifacts, and agent trace events to the provisional contract types (ADR 0015, ADR 0018).

The domain service owns the domain data. This module only presents it; it adds no CAD, drawing, or release rule.
"""

from __future__ import annotations

from typing import Any

PHASE_BY_TOOL = {
    "pdf_info": "analyzing", "pdf_read_text": "analyzing", "pdf_render_page": "analyzing", "pdf_crop_region": "analyzing",
    "drawing_extract": "analyzing", "pdf_calibrate": "analyzing", "pdf_measure_distance": "analyzing",
    "pdf_measure_circle": "analyzing",
    # part_schema and part_read only read; they keep the current phase like the status and probe calls.
    "part_validate": "modeling", "part_create": "modeling", "part_update": "modeling", "create_base_body": "modeling", "add_hole": "modeling", "add_pocket": "modeling",
    "add_cut": "modeling", "add_chamfer": "modeling", "add_fillet": "modeling", "build_from_description": "modeling",
    "drawing_schema": "drawing", "drawing_derive_views": "drawing", "drawing_verify": "drawing", "drawing_validate": "drawing", "drawing_render": "drawing", "drawing_review": "drawing",
    "artifact_preview": "drawing",
    # part_export_review only exports the current state; it keeps the phase, so a failed build stays in "modeling".
    # model_projection_check only reads the validated build and does not gate the release; it keeps the phase.
    "export_step": "validating",
}
# Domain artifact roles that the web UI delivers. Previews of sources and artifacts are inspection aids only.
ROLE_BY_MEDIA_TYPE = {("released_step", "model/step"): "step", ("technical_drawing", "application/pdf"): "drawing_pdf",
                      ("drawing_diagnostic_preview", "application/pdf"): "drawing_diagnostic",
                      ("technical_drawing", "image/vnd.dxf"): "drawing_dxf",
                      ("part_description", "application/json"): "part_description",
                      ("run_manifest", "application/json"): "manifest", ("run_trace", "application/json"): "trace",
                      ("domain_run_events", "application/json"): "events"}

ORIGIN_BY_EVIDENCE = {"explicit": "source", "derived": "source", "inferred": "assumed", "assumed": "assumed", "unresolved": "assumed"}
CHECK_STATUS = {"pass": "pass", "fail": "fail"}
MM_PER_POINT = 25.4 / 72


def phase_for(tool_name: str | None, current: str) -> str:
    """Phase of the run after a tool request. Status and probe calls keep the current phase."""
    return PHASE_BY_TOOL.get(tool_name or "", current)


def sheet_region(source: dict[str, Any] | None, sheet_mm: tuple[float, float]) -> list[float] | None:
    """Convert an MCP source region to sheet millimeters (Y down), if the coordinate system permits it."""
    if not source or "region" not in source:
        return None
    x0, y0, x1, y1 = source["region"]
    system = source.get("coordinate_system", "pdf_points")
    if system == "normalized_displayed":
        width, height = sheet_mm
        return [x0 * width, y0 * height, x1 * width, y1 * height]
    if system == "pdf_points":
        return [x0 * MM_PER_POINT, y0 * MM_PER_POINT, x1 * MM_PER_POINT, y1 * MM_PER_POINT]
    return None  # Pixel regions need the render DPI, which the state does not record.


def _scalar_names(value: Any) -> list[str]:
    if isinstance(value, dict) and set(value) == {"parameter"}:
        return [value["parameter"]]
    if isinstance(value, (list, tuple)):
        return [name for item in value for name in _scalar_names(item)]
    if isinstance(value, dict):
        return [name for item in value.values() for name in _scalar_names(item)]
    return []


def part_view(state: dict[str, Any]) -> dict[str, Any]:
    """Named parameters and ordered operations of the current description."""
    description = state.get("description") or {}
    evidence = {item["id"]: item for item in description.get("evidence", [])}
    parameters = []
    for parameter in description.get("parameters", []):
        statuses = [evidence.get(i, {}).get("status", "explicit") for i in parameter.get("evidence_ids", [])]
        origin = "assumed" if any(ORIGIN_BY_EVIDENCE.get(s) == "assumed" for s in statuses) else "source"
        unit = parameter.get("unit", "mm")
        parameters.append({
            "name": parameter["name"], "value": parameter.get("value"), "unit": "" if unit == "dimensionless" else unit,
            "origin": origin, "editable": False, "feature": "",
        })
    operations = []
    for index, feature in enumerate(description.get("features", []), start=1):
        names = sorted(set(_scalar_names({k: v for k, v in feature.items() if k not in ("id", "evidence_ids")})))
        for parameter in parameters:
            if parameter["name"] in names and not parameter["feature"]:
                parameter["feature"] = feature["id"]
        operations.append({"index": index, "kind": feature.get("type", "feature"), "label": feature["id"], "parameters": names})
    return {"revision": state.get("revision", 1), "parameters": parameters, "operations": operations,
            "capabilities": {"parameter_edit": False}}


def review_view(state: dict[str, Any], review_items: list[dict[str, Any]], sheet_mm: tuple[float, float],
                released: bool) -> dict[str, Any]:
    """Release state, assumptions, uncertainty markers, and validation results of the MCP state."""
    evidence = {item["id"]: item for item in (state.get("description") or {}).get("evidence", [])}
    assumptions, uncertainties = [], []
    for item in review_items:
        if "target_id" in item:  # A review flag. Its location comes from its first evidence item.
            first = evidence.get((item.get("evidence_ids") or [None])[0], {})
            if item.get("status") != "accepted":
                uncertainties.append({"id": item["id"], "feature": item["target_id"], "message": item["reason"],
                                      "source_region": sheet_region(first.get("source"), sheet_mm)})
            continue
        entry = {"id": item["id"], "feature": item.get("source", {}).get("view", ""), "parameter": None, "value": 0, "unit": "",
                 "reason": item["reason"], "source_region": sheet_region(item.get("source"), sheet_mm)}
        if item.get("status") == "unresolved":
            uncertainties.append({"id": entry["id"], "feature": entry["feature"], "message": entry["reason"],
                                  "source_region": entry["source_region"]})
        else:
            assumptions.append(entry)
    build = state.get("build") or {}
    checks = (build.get("validation") or {}).get("checks", [])
    validation = [{"check": c["check"], "status": CHECK_STATUS.get(c.get("status"), "not_tested"),
                   "detail": str(c.get("detail") or c.get("message") or c.get("observed") or "")} for c in checks]
    if released:
        release_state = "released"
    elif build.get("status") == "pass":
        release_state = "blocked"
    else:
        release_state = "draft"
    # The STEP release records the drawing status. The drawing does not gate the release.
    recorded = (state.get("release") or {}).get("drawing") if released else None
    drawing = ({"status": recorded["status"], "reason": recorded.get("reason"),
                "current": bool((state.get("release") or {}).get("drawing_current", True))} if recorded else None)
    return {"release_state": release_state, "assumptions": assumptions, "uncertainties": uncertainties, "validation": validation,
            "drawing": drawing}


def artifact_view(artifact: dict[str, Any], source_sha256: str, released_ids: frozenset[str] = frozenset()) -> dict[str, Any] | None:
    """A domain artifact as a delivered web artifact, or None for an artifact that the UI does not deliver.
    released_ids are the STEP and drawing artifacts that the current release names."""
    media_type = artifact["media_type"]
    role = ROLE_BY_MEDIA_TYPE.get((artifact["role"], media_type)) or ("report" if media_type == "application/json" else None)
    if role is None:
        return None
    return {"artifact_id": artifact["artifact_id"], "role": role, "media_type": media_type, "filename": artifact["filename"],
            "sha256": artifact["sha256"], "byte_count": artifact["size_bytes"], "source_sha256": source_sha256,
            "model_revision": artifact["revision"], "released": artifact["artifact_id"] in released_ids}
