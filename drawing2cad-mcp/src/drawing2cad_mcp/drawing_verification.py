"""Service rules of the drawing PDF verification: the request for the restricted verifier and the validity of a stored report.

The expectations come from the bound drawing specification after a new validation. They do not come from the DXF or from
the entity list of the renderer. This module does not import CAD libraries.
"""

from __future__ import annotations

import math
from typing import Any

from . import sheet_layout
from .adapters.poppler import DPI
from .pdf_verifier import MANDATORY_RULES, THRESHOLDS, number_text

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


def _dot2(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _dimension_lines(view: dict, text_height: float) -> list[dict]:
    """Sheet segments that the dimension lines, extension lines, and leaders of a native dimension must show."""
    result = []
    for dimension in view["dimensions"]:
        label = _sheet(view, dimension["label_position"])
        segments = []
        failed = None
        if dimension["type"] in {"radius", "diameter"}:
            center = _sheet(view, dimension["center"])
            direction = _unit([label[0] - center[0], label[1] - center[1]])
            edge = [center[0] + direction[0] * dimension["radius"] * view["scale"], center[1] + direction[1] * dimension["radius"] * view["scale"]]
            # The leader from the circle to the start of the value. The value is centered at the label point.
            half_text = len(_dimension_text(dimension)) * text_height * 0.475 + 0.5
            length = math.dist(edge, label) - half_text
            if length > 1.0:
                segments.append([edge, [edge[0] + direction[0] * length, edge[1] + direction[1] * length]])
            else:
                # A value close to the circle: at least the arrow at the circle.
                segments.append([edge, [edge[0] + direction[0] * 1.0, edge[1] + direction[1] * 1.0]])
        elif dimension["type"] == "angular":
            segments = _angular_lines(view, dimension, label, text_height)
            arc_radius = math.dist(_sheet(view, dimension["center"]), label)
            if arc_radius <= 1.0:
                # An arc of 1 mm or less cannot be read on the sheet. The dimension fails instead of leaving the rule.
                failed = (f"Dimension {dimension['id']} has an arc radius of {arc_radius:.2f} mm on the sheet. "
                          "The arc radius is too small to read (1 mm or less).")
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
                # The value is centered on the dimension line (DIMTAD 0) and interrupts it. A short dimension with a long
                # value keeps only the line parts beside the value, or at least the arrows.
                along = _unit([ends[1][0] - ends[0][0], ends[1][1] - ends[0][1]])
                middle = [(ends[0][i] + ends[1][i]) / 2 for i in (0, 1)]
                half_text = len(_dimension_text(dimension)) * text_height * 0.475 + 0.5
                parts = [[ends[0], [middle[0] - along[0] * half_text, middle[1] - along[1] * half_text]],
                         [[middle[0] + along[0] * half_text, middle[1] + along[1] * half_text], ends[1]]]
                if all(math.dist(*part) > 1.0 and _dot2(along, [part[1][0] - part[0][0], part[1][1] - part[0][1]]) > 0 for part in parts):
                    segments += parts
                else:
                    segments += [[ends[0], [ends[0][0] + along[0], ends[0][1] + along[1]]],
                                 [[ends[1][0] - along[0], ends[1][1] - along[1]], ends[1]]]
        if failed:
            result.append({"id": dimension["id"], "segments": segments, "evidence": dimension["evidence_ids"], "failed": failed})
        elif segments:
            result.append({"id": dimension["id"], "segments": segments, "evidence": dimension["evidence_ids"]})
    return result


def _arc(center, radius, start, end) -> dict:
    return {"type": "arc", "center": center, "radius": radius, "start_angle": start, "end_angle": end}


def _angular_geometry(view: dict, dimension: dict, label) -> tuple[list[float], float, float, float, list[tuple[list[float], float]]]:
    """The vertex, the arc radius, the start angle, and the sweep of an angular dimension, and the direction and sheet length of each leg.

    The renderer draws the arc through the label point around the vertex, counterclockwise from the first leg to the second leg.
    """
    center = _sheet(view, dimension["center"])
    radius = math.dist(center, label)
    legs = []
    for key in ("p1", "p2"):
        point = _sheet(view, dimension[key])
        legs.append((_unit([point[0] - center[0], point[1] - center[1]]), math.dist(center, point)))
    start = math.degrees(math.atan2(legs[0][0][1], legs[0][0][0]))
    sweep = (math.degrees(math.atan2(legs[1][0][1], legs[1][0][0])) - start) % 360
    return center, radius, start, sweep, legs


def _angular_lines(view: dict, dimension: dict, label, text_height: float) -> list:
    """The extension lines and the arc parts of an angular dimension that the raster must show."""
    center, radius, start, sweep, legs = _angular_geometry(view, dimension, label)
    segments = []
    for direction, length in legs:
        if radius - length > 2.0:
            # The arc is outside the drawn leg: the extension line starts 0.5 mm after the leg end (DIMEXO) and passes the arc.
            segments.append([[center[0] + direction[0] * (length + 0.8), center[1] + direction[1] * (length + 0.8)],
                             [center[0] + direction[0] * radius, center[1] + direction[1] * radius]])
    if radius <= 1.0:
        return segments
    # The value is centered on the arc at the label point (DIMTAD 0) and interrupts it. Angles are relative to the first leg.
    gap = math.degrees((len(_dimension_text(dimension)) * text_height * 0.475 + 0.5) / radius)
    middle = (math.degrees(math.atan2(label[1] - center[1], label[0] - center[0])) - start) % 360
    if middle > sweep and 360 - middle < middle - sweep:
        middle -= 360
    # The filled arrowhead covers the first DIMASZ of the arc at each arc end, and the ink check adds its own radius.
    # A part at an arc end starts after the arrowhead. The trim at the value gap is not changed.
    arrow = math.degrees((sheet_layout.DIMASZ_MM + THRESHOLDS["edge_radius_mm"]) / radius)
    parts = [(a + (arrow if a == 0.0 else 0.0), b - (arrow if b == sweep else 0.0))
             for a, b in ((0.0, min(sweep, middle - gap)), (max(0.0, middle + gap), sweep))]
    parts = [part for part in parts if math.radians(part[1] - part[0]) * radius > 1.0]
    if not parts:
        # A short arc, or a long value, leaves no arc part after the arrowheads: at least the arrow ends are checked.
        end = math.degrees(1.0 / radius)
        parts = [(0.0, min(end, sweep)), (max(0.0, sweep - end), sweep)]
    segments += [_arc(center, radius, start + a, start + b) for a, b in parts]
    return segments


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
            elif dimension["type"] == "angular":
                # The complete arc below the value, and the extension lines up to their ends past the arc (DIMEXE).
                center, radius, start, sweep, legs = _angular_geometry(view, dimension, label)
                lines.append(_arc(center, radius, start, start + sweep))
                for direction, length in legs:
                    if radius > length:
                        lines.append([[center[0] + direction[0] * length, center[1] + direction[1] * length],
                                      [center[0] + direction[0] * (radius + 1.0), center[1] + direction[1] * (radius + 1.0)]])
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
            x1 -= 0.6
            if compartment["circles"]:
                x1 = compartment["circles"][0]["center"][0] - compartment["circles"][0]["radius"] - 0.2
            # Read inside the compartment borders. A border read as a letter must not change the value.
            texts.append({"rule": "GPS-06", "kind": "datum reference", "id": f"{frame['id']}_{index}", "text": compartment["text"],
                          "box": [x0 + 0.6, y0 + 0.6, x1, y1 - 0.6], "center": [(x0 + x1) / 2, (y0 + y1) / 2], "angles": [0.0],
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
    markers = {marker["id"] for marker in resolved.get("uncertainty_markers", [])}
    # The values of native dimensions are read by DIM-01 in their text directions.
    dimension_ids = {dimension["id"] for view in resolved["views"] for dimension in view["dimensions"]}
    for label in resolved["labels"]:
        if label["id"] in dimension_ids:
            continue
        # Every label is expected text: view labels, notes, uncertainty markers, sheet labels, and review lines.
        identifier = label["id"]
        rule = ("GPS-04" if identifier in review_ids else "TEXT-02" if identifier.endswith("_label") else "TEXT-03"
                if identifier.startswith("note_") else "TEXT-04" if identifier in markers else "TEXT-05")
        texts.append({"rule": rule, "kind": "label", "id": identifier, "text": label["text"],
                      "center": [(label["bounds"][0] + label["bounds"][2]) / 2, (label["bounds"][1] + label["bounds"][3]) / 2],
                      "angles": [0.0], "critical": identifier in review_ids, "height": height, "feature": identifier})
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
                       "symbol": sheet_layout.symbol_strokes(symbol["symbol"], symbol["rect"]), "characteristic": frame["characteristic"],
                       "modifier_circles": [circle for item in frame_layout["compartments"] for circle in item.get("circles", [])]})
        texts += _frame_semantics(frame)
        value = next(item for item in frame_layout["compartments"] if item["kind"] == "value")
        size = frame_layout["text_height"]
        x0, y0, x1, y1 = value["rect"]
        x1 -= 0.6
        if value["circles"]:
            # Read the value without the circled modifiers.
            x1 = value["circles"][0]["center"][0] - value["circles"][0]["radius"] - 0.2
        box = [x0 + 0.6, y0 + 0.6, x1, y1 - 0.6]
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
    datums = []
    for datum in layout.get("datums", []):
        datums.append({"letter": datum["letter"], "box": datum["box"], "triangle": datum["triangle"], "leader": datum["leader"]})
        x0, y0, x1, y1 = datum["box"]
        texts.append({"rule": "GPS-08", "kind": "datum symbol", "id": "datum_" + datum["letter"], "text": datum["letter"],
                      "box": [x0 + 0.4, y0 + 0.4, x1 - 0.4, y1 - 0.4], "center": [(x0 + x1) / 2, (y0 + y1) / 2], "angles": [0.0],
                      "critical": True, "height": height, "feature": "datum_" + datum["letter"], "evidence": datum["evidence_ids"]})
    dimension_lines = [item for view in resolved["views"] for item in _dimension_lines(view, height)]
    return {"mode": "bound", "profile": PROFILE, "dpi": DPI, "expected": expected, "sheet": sheet, "pages_rendered": pages_rendered,
            "required": {"isometric": True, "section": True}, "views": views, "texts": texts, "frames": frames,
            "dimension_lines": dimension_lines, "datums": datums, "annotations": _annotations(resolved, texts, dimension_lines),
            "hatching": _hatch_polygons(resolved), "service_findings": [],
            "markers": [{key: marker[key] for key in ("id", "view_id", "primitive_id")} for marker in resolved.get("uncertainty_markers", [])]}


def _hatch_polygons(resolved: dict) -> list[dict]:
    """The hatched cut surfaces: their sheet loops and the pattern angle and spacing. Only their hatch lines are expected ink."""
    from .drafting import _hatch_loops

    hatching = []
    for view in resolved["views"]:
        by_id = {item["id"]: item for item in view["geometry"]}
        for hatch in view.get("hatching") or []:
            items = [by_id[ref] for ref in hatch["boundary_primitive_ids"] if ref in by_id]
            hatching.append({"loops": _hatch_loops(items, lambda p, v=view: _sheet(v, p), view["scale"]),
                             "angle": hatch["angle"], "spacing": hatch["spacing"]})
    return hatching


def build_unbound_request(expected: dict, pages_rendered: int) -> dict[str, Any]:
    """The request for a PDF without a bound drawing specification, for example a supplied source drawing."""
    return {"mode": "unbound", "profile": PROFILE, "dpi": DPI, "expected": expected, "sheet": None, "pages_rendered": pages_rendered,
            "required": {"isometric": True, "section": True}, "views": [], "texts": [], "frames": [], "service_findings": []}


MAX_RECORDED_FINDINGS = 300


def record(report: dict, binding: dict, artifact_ids: list[str]) -> dict[str, Any]:
    """The stored verification record of a drawing state. It keeps each mandatory finding that is not a pass."""
    open_findings = [{key: item.get(key) for key in ("rule_id", "status", "severity", "message", "feature")}
                     for item in report["findings"] if item["rule_id"] in MANDATORY_RULES and item["status"] != "pass"]
    covered = sorted({item["rule_id"] for item in report["findings"] if item["rule_id"] in MANDATORY_RULES})
    return {"status": report["status"], "report_sha256": report.get("report_sha256"), "binding": binding,
            "artifact_ids": artifact_ids, "untested_rules": report.get("untested_rules", []),
            "verifier_version": report.get("verifier_version"), "profile": report.get("profile"), "covered_rules": covered,
            "findings": open_findings[:MAX_RECORDED_FINDINGS], "findings_truncated": len(open_findings) > MAX_RECORDED_FINDINGS}


def gate(verification: dict | None, decisions: list[dict] | None) -> dict[str, Any]:
    """The acceptance gate of a complete-service drawing.

    A current verification is necessary. A mandatory finding with fail or not_tested blocks. A needs_review finding blocks
    unless the identified review decided it. A not_applicable finding needs a reason.
    """
    if verification is None:
        return {"passed": False, "reason": "The drawing PDF has no verification. Call drawing_verify.", "blocking": []}
    if verification.get("validity") != "current":
        return {"passed": False, "reason": "The verification is stale: " + (verification.get("reason") or "a bound input changed."), "blocking": []}
    if verification.get("profile") != PROFILE:
        return {"passed": False, "reason": f"The verification used profile {verification.get('profile')}, not {PROFILE}.", "blocking": []}
    if verification.get("findings_truncated"):
        return {"passed": False, "reason": "The verification has more open findings than the record keeps.", "blocking": []}
    missing = sorted(set(MANDATORY_RULES) - set(verification.get("covered_rules", [])))
    if missing:
        return {"passed": False, "reason": "The verification report has no result for the mandatory rules " + ", ".join(missing[:10]) + ".",
                "blocking": [{"rule_id": rule, "status": "not_tested", "feature": None, "message": "No result in the report."}
                             for rule in missing[:50]], "blocking_count": len(missing)}
    decided = {(item["rule_id"], item.get("feature")) for item in decisions or []}
    blocking, reviewed = [], []
    for item in verification.get("findings", []):
        key = (item["rule_id"], item.get("feature"))
        if item["status"] in {"fail", "not_tested"}:
            blocking.append(item)
        elif item["status"] == "needs_review":
            (reviewed if key in decided else blocking).append(item)
        elif item["status"] == "not_applicable" and not item.get("message"):
            blocking.append(item)
    if verification.get("status") == "fail" and not blocking:
        # A failed report always blocks, also for a rule outside the mandatory list.
        blocking.append({"rule_id": "REPORT", "status": "fail", "severity": "major", "feature": None,
                         "message": "The verification report failed."})
    passed = not blocking
    return {"passed": passed, "blocking": blocking[:50], "blocking_count": len(blocking), "reviewed": reviewed[:50],
            "reason": None if passed else f"{len(blocking)} mandatory verification findings block the acceptance."}


def status(record: dict | None, current: dict | None) -> dict[str, Any] | None:
    """current or stale. A changed PDF, drawing, part revision, or build makes an earlier report stale."""
    if record is None:
        return None
    invalid = sorted(key for key in ("pdf_sha256", "candidate_sha256") if record["binding"].get(key) == "changed")
    if invalid:
        return {**record, "validity": "stale", "reason": "The verification was recorded for a changed input: " + ", ".join(invalid) + "."}
    if current is None:
        return {**record, "validity": "stale", "reason": "The drawing or its PDF changed after the verification."}
    changed = sorted(key for key, value in record["binding"].items() if current.get(key) != value)
    if changed:
        return {**record, "validity": "stale", "reason": "Changed since the verification: " + ", ".join(changed) + "."}
    return {**record, "validity": "current", "reason": None}
