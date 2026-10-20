"""Service rules of the drawing PDF verification: the request for the restricted verifier and the validity of a stored report.

The expectations come from the bound drawing specification after a new validation. They do not come from the DXF or from
the entity list of the renderer. This module does not import CAD libraries.
"""

from __future__ import annotations

import math
from typing import Any

from . import sheet_layout
from .adapters.poppler import DPI
from .pdf_verifier import number_text

PROFILE = "drawing2cad-verify-1"


def _sheet(view, point):
    return [view["origin"][i] + view["scale"] * point[i] for i in (0, 1)]


def _dimension_text(dimension: dict) -> dict[str, Any]:
    """The expected text of a native dimension, its center on the sheet, and the text directions to try."""
    value = number_text(dimension["expected"])
    return {"radius": "R" + value, "diameter": "Ø" + value, "angular": value + "°"}.get(dimension["type"], value)


def _unit(vector):
    length = math.hypot(*vector) or 1.0
    return [vector[0] / length, vector[1] / length]


def _dimension_lines(view: dict) -> list[dict]:
    """Sheet segments that the dimension lines, extension lines, and leaders of a native dimension must show."""
    result = []
    for dimension in view["dimensions"]:
        label = _sheet(view, dimension["label_position"])
        segments = []
        if dimension["type"] in {"radius", "diameter"}:
            center = _sheet(view, dimension["center"])
            direction = _unit([label[0] - center[0], label[1] - center[1]])
            edge = [center[0] + direction[0] * dimension["radius"] * view["scale"], center[1] + direction[1] * dimension["radius"] * view["scale"]]
            if math.dist(edge, label) > 4.0:
                # The leader from the circle toward the value; the part next to the value can be covered by text.
                segments.append([edge, [edge[0] + (label[0] - edge[0]) * 0.5, edge[1] + (label[1] - edge[1]) * 0.5]])
        elif dimension["type"] == "linear":
            angle = math.radians(float(dimension.get("angle", 0.0)))
            direction = [math.cos(angle), math.sin(angle)]
            normal = [-direction[1], direction[0]]
            ends = []
            for key in ("p1", "p2"):
                point = _sheet(view, dimension[key])
                offset = (label[0] - point[0]) * normal[0] + (label[1] - point[1]) * normal[1]
                foot = [point[0] + normal[0] * offset, point[1] + normal[1] * offset]
                ends.append(foot)
                if abs(offset) > 2.0:
                    sign = 1.0 if offset > 0 else -1.0
                    # The extension line starts 0.5 mm from the feature (DIMEXO) and passes the dimension line.
                    segments.append([[point[0] + normal[0] * sign * 0.8, point[1] + normal[1] * sign * 0.8], foot])
            if math.dist(*ends) > 2.0:
                segments.append(ends)
        if segments:
            result.append({"id": dimension["id"], "segments": segments, "evidence": dimension["evidence_ids"]})
    return result


def _box_polygon(center, width, height, angle):
    a = math.radians(angle)
    u, v = [math.cos(a), math.sin(a)], [-math.sin(a), math.cos(a)]
    return [[center[0] + sx * width / 2 * u[0] + sy * height / 2 * v[0], center[1] + sx * width / 2 * u[1] + sy * height / 2 * v[1]]
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def _annotations(resolved: dict, texts: list[dict], dimension_lines: list[dict]) -> dict[str, list]:
    """Sheet shapes that may contain ink besides the model edges and the declared geometry."""
    lines = [segment for item in dimension_lines for segment in item["segments"]]
    polygons = []
    for item in texts:
        height = item["height"] * 2.0 + 1.6
        width = len(item["text"]) * item["height"] * 0.95 + 3.0
        for angle in item["angles"][:1] if item.get("box") else item["angles"][:2]:
            polygons.append(_box_polygon(item["center"], width, height, angle))
    for label in resolved["labels"]:
        x0, y0, x1, y1 = label["bounds"]
        polygons.append([[x0 - 0.5, y0 - 0.5], [x1 + 0.5, y0 - 0.5], [x1 + 0.5, y1 + 0.5], [x0 - 0.5, y1 + 0.5]])
    for marker in resolved.get("uncertainty_markers", []):
        lines.append([marker["position"], marker["target"]])
        polygons.append(_box_polygon(marker["target"], 3.0, 3.0, 0.0))
    for view in resolved["views"]:
        for dimension in view["dimensions"]:
            # The arrow heads and the leader beside a moved value.
            label = _sheet(view, dimension["label_position"])
            if dimension["type"] in {"radius", "diameter"}:
                lines.append([_sheet(view, dimension["center"]), label])
    layout = resolved.get("layout") or {}
    for frame in layout.get("frames", []):
        x0, y0, x1, y1 = frame["layout"]["rect"]
        right = x1 + (1.0 + sheet_layout.text_width("REVIEW", frame["layout"]["text_height"]) if frame.get("review") else 0.0)
        polygons.append([[x0, y0], [right, y0], [right, y1], [x0, y1]])
        lines.append(frame["leader"])
    for datum in layout.get("datums", []):
        x0, y0, x1, y1 = datum["box"]
        polygons += [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]], datum["triangle"]]
        lines.append(datum["leader"])
    for section in layout.get("sections", []):
        lines.append(section["line"])
        for end in section["ends"]:
            lines += [end["thick"], end["shaft"]]
            polygons += [end["head"], _box_polygon(end["letter_center"], 4.0, 4.0, 0.0)]
    return {"lines": lines, "polygons": polygons}


def _frame_semantics(frame: dict) -> list[dict]:
    """Texts of the datum compartments and the circled modifiers of a frame. They are critical: a changed requirement must fail."""
    texts = []
    size = frame["layout"]["text_height"]
    for index, compartment in enumerate(frame["layout"]["compartments"]):
        if compartment["kind"] == "datum":
            x0, y0, x1, y1 = compartment["rect"]
            if compartment["circles"]:
                x1 = compartment["circles"][0]["center"][0] - compartment["circles"][0]["radius"] - 0.2
            texts.append({"rule": "GPS-06", "kind": "datum reference", "id": f"{frame['id']}_{index}", "text": compartment["text"],
                          "box": [x0 + 0.4, y0 + 0.4, x1, y1 - 0.4], "center": [(x0 + x1) / 2, (y0 + y1) / 2], "angles": [0.0],
                          "critical": True, "height": size, "feature": frame["id"], "evidence": frame["evidence_ids"]})
        for number, circle in enumerate(compartment.get("circles", [])):
            r = circle["radius"] * 0.72
            cx, cy = circle["center"]
            texts.append({"rule": "GPS-07", "kind": "modifier", "id": f"{frame['id']}_{index}_{number}", "text": circle["letter"],
                          "box": [cx - r, cy - r, cx + r, cy + r], "center": circle["center"], "angles": [0.0], "critical": True,
                          "height": size * 0.8, "feature": frame["id"], "evidence": frame["evidence_ids"]})
    return texts


def _dimension_texts(view: dict, text_height: float) -> list[dict]:
    texts = []
    for dimension in view["dimensions"]:
        label = _sheet(view, dimension["label_position"])
        if dimension["type"] in {"radius", "diameter"}:
            center = _sheet(view, dimension["center"])
            angle = math.degrees(math.atan2(label[1] - center[1], label[0] - center[0]))
            position, angles = label, [angle, angle + 180, 0.0]
        elif dimension["type"] == "linear":
            angle = float(dimension.get("angle", 0.0))
            direction = [math.cos(math.radians(angle)), math.sin(math.radians(angle))]
            middle = _sheet(view, [(dimension["p1"][i] + dimension["p2"][i]) / 2 for i in (0, 1)])
            offset = (middle[0] - label[0]) * direction[0] + (middle[1] - label[1]) * direction[1]
            # The value is above the dimension line, at the middle between the extension lines.
            normal = [-direction[1], direction[0]]
            position = [label[0] + offset * direction[0] + normal[0] * text_height * 0.7,
                        label[1] + offset * direction[1] + normal[1] * text_height * 0.7]
            angles = [angle, angle + 180]
        else:
            position, angles = label, [0.0, 90.0, 180.0, 270.0]
        texts.append({"rule": "DIM-01", "kind": "dimension", "id": dimension["id"], "text": _dimension_text(dimension),
                      "center": position, "angles": [round(a % 360, 3) for a in angles], "critical": True,
                      "height": text_height, "feature": dimension["id"], "evidence": dimension["evidence_ids"]})
    return texts


def _derivation_request(view: dict, views: dict) -> dict | None:
    """The request for a new model projection of a view. Only a view with a projection has a model-bound coordinate system."""
    if not view.get("projection"):
        return None
    request = {"id": view["id"], "kind": "orthographic" if view["kind"] in {"orthographic", "detail"} else view["kind"],
               "projection": view["projection"], "hidden_lines": True, "cutting_plane": None}
    plane = view.get("cutting_plane")
    if view["kind"] == "section":
        source = views.get(plane["source_view_id"]) if plane else None
        if not plane or not source or not source.get("projection"):
            return None
        request["cutting_plane"] = {key: plane[key] for key in ("letter", "origin", "normal", "viewing_side", "source_view_id")}
        request["source_projection"] = source["projection"]
        request["hidden_lines"] = False
    return request


def build_request(resolved: dict, expected: dict, pages_rendered: int) -> dict[str, Any]:
    """The verification request of a bound drawing. resolved is the result of drawing_validate for the stored drawing."""
    sheet = resolved["sheet"]
    height = sheet["text_height"]
    by_id = {view["id"]: view for view in resolved["views"]}
    views, texts = [], []
    for view in resolved["views"]:
        views.append({"id": view["id"], "kind": view["kind"], "origin": view["origin"], "scale": view["scale"], "frame": view["frame"],
                      "projection": view.get("projection"), "geometry": view["geometry"], "dimensions": view["dimensions"],
                      "hidden_lines": any(item.get("style") == "hidden" for item in view["geometry"]),
                      "derivation_request": _derivation_request(view, by_id)})
        texts += _dimension_texts(view, height)
    layout = resolved.get("layout") or {}
    review_ids = set(layout.get("review_label_ids", []))
    for label in resolved["labels"]:
        if label["id"].endswith("_label") or label["id"] in review_ids:
            texts.append({"rule": "GPS-04" if label["id"] in review_ids else "TEXT-02", "kind": "label", "id": label["id"],
                          "text": label["text"], "center": [(label["bounds"][0] + label["bounds"][2]) / 2, (label["bounds"][1] + label["bounds"][3]) / 2],
                          "angles": [0.0], "critical": label["id"] in review_ids, "height": height})
    block = layout.get("title_block")
    if block:
        rules = {"units": ("UNITS-01", True), "part_revision": ("REV-02", True), "scale": ("TEXT-01", True)}
        for cell in block["cells"]:
            if cell["value"] is None:
                continue
            rule, critical = rules.get(cell["field"], ("TEXT-01", False))
            x0, y0, x1, _ = cell["rect"]
            # The value line below the caption, inside the cell borders.
            box = [x0 + 0.4, y0 + 0.4, x1 - 0.4, cell["caption_position"][1] - 0.3]
            texts.append({"rule": rule, "kind": "title block field", "id": cell["field"], "text": cell["value"], "box": box,
                          "center": [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2], "angles": [0.0], "critical": critical,
                          "height": cell["value_height"], "feature": cell["field"]})
    frames = []
    for frame in layout.get("frames", []):
        frame_layout = frame["layout"]
        symbol = next(item for item in frame_layout["compartments"] if item["kind"] == "symbol")
        frames.append({"id": frame["id"], "rect": frame_layout["rect"], "status": frame["status"], "symbol_rect": symbol["rect"],
                       "symbol": sheet_layout.symbol_strokes(symbol["symbol"], symbol["rect"]), "characteristic": frame["characteristic"]})
        texts += _frame_semantics(frame)
        value = next(item for item in frame_layout["compartments"] if item["kind"] == "value")
        size = frame_layout["text_height"]
        x0, y0, x1, y1 = value["rect"]
        if value["circles"]:
            # Read the value without the circled modifiers.
            x1 = value["circles"][0]["center"][0] - value["circles"][0]["radius"] - 0.2
        box = [x0 + 0.4, y0 + 0.4, x1, y1 - 0.4]
        texts.append({"rule": "GPS-02", "kind": "tolerance value", "id": frame["id"], "text": value["text"], "box": box,
                      "center": [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2], "angles": [0.0], "critical": True, "height": size,
                      "feature": frame["id"], "evidence": frame["evidence_ids"]})
        if frame.get("review"):
            position = frame["review"]["position"]
            texts.append({"rule": "GPS-03", "kind": "review mark", "id": frame["id"], "text": "REVIEW",
                          "center": [position[0] + 6 * height * 0.45, position[1] + height / 2], "angles": [0.0], "critical": True, "height": height})
    for section in layout.get("sections", []):
        for index, end in enumerate(section["ends"]):
            texts.append({"rule": "SEC-01", "kind": "section letter", "id": f"{section['view_id']}_{index}", "text": section["letter"],
                          "center": end["letter_center"], "angles": [0.0], "critical": True, "height": height,
                          "feature": section["view_id"]})
    dimension_lines = [item for view in resolved["views"] for item in _dimension_lines(view)]
    return {"mode": "bound", "profile": PROFILE, "dpi": DPI, "expected": expected, "sheet": sheet, "pages_rendered": pages_rendered,
            "required": {"isometric": True, "section": True}, "views": views, "texts": texts, "frames": frames,
            "dimension_lines": dimension_lines, "annotations": _annotations(resolved, texts, dimension_lines),
            "hatching": _hatch_polygons(resolved), "service_findings": []}


def _hatch_polygons(resolved: dict) -> list[list[list[float]]]:
    """Sheet polygons of the hatched cut surfaces. Their hatch lines are expected ink."""
    from .drafting import _hatch_loops

    polygons = []
    for view in resolved["views"]:
        by_id = {item["id"]: item for item in view["geometry"]}
        for hatch in view.get("hatching") or []:
            items = [by_id[ref] for ref in hatch["boundary_primitive_ids"] if ref in by_id]
            polygons += _hatch_loops(items, lambda p, v=view: _sheet(v, p), view["scale"])
    return polygons


def build_unbound_request(expected: dict, pages_rendered: int) -> dict[str, Any]:
    """The request for a PDF without a bound drawing specification, for example a supplied source drawing."""
    return {"mode": "unbound", "profile": PROFILE, "dpi": DPI, "expected": expected, "sheet": None, "pages_rendered": pages_rendered,
            "required": {"isometric": True, "section": True}, "views": [], "texts": [], "frames": [], "service_findings": []}


def record(report: dict, binding: dict, artifact_ids: list[str]) -> dict[str, Any]:
    """The stored verification record of a drawing state."""
    return {"status": report["status"], "report_sha256": report.get("report_sha256"), "binding": binding,
            "artifact_ids": artifact_ids, "untested_rules": report.get("untested_rules", []),
            "verifier_version": report.get("verifier_version")}


def status(record: dict | None, current: dict | None) -> dict[str, Any] | None:
    """current or stale. A changed PDF, drawing, part revision, or build makes an earlier report stale."""
    if record is None:
        return None
    if current is None:
        return {**record, "validity": "stale", "reason": "The drawing or its PDF changed after the verification."}
    changed = sorted(key for key, value in record["binding"].items() if current.get(key) != value)
    if changed:
        return {**record, "validity": "stale", "reason": "Changed since the verification: " + ", ".join(changed) + "."}
    return {**record, "validity": "current", "reason": None}
