"""Render supplied 2D geometry as native DXF dimensions and a matching PDF."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .drawing_contract import _inside, _overlap, description_digest, drawing_validate


def _layout_diagnostics(labels: list[dict[str, Any]], affected_ids: set[str] | None = None) -> dict[str, Any]:
    """Bound the diagnostic payload and the work needed to compare text boxes."""
    pairs = []
    count = 0
    comparisons = 0
    complete = True
    ordered = sorted(labels, key=lambda item: item["bounds_mm"][0])
    for index, first in enumerate(ordered):
        for second in ordered[index + 1:]:
            if second["bounds_mm"][0] >= first["bounds_mm"][2] - 0.05:
                break
            if comparisons >= 250000:
                complete = False
                break
            comparisons += 1
            if _overlap(first["bounds_mm"], second["bounds_mm"]):
                count += 1
                if len(pairs) < 100:
                    pairs.append({"first_id": first["id"], "second_id": second["id"],
                                  "first_source_id": first["source_id"], "second_source_id": second["source_id"],
                                  "first_bounds_mm": first["bounds_mm"], "second_bounds_mm": second["bounds_mm"]})
        if not complete:
            break
    involved = {pair[side + "_id"] for pair in pairs for side in ("first", "second")}
    selected = [label for label in labels if label["id"] in involved or label["source_id"] in (affected_ids or set())]
    return {"schema_version": "1.0", "coordinate_system": {"units": "mm", "origin": "bottom_left", "positive_y": "up"},
            "bounds_source": "ezdxf_rendered_text", "labels": selected[:100], "total_labels": len(labels),
            "relevant_labels": len(selected), "reported_labels": min(100, len(selected)),
            "collision_pairs": pairs, "reported_collision_pairs": len(pairs),
            "detected_collision_pairs": count, "total_collision_pairs": count if complete else None,
            "scanned_pair_count": comparisons, "scan_complete": complete,
            "truncated": len(selected) > 100 or count > len(pairs) or not complete}


def _diagnostic_pdf(pdf: bytes, sheet: dict[str, Any], report: dict[str, Any]) -> bytes:
    """Mark the failed sheet and add a readable source-ID legend."""
    import pymupdf

    document = pymupdf.open(stream=pdf, filetype="pdf")
    page = document[0]
    scale = page.rect.width / sheet["width"]
    pairs = report["diagnostics"]["collision_pairs"]
    labels = {item["id"]: item for item in report["diagnostics"]["labels"]}
    marked = {}
    for pair in pairs:
        for side in ("first", "second"):
            marked.setdefault(pair[side + "_id"], pair[side + "_bounds_mm"])
    # Clipped labels and conservative-layout failures can have no rendered pair.
    affected = {item.get("id") for item in report["defects"]}
    for identifier, label in labels.items():
        if label["source_id"] in affected:
            marked.setdefault(identifier, label["bounds_mm"])
    for number, (identifier, bounds) in enumerate(marked.items(), 1):
        x0, y0, x1, y1 = bounds
        rect = pymupdf.Rect(x0 * scale, (sheet["height"] - y1) * scale,
                           x1 * scale, (sheet["height"] - y0) * scale)
        if not rect.is_empty:
            page.draw_rect(rect, color=(1, 0, 0), width=0.7, overlay=True)
            page.insert_text((max(2, min(rect.x0, page.rect.width - 30)),
                              max(12, min(rect.y0 - 2, page.rect.height - 3))),
                             str(number), fontsize=7, color=(1, 0, 0), overlay=True)
    banner = "DIAGNOSTIC ONLY - FAILED DRAWING - NOT FOR RELEASE"
    for item in document:
        item.draw_rect(pymupdf.Rect(0, 0, item.rect.width, 18), color=None, fill=(1, 0.92, 0.92), overlay=True)
        item.insert_text((6, 12), banner, fontsize=9, color=(0.8, 0, 0), overlay=True)
    lines = ["Coordinates: sheet mm; bottom-left origin; positive Y up.",
             "Red boxes identify rendered text bounds. Numbers refer to source labels.",
             "Only reported collisions are marked. Read the JSON report for counts and limits."]
    for number, (identifier, bounds) in enumerate(marked.items(), 1):
        lines.append(f"{number}: {identifier} | bounds: " + ", ".join(f"{value:.3f}" for value in bounds))
    lines.extend(f"{item['code']}: {item.get('id', 'drawing')}" for item in report["defects"])
    for offset in range(0, len(lines), 44):
        legend = document.new_page(width=842, height=595)
        legend.insert_text((18, 22), banner, fontsize=10, color=(0.8, 0, 0))
        legend.insert_text((18, 42), "\n".join(lines[offset:offset + 44]), fontsize=8, lineheight=1.4)
    data = document.tobytes(garbage=4, deflate=True)
    document.close()
    return data


def render_drawing(spec: dict[str, Any], description: dict[str, Any], revision: int,
                   output_dir: Path) -> dict[str, Any]:
    """Render fixed artifact names inside the restricted worker directory."""
    report = drawing_validate(spec, description, revision)
    if report["status"] != "pass" and not report.get("diagnostic_eligible", False):
        return report
    import ezdxf
    from ezdxf import bbox, disassemble, units
    from ezdxf.addons.drawing import Frontend, RenderContext, config, layout, pymupdf
    from ezdxf.enums import TextEntityAlignment
    from ezdxf.math import BoundingBox2d

    resolved = report.pop("resolved")
    sheet = resolved["sheet"]
    document = ezdxf.new("R2013", setup=True, units=units.MM)
    document.header["$MEASUREMENT"] = 1
    document.appids.add("DRAWING2CAD")
    # Sheet geometry uses mm. Explicit patterns retain visible gaps in the PDF;
    # the setup DASHED gap is only 0.254 mm, close to the default stroke width.
    document.linetypes.add("D2C_HIDDEN_MM", [3.0, 2.0, -1.0], description="Hidden edge: 2 mm dash, 1 mm gap")
    document.linetypes.add("D2C_CENTER_MM", [8.0, 5.0, -1.0, 1.0, -1.0], description="Center line: 5/1 mm dashes, 1 mm gaps")
    for name, color, linetype in (("VISIBLE", 7, "CONTINUOUS"), ("HIDDEN", 7, "D2C_HIDDEN_MM"),
                                  ("CENTER", 7, "D2C_CENTER_MM"), ("SECTION", 7, "CONTINUOUS"),
                                  ("DIMENSIONS", 7, "CONTINUOUS"), ("ANNOTATIONS", 7, "CONTINUOUS"),
                                  ("UNCERTAINTY", 1, "CONTINUOUS")):
        attrs = {"color": color, "linetype": linetype}
        if name in {"HIDDEN", "CENTER"}:
            attrs["lineweight"] = 18  # DXF line weights use hundredths of a mm.
        document.layers.new(name, dxfattribs=attrs)
    modelspace = document.modelspace()
    entity_groups = []
    native_dimensions = []
    text_sources = []

    def evidence(entity, identifier, refs, feature_ids=()):
        values = ["drawing2cad:1.0", identifier, f"part_revision:{revision}", f"description:{report['description_sha256']}"]
        values.extend("evidence:" + ref for ref in refs)
        values.extend("feature:" + ref for ref in feature_ids)
        entity.set_xdata("DRAWING2CAD", [(1000, value) for value in values])

    for view in resolved["views"]:
        entities = []
        scale = view["scale"]

        def point(p):
            return [view["origin"][i] + scale * p[i] for i in (0, 1)]

        for primitive in view["geometry"]:
            attrs = {"layer": primitive["style"].upper()}
            if primitive["type"] == "line":
                entity = modelspace.add_line(point(primitive["start"]), point(primitive["end"]), dxfattribs=attrs)
            elif primitive["type"] == "circle":
                entity = modelspace.add_circle(point(primitive["center"]), scale * primitive["radius"], dxfattribs=attrs)
            else:
                entity = modelspace.add_arc(point(primitive["center"]), scale * primitive["radius"],
                                           primitive["start_angle"], primitive["end_angle"], dxfattribs=attrs)
            evidence(entity, primitive["id"], primitive["evidence_ids"], primitive["feature_ids"])
            entities.append(entity)
        for dim in view["dimensions"]:
            label = point(dim["label_position"])
            attrs = {"layer": "DIMENSIONS"}
            overrides = {"dimtxt": sheet["text_height"], "dimasz": 1.25, "dimlfac": 1 / scale,
                         "dimdec": 4, "dimadec": 4, "dimzin": 8, "dimazin": 2, "dimtad": 0,
                         "dimgap": 0.5, "dimexe": 1.0, "dimexo": 0.5, "dimtmove": 2}
            if dim["type"] == "linear":
                result = modelspace.add_linear_dim(base=label, p1=point(dim["p1"]), p2=point(dim["p2"]),
                                                   location=label, angle=dim["angle"], override=overrides, dxfattribs=attrs)
            elif dim["type"] in {"radius", "diameter"}:
                # Keep a native leader between a moved round-dimension label
                # and its circle. DIMTMOVE=2 deliberately omits this leader.
                overrides["dimtmove"] = 1
                method = modelspace.add_radius_dim if dim["type"] == "radius" else modelspace.add_diameter_dim
                center = dim["center"]
                result = method(center=point(center), radius=dim["radius"] * scale, location=label,
                                override=overrides, dxfattribs=attrs)
            else:
                overrides["dimlfac"] = 1
                result = modelspace.add_angular_dim_3p(base=label, center=point(dim["center"]),
                                                       p1=point(dim["p1"]), p2=point(dim["p2"]),
                                                       location=label, override=overrides, dxfattribs=attrs)
            result.render()
            evidence(result.dimension, dim["id"], dim["evidence_ids"])
            native_dimensions.append(dim["id"])
            entities.append(result.dimension)
            text_sources.append((dim["id"], view["id"], "dimension", result.dimension))
        entity_groups.append((view["id"], entities, view["frame"]))

    marker_ids = {marker["id"] for marker in resolved["uncertainty_markers"]}
    for label in resolved["labels"]:
        if label["id"] in native_dimensions:
            continue
        entity = modelspace.add_text(label["text"], dxfattribs={"height": sheet["text_height"],
                                    "layer": "UNCERTAINTY" if label["id"] in marker_ids else "ANNOTATIONS"})
        entity.set_placement(label["position"], align=TextEntityAlignment.LEFT)
        view_id = next((view["id"] for view in resolved["views"]
                        if label["id"] in {view["id"] + "_label", view["id"] + "_section"}), None)
        if label["id"] in marker_ids:
            view_id = next(marker["view_id"] for marker in resolved["uncertainty_markers"] if marker["id"] == label["id"])
        text_sources.append((label["id"], view_id, "annotation", entity))
    for marker in resolved["uncertainty_markers"]:
        leader = modelspace.add_line(marker["position"], marker["target"], dxfattribs={"layer": "UNCERTAINTY"})
        evidence(leader, marker["id"], marker["evidence_ids"])
        modelspace.add_circle(marker["target"], 1.2, dxfattribs={"layer": "UNCERTAINTY"})

    defects = []
    cache = bbox.Cache()
    for identifier, entities, frame in entity_groups:
        bounds = bbox.extents(entities, cache=cache)
        if bounds.has_data and not _inside([bounds.extmin.x, bounds.extmin.y, bounds.extmax.x, bounds.extmax.y], frame):
            defects.append({"code": "rendered_view_clipping", "id": identifier,
                            "bounds_mm": [bounds.extmin.x, bounds.extmin.y, bounds.extmax.x, bounds.extmax.y],
                            "allowed_bounds_mm": frame,
                            "message": "Rendered geometry or dimension lines exceed their view frame."})
    margin = sheet["margin"]
    usable = [margin, margin, sheet["width"] - margin, sheet["height"] - margin]
    bounds = bbox.extents(modelspace, cache=cache)
    if bounds.has_data and not _inside([bounds.extmin.x, bounds.extmin.y, bounds.extmax.x, bounds.extmax.y], usable):
        defects.append({"code": "rendered_sheet_clipping", "id": "drawing", "message": "Rendered entities exceed the sheet margin.",
                        "bounds_mm": [bounds.extmin.x, bounds.extmin.y, bounds.extmax.x, bounds.extmax.y], "allowed_bounds_mm": usable})
    text_labels = []
    for identifier, view_id, kind, source in text_sources:
        texts = [entity for entity in disassemble.recursive_decompose([source]) if entity.dxftype() in {"TEXT", "MTEXT"}]
        for index, entity in enumerate(texts):
            box = bbox.extents([entity])
            if box.has_data:
                text_labels.append({"id": identifier if len(texts) == 1 else f"{identifier}/text_{index}",
                                    "source_id": identifier, "view_id": view_id, "kind": kind,
                                    "text": entity.plain_text()[:180],
                                    "bounds_mm": [box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y]})
    diagnostics = _layout_diagnostics(text_labels, {item.get("id") for item in report["defects"] + defects})
    if diagnostics["detected_collision_pairs"]:
        defects.append({"code": "rendered_label_overlap", "id": "drawing", "message": "Rendered text bounds overlap. Read diagnostics.collision_pairs for the source identifiers and sheet bounds."})
    if not diagnostics["scan_complete"]:
        defects.append({"code": "rendered_layout_limit", "id": "drawing", "message": "The text comparison limit was reached. Separate crowded labels and retry."})
    report["checks"]["rendered_layout"] = "fail" if defects else "pass"
    report["total_defects"] = report.get("total_defects", len(report["defects"])) + len(defects)
    report["defects"].extend(defects)
    diagnostic_only = bool(report["defects"])
    if diagnostic_only:
        report["status"] = "fail"
        report.update(diagnostic_only=True, drawing_sha256=description_digest(spec), diagnostics=diagnostics)

    directory = Path(output_dir)
    dxf_path = directory / "drawing.dxf"
    pdf_path = directory / ("drawing-diagnostic.pdf" if diagnostic_only else "drawing.pdf")
    report_path = directory / ("drawing-diagnostic.json" if diagnostic_only else "drawing-report.json")
    # Artifact directories are private worker directories. Never replace an existing link.
    for path in ((pdf_path, report_path) if diagnostic_only else (dxf_path, pdf_path, report_path)):
        if path.exists() or path.is_symlink():
            raise ValueError("Drawing artifact paths must be empty before rendering.")
    if not diagnostic_only:
        document.saveas(dxf_path)
    backend = pymupdf.PyMuPdfBackend()
    render_config = config.Configuration(background_policy=config.BackgroundPolicy.WHITE,
                                         color_policy=config.ColorPolicy.COLOR)
    Frontend(RenderContext(document), backend, config=render_config).draw_layout(modelspace, finalize=True)
    pdf = backend.get_pdf_bytes(layout.Page(sheet["width"], sheet["height"], units=layout.Units.mm),
                                settings=layout.Settings(fit_page=False, scale=1.0),
                                render_box=BoundingBox2d([(0, 0), (sheet["width"], sheet["height"])]))
    if diagnostic_only:
        pdf_path.write_bytes(_diagnostic_pdf(pdf, sheet, report))
        data = pdf_path.read_bytes()
        report["artifacts"] = [{"path": str(pdf_path), "name": pdf_path.name, "sha256": hashlib.sha256(data).hexdigest(),
                                "bytes": len(data), "role": "drawing_diagnostic_preview"}]
        stored_report = {**report, "artifacts": [{key: value for key, value in item.items() if key != "path"}
                                                for item in report["artifacts"]]}
        report_path.write_text(json.dumps(stored_report, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
        data = report_path.read_bytes()
        report["artifacts"].append({"path": str(report_path), "name": report_path.name,
                                    "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "role": "drawing_diagnostic_report"})
        return report
    pdf_path.write_bytes(pdf)
    reopened = ezdxf.readfile(dxf_path)
    actual_count = len(reopened.modelspace().query("DIMENSION"))
    if actual_count != len(native_dimensions) or reopened.audit().has_errors:
        raise ValueError("The written DXF failed the native dimension and structure checks.")
    report.update(native_dimension_count=actual_count, artifacts=[],
                  adapter={"name": "ezdxf-pymupdf", "ezdxf_version": ezdxf.__version__},
                  pdf_page={"width_points": int(sheet["width"] / 25.4 * 72),
                            "height_points": int(sheet["height"] / 25.4 * 72),
                            "limitation": "The PDF backend quantizes page dimensions to whole points. Read dimensions from native DXF entities; do not measure PDF pixels."},
                  evidence_map={view["id"]: {item["id"]: {"evidence_ids": item["evidence_ids"],
                                "feature_ids": item.get("feature_ids", [])} for item in view["geometry"] + view["dimensions"]}
                                for view in resolved["views"]})
    for path in (dxf_path, pdf_path):
        data = path.read_bytes()
        report["artifacts"].append({"path": str(path), "name": path.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    report_path.write_text(json.dumps(report, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    data = report_path.read_bytes()
    report["artifacts"].append({"path": str(report_path), "name": report_path.name,
                                "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    return report
