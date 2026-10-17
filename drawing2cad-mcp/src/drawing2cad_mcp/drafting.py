"""Render supplied 2D geometry as native DXF dimensions and a matching PDF."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .drawing_contract import _inside, _overlap, drawing_validate


def render_drawing(spec: dict[str, Any], description: dict[str, Any], revision: int,
                   output_dir: Path) -> dict[str, Any]:
    """Render fixed artifact names inside the restricted worker directory."""
    report = drawing_validate(spec, description, revision)
    if report["status"] != "pass":
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
        entity_groups.append((view["id"], entities, view["frame"]))

    marker_ids = {marker["id"] for marker in resolved["uncertainty_markers"]}
    for label in resolved["labels"]:
        if label["id"] in native_dimensions:
            continue
        entity = modelspace.add_text(label["text"], dxfattribs={"height": sheet["text_height"],
                                    "layer": "UNCERTAINTY" if label["id"] in marker_ids else "ANNOTATIONS"})
        entity.set_placement(label["position"], align=TextEntityAlignment.LEFT)
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
                            "message": "Rendered geometry or dimension lines exceed their view frame."})
    margin = sheet["margin"]
    usable = [margin, margin, sheet["width"] - margin, sheet["height"] - margin]
    bounds = bbox.extents(modelspace, cache=cache)
    if bounds.has_data and not _inside([bounds.extmin.x, bounds.extmin.y, bounds.extmax.x, bounds.extmax.y], usable):
        defects.append({"code": "rendered_sheet_clipping", "id": "drawing", "message": "Rendered entities exceed the sheet margin."})
    text_bounds = []
    for entity in disassemble.recursive_decompose(modelspace):
        if entity.dxftype() not in {"TEXT", "MTEXT"}:
            continue
        box = bbox.extents([entity])
        if box.has_data:
            text_bounds.append([box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y])
    if any(_overlap(first, second) for index, first in enumerate(text_bounds) for second in text_bounds[index + 1:]):
        defects.append({"code": "rendered_label_overlap", "id": "drawing", "message": "Rendered text bounds overlap."})
    report["checks"]["rendered_layout"] = "fail" if defects else "pass"
    report["defects"].extend(defects)
    if defects:
        report["status"] = "fail"
        return report

    directory = Path(output_dir)
    dxf_path = directory / "drawing.dxf"
    pdf_path = directory / "drawing.pdf"
    report_path = directory / "drawing-report.json"
    # Artifact directories are private worker directories. Never replace an existing link.
    for path in (dxf_path, pdf_path, report_path):
        if path.exists() or path.is_symlink():
            raise ValueError("Drawing artifact paths must be empty before rendering.")
    document.saveas(dxf_path)
    backend = pymupdf.PyMuPdfBackend()
    render_config = config.Configuration(background_policy=config.BackgroundPolicy.WHITE,
                                         color_policy=config.ColorPolicy.COLOR)
    Frontend(RenderContext(document), backend, config=render_config).draw_layout(modelspace, finalize=True)
    pdf = backend.get_pdf_bytes(layout.Page(sheet["width"], sheet["height"], units=layout.Units.mm),
                                settings=layout.Settings(fit_page=False, scale=1.0),
                                render_box=BoundingBox2d([(0, 0), (sheet["width"], sheet["height"])]))
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
