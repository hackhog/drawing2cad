"""Render supplied 2D geometry as native DXF dimensions and a matching PDF."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import math

from . import sheet_layout
from .drawing_contract import _inside, _overlap, description_digest, drawing_validate, render_gate


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


def geometry_by_id(view: dict, identifier: str) -> dict:
    return next(item for item in view["geometry"] if item["id"] == identifier)


def _sample(item: dict, point, scale: float) -> list[list[float]]:
    """Sheet points of a boundary primitive, in its own direction."""
    if item["type"] == "line":
        return [point(item["start"]), point(item["end"])]
    if item["type"] in {"circle", "arc"}:
        start = 0.0 if item["type"] == "circle" else item["start_angle"]
        sweep = 360.0 if item["type"] == "circle" else (item["end_angle"] - item["start_angle"]) % 360 or 360.0
        count = max(8, math.ceil(sweep / 5))
        return [point([item["center"][0] + item["radius"] * math.cos(math.radians(start + sweep * i / count)),
                       item["center"][1] + item["radius"] * math.sin(math.radians(start + sweep * i / count))]) for i in range(count + 1)]
    major = item["major_axis"]
    minor = [-major[1] * item["ratio"], major[0] * item["ratio"]]
    start, end = item["start_parameter"], item["end_parameter"]
    count = max(8, math.ceil((end - start) / 5))
    return [point([item["center"][0] + math.cos(math.radians(start + (end - start) * i / count)) * major[0]
                   + math.sin(math.radians(start + (end - start) * i / count)) * minor[0],
                   item["center"][1] + math.cos(math.radians(start + (end - start) * i / count)) * major[1]
                   + math.sin(math.radians(start + (end - start) * i / count)) * minor[1]]) for i in range(count + 1)]


def _hatch_loops(items: list[dict], point, scale: float) -> list[list[list[float]]]:
    """Closed sheet polylines of a hatching boundary. The validator has checked that the boundary is closed."""
    pieces = [_sample(item, point, scale) for item in items]
    loops = []
    while pieces:
        loop = pieces.pop(0)
        while math.dist(loop[0], loop[-1]) > 1e-4 and pieces:
            for index, piece in enumerate(pieces):
                if math.dist(loop[-1], piece[0]) <= 1e-4:
                    loop += piece[1:]
                elif math.dist(loop[-1], piece[-1]) <= 1e-4:
                    loop += piece[::-1][1:]
                else:
                    continue
                pieces.pop(index)
                break
            else:
                raise ValueError("A hatching boundary is not closed.")
        loops.append([[round(x, 6), round(y, 6)] for x, y in loop[:-1]])
    return loops


def _render_sheet_items(modelspace, layout: dict, sheet: dict, evidence) -> list:
    """Draw the border, the title block, the section marks, the tolerance frames, and the datum symbols.

    Return the entities in the sheet margin. They are excluded from the margin check.
    """
    from ezdxf.enums import TextEntityAlignment

    height = sheet["text_height"]
    furniture = []

    def text(value, position, layer, size=height, centered=False):
        entity = modelspace.add_text(value, dxfattribs={"height": size, "layer": layer})
        if centered:
            entity.set_placement(position, align=TextEntityAlignment.MIDDLE_CENTER)
        else:
            entity.set_placement(position, align=TextEntityAlignment.LEFT)
        return entity

    def rect(box, layer):
        return modelspace.add_lwpolyline([(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])],
                                         close=True, dxfattribs={"layer": layer})

    def solid(points, layer):
        # A SOLID with three points is a filled triangle. The fourth point repeats the third point.
        return modelspace.add_solid([points[0], points[1], points[2], points[2]], dxfattribs={"layer": layer})

    border = layout.get("border")
    if border:
        rect(border["frame"], "BORDER")
        for start, end in border["marks"]:
            furniture.append(modelspace.add_line(start, end, dxfattribs={"layer": "BORDER"}))
        for start, end in border["ticks"]:
            furniture.append(modelspace.add_line(start, end, dxfattribs={"layer": "SHEET"}))
        for item in border["labels"]:
            furniture.append(text(item["text"], item["position"], "SHEET", border["label_height"], centered=True))
    block = layout.get("title_block")
    if block:
        rect(block["rect"], "BORDER")
        for cell in block["cells"]:
            rect(cell["rect"], "TITLE_BLOCK")
            text(cell["caption"], cell["caption_position"], "TITLE_BLOCK", cell["caption_height"])
            if cell["value"] is not None:
                text(cell["value"], cell["value_position"], "ANNOTATIONS", cell["value_height"])
        symbol = block.get("projection_symbol")
        if symbol:
            modelspace.add_lwpolyline(symbol["cone"], close=True, dxfattribs={"layer": "TITLE_BLOCK"})
            for radius in symbol["radii"]:
                modelspace.add_circle(symbol["circle_center"], radius, dxfattribs={"layer": "TITLE_BLOCK"})
            modelspace.add_line(*symbol["axis"], dxfattribs={"layer": "CENTER"})
    for section in layout.get("sections", []):
        line = modelspace.add_line(*section["line"], dxfattribs={"layer": "CUTTING"})
        evidence(line, section["view_id"] + "_cutting_line", section["evidence_ids"])
        for end in section["ends"]:
            modelspace.add_line(*end["thick"], dxfattribs={"layer": "CUTTING_THICK"})
            modelspace.add_line(*end["shaft"], dxfattribs={"layer": "CUTTING_THICK"})
            solid(end["head"], "CUTTING_THICK")
            text(section["letter"], end["letter_center"], "ANNOTATIONS", centered=True)
    for frame in layout.get("frames", []):
        layer = "GPS" if frame["status"] == "pass" else "GPS_REVIEW"
        frame_layout = frame["layout"]
        outline = rect(frame_layout["rect"], layer)
        evidence(outline, frame["id"], frame["evidence_ids"], frame["feature_ids"])
        for compartment in frame_layout["compartments"]:
            rect(compartment["rect"], layer)
            if compartment["kind"] == "symbol":
                strokes = sheet_layout.symbol_strokes(compartment["symbol"], compartment["rect"])
                for start, end in strokes["lines"]:
                    modelspace.add_line(start, end, dxfattribs={"layer": layer})
                for center, radius in strokes["circles"]:
                    modelspace.add_circle(center, radius, dxfattribs={"layer": layer})
                for center, radius, start, end in strokes["arcs"]:
                    modelspace.add_arc(center, radius, start, end, dxfattribs={"layer": layer})
                continue
            text(compartment["text"], compartment["text_position"], layer, frame_layout["text_height"])
            for item in compartment["circles"]:
                modelspace.add_circle(item["center"], item["radius"], dxfattribs={"layer": layer})
                text(item["letter"], item["center"], layer, frame_layout["text_height"] * 0.8, centered=True)
        start, target = frame["leader"]
        modelspace.add_line(start, target, dxfattribs={"layer": layer})
        direction = [target[0] - start[0], target[1] - start[1]]
        length = math.hypot(*direction)
        if length > 1e-6:
            unit = [direction[0] / length, direction[1] / length]
            normal = [-unit[1], unit[0]]
            base = [target[0] - unit[0] * 2.5, target[1] - unit[1] * 2.5]
            solid([target, [base[0] + normal[0] * 0.8, base[1] + normal[1] * 0.8],
                   [base[0] - normal[0] * 0.8, base[1] - normal[1] * 0.8]], layer)
        if frame.get("review"):
            text(frame["review"]["text"], frame["review"]["position"], "UNCERTAINTY")
    for datum in layout.get("datums", []):
        box = rect(datum["box"], "GPS")
        evidence(box, "datum_" + datum["letter"], datum["evidence_ids"], datum["feature_ids"])
        text(datum["letter"], datum["text_position"], "GPS")
        modelspace.add_line(*datum["leader"], dxfattribs={"layer": "GPS"})
        solid(datum["triangle"], "GPS")
    return furniture


def _bind_pdf(pdf: bytes, revision: int, description_sha256: str, dxf_sha256: str) -> bytes:
    """Record the drawing binding in the PDF metadata: the part revision, the description, and the DXF that the PDF shows."""
    import pymupdf

    document = pymupdf.open(stream=pdf, filetype="pdf")
    document.set_metadata({"title": "drawing2cad technical drawing", "producer": "drawing2cad ezdxf-pymupdf",
                           "keywords": f"part_revision:{revision}; description_sha256:{description_sha256}; dxf_sha256:{dxf_sha256}"})
    data = document.tobytes(garbage=4, deflate=True)
    document.close()
    return data


def render_drawing(spec: dict[str, Any], description: dict[str, Any], revision: int,
                   output_dir: Path) -> dict[str, Any]:
    """Render fixed artifact names inside the restricted worker directory."""
    report = render_gate(drawing_validate(spec, description, revision))
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
    # Line weights in hundredths of a mm: 0.7 mm for frames and thick cutting-line ends, 0.18 mm for thin lines.
    for name, color, linetype, weight in (("VISIBLE", 7, "CONTINUOUS", None), ("HIDDEN", 7, "D2C_HIDDEN_MM", 18),
                                          ("CENTER", 7, "D2C_CENTER_MM", 18), ("SECTION", 7, "CONTINUOUS", None),
                                          ("HATCH", 7, "CONTINUOUS", 18),
                                          ("DIMENSIONS", 7, "CONTINUOUS", None), ("ANNOTATIONS", 7, "CONTINUOUS", None),
                                          ("UNCERTAINTY", 1, "CONTINUOUS", None), ("CUTTING", 7, "D2C_CENTER_MM", 18),
                                          ("CUTTING_THICK", 7, "CONTINUOUS", 70), ("BORDER", 7, "CONTINUOUS", 70),
                                          ("SHEET", 7, "CONTINUOUS", 25), ("TITLE_BLOCK", 7, "CONTINUOUS", 35),
                                          ("GPS", 7, "CONTINUOUS", 25), ("GPS_REVIEW", 1, "D2C_HIDDEN_MM", 25)):
        attrs = {"color": color, "linetype": linetype}
        if weight is not None:
            attrs["lineweight"] = weight
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
            elif primitive["type"] == "ellipse":
                major = [scale * primitive["major_axis"][0], scale * primitive["major_axis"][1], 0.0]
                full = primitive["end_parameter"] - primitive["start_parameter"] >= 360 - 1e-9
                entity = modelspace.add_ellipse(point(primitive["center"]), major_axis=major, ratio=primitive["ratio"],
                                                start_param=0.0 if full else math.radians(primitive["start_parameter"]),
                                                end_param=2 * math.pi if full else math.radians(primitive["end_parameter"]),
                                                dxfattribs=attrs)
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
            if dim.get("theoretically_exact"):
                # A negative DIMGAP draws a frame around the value: a theoretically exact dimension (ISO 1101).
                overrides["dimgap"] = -0.5
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
        for index, hatch in enumerate(view.get("hatching") or []):
            loops = _hatch_loops([geometry_by_id(view, ref) for ref in hatch["boundary_primitive_ids"]], point, scale)
            entity = modelspace.add_hatch(dxfattribs={"layer": "HATCH"})
            # ANSI31 has 45-degree lines with 3.175 mm spacing at scale 1.
            entity.set_pattern_fill("ANSI31", angle=hatch["angle"] - 45.0, scale=hatch["spacing"] / 3.175)
            for loop in loops:
                entity.paths.add_polyline_path(loop, is_closed=True)
            evidence(entity, f"{view['id']}_hatch_{index}", view["cutting_plane"]["evidence_ids"] if view.get("cutting_plane") else [])
            entities.append(entity)
        entity_groups.append((view["id"], entities, view["frame"]))

    layout_data = resolved.get("layout") or {}
    furniture = _render_sheet_items(modelspace, layout_data, sheet, evidence)

    marker_ids = {marker["id"] for marker in resolved["uncertainty_markers"]}
    review_ids = set(layout_data.get("review_label_ids", []))
    for label in resolved["labels"]:
        if label["id"] in native_dimensions:
            continue
        entity = modelspace.add_text(label["text"], dxfattribs={"height": sheet["text_height"],
                                    "layer": "UNCERTAINTY" if label["id"] in marker_ids | review_ids else "ANNOTATIONS"})
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
    # The border, its marks, and its zone labels are in the margin. They must stay on the sheet.
    furniture_handles = {entity.dxf.handle for entity in furniture}
    bounds = bbox.extents([entity for entity in modelspace if entity.dxf.handle not in furniture_handles], cache=cache)
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
    source = document
    if not diagnostic_only:
        document.saveas(dxf_path)
        # Render the PDF from the written DXF, so both files have the same content.
        source = ezdxf.readfile(dxf_path)
    backend = pymupdf.PyMuPdfBackend()
    render_config = config.Configuration(background_policy=config.BackgroundPolicy.WHITE,
                                         color_policy=config.ColorPolicy.COLOR)
    Frontend(RenderContext(source), backend, config=render_config).draw_layout(source.modelspace(), finalize=True)
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
    dxf_sha256 = hashlib.sha256(dxf_path.read_bytes()).hexdigest()
    pdf_path.write_bytes(_bind_pdf(pdf, revision, report["description_sha256"], dxf_sha256))
    reopened = ezdxf.readfile(dxf_path)
    actual_count = len(reopened.modelspace().query("DIMENSION"))
    if actual_count != len(native_dimensions) or reopened.audit().has_errors:
        raise ValueError("The written DXF failed the native dimension and structure checks.")
    report.update(native_dimension_count=actual_count, artifacts=[], dxf_sha256=dxf_sha256,
                  sheet_items={"title_block": bool(layout_data.get("title_block")), "border": bool(layout_data.get("border")),
                               "tolerance_frames": len(layout_data.get("frames", [])), "datums": len(layout_data.get("datums", [])),
                               "sections": len(layout_data.get("sections", [])),
                               "review_marks": sum(1 for item in layout_data.get("frames", []) if item.get("review"))
                               + len(layout_data.get("review_label_ids", []))},
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
