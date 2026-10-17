"""Bounded declarations for evidence-based technical drawing sheets."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, field_validator

from .part_schema import ClosedModel, EvidenceIds, Identifier, Number, _references, parse_description

DRAWING_SCHEMA_VERSION = "1.0"
Text = Annotated[str, Field(min_length=1, max_length=180, pattern=r"^[^\x00-\x1f\x7f\\]+$")]
Point = tuple[Number, Number]


class DrawingRef(ClosedModel):
    parameter: Identifier
    factor: Annotated[float, Field(allow_inf_nan=False, ge=-1000, le=1000)] = 1.0
    offset: Number = 0.0


Scalar = Number | DrawingRef
ModelPoint = tuple[Scalar, Scalar]


class Primitive(ClosedModel):
    id: Identifier
    evidence_ids: EvidenceIds
    feature_ids: Annotated[list[Identifier], Field(min_length=1, max_length=100)]
    style: Literal["visible", "hidden", "center", "section"] = "visible"


class Line(Primitive):
    type: Literal["line"]
    start: ModelPoint
    end: ModelPoint


class Circle(Primitive):
    type: Literal["circle"]
    center: ModelPoint
    radius: Scalar


class Arc(Primitive):
    type: Literal["arc"]
    center: ModelPoint
    radius: Scalar
    start_angle: Scalar
    end_angle: Scalar


Geometry = Annotated[Line | Circle | Arc, Field(discriminator="type")]


class Anchor(ClosedModel):
    primitive: Identifier
    point: Literal["start", "end", "center", "left", "right", "top", "bottom"]


class Dimension(ClosedModel):
    id: Identifier
    evidence_ids: EvidenceIds
    expected: Scalar
    label_position: ModelPoint


class LinearDimension(Dimension):
    type: Literal["linear"]
    p1: Anchor
    p2: Anchor
    axis: Literal["horizontal", "vertical", "aligned"] = "horizontal"


class RoundDimension(Dimension):
    type: Literal["radius", "diameter"]
    primitive: Identifier


class AngularDimension(Dimension):
    type: Literal["angular"]
    first_line: Identifier
    second_line: Identifier


Dim = Annotated[LinearDimension | RoundDimension | AngularDimension, Field(discriminator="type")]


class View(ClosedModel):
    id: Identifier
    label: Text
    kind: Literal["orthographic", "section", "detail"]
    orientation: Literal["front", "top", "right", "left", "bottom", "rear", "custom"]
    origin: Point
    frame: tuple[Number, Number, Number, Number]
    scale: Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)] = 1.0
    geometry: Annotated[list[Geometry], Field(min_length=1, max_length=300)]
    dimensions: Annotated[list[Dim], Field(max_length=100)]
    section_note: Text | None = None


class Note(ClosedModel):
    text: Text
    position: Point
    evidence_ids: EvidenceIds


class Marker(ClosedModel):
    id: Identifier
    view_id: Identifier
    primitive_id: Identifier
    text: Text
    position: ModelPoint
    evidence_ids: EvidenceIds


class Sheet(ClosedModel):
    width: Annotated[float, Field(ge=100, le=1200, allow_inf_nan=False)] = 297.0
    height: Annotated[float, Field(ge=100, le=1200, allow_inf_nan=False)] = 210.0
    margin: Annotated[float, Field(ge=5, le=30, allow_inf_nan=False)] = 10.0
    text_height: Annotated[float, Field(ge=1.8, le=5, allow_inf_nan=False)] = 2.5


class DrawingSpec(ClosedModel):
    schema_version: Literal[DRAWING_SCHEMA_VERSION]
    part_revision: Annotated[int, Field(ge=1, strict=True)]
    description_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    units: Literal["mm"]
    title: Text
    sheet: Sheet = Field(default_factory=Sheet)
    required_view_ids: Annotated[list[Identifier], Field(min_length=1, max_length=12)]
    views: Annotated[list[View], Field(min_length=1, max_length=12)]
    notes: Annotated[list[Note], Field(max_length=40)] = []
    uncertainty_markers: Annotated[list[Marker], Field(max_length=100)] = []

    @field_validator("views")
    @classmethod
    def bounded_entities(cls, views):
        if sum(len(v.geometry) + len(v.dimensions) for v in views) > 1000:
            raise ValueError("A sheet permits at most 1000 geometry and dimension entities.")
        return views


def description_digest(description: dict[str, Any]) -> str:
    """Use the same canonical description bytes as the part service."""
    data = json.dumps(description, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def drawing_schema() -> dict[str, Any]:
    return {"schema_version": DRAWING_SCHEMA_VERSION, "schema": DrawingSpec.model_json_schema(),
            "scope": "Supplied 2D view geometry. Native DXF dimensions and a PDF from the same entities.",
            "unsupported": ["automatic CAD projection", "automatic section extraction", "automatic source interpretation",
                            "automatic drawing-to-solid equivalence", "semantic PMI", "general GD&T validation"]}


def _resolve(value, parameters, unit="mm"):
    if isinstance(value, DrawingRef):
        parameter = parameters.get(value.parameter)
        if parameter is None or parameter.value is None:
            raise ValueError(f"Unknown or unresolved drawing parameter: {value.parameter}.")
        if parameter.unit != unit:
            raise ValueError(f"Parameter {value.parameter} requires unit {unit}.")
        result = parameter.value * value.factor + value.offset
    else:
        result = value
    if not math.isfinite(result) or abs(result) > 100000:
        raise ValueError("A resolved drawing value must be finite and within 100000 units.")
    return float(result)


def _point(value, parameters):
    return [_resolve(v, parameters) for v in value]


def _anchor(reference, geometry):
    item = geometry.get(reference.primitive)
    if item is None:
        raise ValueError(f"Unknown dimension primitive: {reference.primitive}.")
    point = reference.point
    if item["type"] == "line":
        if point not in {"start", "end"}:
            raise ValueError("Line anchors require start or end.")
        return item[point]
    if point == "center":
        return item["center"]
    if item["type"] == "arc":
        if point not in {"start", "end"}:
            raise ValueError("Arc anchors require center, start, or end.")
        angle = math.radians(item[point + "_angle"])
        offset = (math.cos(angle), math.sin(angle))
    else:
        choices = {"left": (-1, 0), "right": (1, 0), "top": (0, 1), "bottom": (0, -1)}
        if point not in choices:
            raise ValueError("Circle anchors require center, left, right, top, or bottom.")
        offset = choices[point]
    return [item["center"][i] + item["radius"] * offset[i] for i in (0, 1)]


def _bounds(item):
    if item["type"] == "line":
        a, b = item["start"], item["end"]
        return [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]
    cx, cy = item["center"]
    radius = item["radius"]
    if item["type"] == "circle":
        return [cx - radius, cy - radius, cx + radius, cy + radius]
    start, end = item["start_angle"], item["end_angle"]
    sweep = (end - start) % 360
    angles = [start, end] + [a for a in (0, 90, 180, 270) if (a - start) % 360 <= sweep]
    points = [(cx + radius * math.cos(math.radians(a)), cy + radius * math.sin(math.radians(a))) for a in angles]
    return [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]


def _inside(inner, outer):
    return all((inner[0] >= outer[0] - 1e-6, inner[1] >= outer[1] - 1e-6,
                inner[2] <= outer[2] + 1e-6, inner[3] <= outer[3] + 1e-6))


def _overlap(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 0.05 and min(a[3], b[3]) - max(a[1], b[1]) > 0.05


def drawing_validate(spec: dict[str, Any], description: dict[str, Any], revision: int) -> dict[str, Any]:
    """Resolve parameter references and check bounded drawing declarations."""
    defects: list[dict] = []
    try:
        drawing = DrawingSpec.model_validate(spec)
        part = parse_description(description)
    except (ValidationError, ValueError) as error:
        return {"status": "fail", "defects": [{"code": "schema", "message": str(error)[:3000]}]}

    def fail(code, identifier, message):
        defects.append({"code": code, "id": identifier, "message": message})

    if drawing.part_revision != revision or drawing.description_sha256 != description_digest(description):
        fail("stale_binding", "drawing", "The drawing requires the current part revision and description hash.")
    sheet = drawing.sheet
    usable = [sheet.margin, sheet.margin, sheet.width - sheet.margin, sheet.height - sheet.margin]
    parameters = {p.name: p for p in part.parameters}
    evidence = {e.id: e for e in part.evidence}
    features = {f.id for f in part.features}
    labels: list[dict] = []
    views = []
    measurements = []
    ids: set[str] = set()
    label_ids: set[str] = set()

    def unique(identifier):
        if identifier in ids:
            fail("duplicate_id", identifier, "Drawing identifiers must be unique across the sheet.")
        ids.add(identifier)

    def check_evidence(identifier, refs):
        for ref in refs:
            if ref not in evidence:
                fail("unknown_evidence", identifier, f"Unknown evidence: {ref}.")

    def label(identifier, text, position, bounds=usable, centered=False):
        if identifier in label_ids:
            fail("duplicate_label_id", identifier, "Annotation identifiers must be unique, including generated sheet labels.")
        label_ids.add(identifier)
        if "%%" in text:
            fail("text_control", identifier, "DXF text control sequences are not permitted.")
        height = sheet.text_height
        width = max(height, len(text) * height * 0.7)
        x, y = position
        box = [x - width / 2 if centered else x, y - height * 0.35, x + width / 2 if centered else x + width, y + height * 1.1]
        if not _inside(box, bounds):
            fail("label_clipping", identifier, "A label exceeds its view frame or sheet margin.")
        labels.append({"id": identifier, "text": text, "position": list(position), "bounds": box, "centered": centered})

    label("sheet_title", drawing.title, (sheet.margin + 2, sheet.margin + 3))
    label("sheet_units", f"Units: mm | Part revision: {revision}", (sheet.margin + 2, sheet.margin + 9))
    for view in drawing.views:
        unique(view.id)
        frame = list(view.frame)
        if frame[2] <= frame[0] or frame[3] <= frame[1] or not _inside(frame, usable):
            fail("view_frame", view.id, "A view needs ordered bounds inside the sheet margin.")
        for other in views:
            if _overlap(frame, other["frame"]):
                fail("view_overlap", view.id, f"View frames overlap: {other['id']}.")
        if view.kind == "section" and (not view.section_note or not any(g.style == "section" for g in view.geometry)):
            fail("section_definition", view.id, "A supplied section needs a cutting-plane note and section line geometry.")

        def transform(p):
            return [view.origin[i] + view.scale * p[i] for i in (0, 1)]

        label(view.id + "_label", f"{view.label} | Scale {view.scale:g}:1", (frame[0] + 2, frame[3] - 4), frame)
        if view.section_note:
            label(view.id + "_section", view.section_note, (frame[0] + 2, frame[1] + 3), frame)
        geometry = {}
        for primitive in view.geometry:
            unique(primitive.id)
            check_evidence(primitive.id, primitive.evidence_ids)
            if not set(primitive.feature_ids) <= features:
                fail("unknown_feature", primitive.id, "Every primitive must identify existing part features.")
            item = primitive.model_dump()
            try:
                if isinstance(primitive, Line):
                    item.update(start=_point(primitive.start, parameters), end=_point(primitive.end, parameters))
                    if math.dist(item["start"], item["end"]) <= 1e-7:
                        raise ValueError("A line requires distinct endpoints.")
                else:
                    item.update(center=_point(primitive.center, parameters), radius=_resolve(primitive.radius, parameters))
                    if item["radius"] <= 0:
                        raise ValueError("A radius must be positive.")
                    if isinstance(primitive, Arc):
                        item.update(start_angle=_resolve(primitive.start_angle, parameters, "deg"),
                                    end_angle=_resolve(primitive.end_angle, parameters, "deg"))
                        if (item["end_angle"] - item["start_angle"]) % 360 <= 1e-7:
                            raise ValueError("An arc requires a nonzero counterclockwise sweep less than 360 degrees.")
                box = _bounds(item)
                transformed = transform(box[:2]) + transform(box[2:])
                if not _inside(transformed, frame):
                    fail("geometry_clipping", primitive.id, "Geometry exceeds its view frame.")
                geometry[primitive.id] = item
            except ValueError as error:
                fail("geometry", primitive.id, str(error))
        dimensions = []
        for dimension in view.dimensions:
            unique(dimension.id)
            check_evidence(dimension.id, dimension.evidence_ids)
            item = dimension.model_dump()
            try:
                item["expected"] = _resolve(dimension.expected, parameters, "deg" if dimension.type == "angular" else "mm")
                item["label_position"] = _point(dimension.label_position, parameters)
                if isinstance(dimension, LinearDimension):
                    p1, p2 = _anchor(dimension.p1, geometry), _anchor(dimension.p2, geometry)
                    delta = [p2[i] - p1[i] for i in (0, 1)]
                    actual = abs(delta[0]) if dimension.axis == "horizontal" else abs(delta[1]) if dimension.axis == "vertical" else math.dist(p1, p2)
                    item.update(p1=p1, p2=p2, angle=0.0 if dimension.axis == "horizontal" else 90.0 if dimension.axis == "vertical" else math.degrees(math.atan2(delta[1], delta[0])))
                elif isinstance(dimension, RoundDimension):
                    primitive = geometry.get(dimension.primitive)
                    if not primitive or primitive["type"] not in {"circle", "arc"}:
                        raise ValueError("A round dimension requires a circle or arc.")
                    delta = [item["label_position"][i] - primitive["center"][i] for i in (0, 1)]
                    if math.hypot(*delta) <= 1e-7:
                        raise ValueError("A round dimension label must differ from its center.")
                    leader_angle = math.degrees(math.atan2(delta[1], delta[0])) % 360
                    if primitive["type"] == "arc" and (leader_angle - primitive["start_angle"]) % 360 > (primitive["end_angle"] - primitive["start_angle"]) % 360 + 1e-6:
                        raise ValueError("The radius leader must touch the arc sweep.")
                    actual = primitive["radius"] * (2 if dimension.type == "diameter" else 1)
                    item.update(center=primitive["center"], radius=primitive["radius"])
                else:
                    first, second = geometry.get(dimension.first_line), geometry.get(dimension.second_line)
                    if not first or not second or first["type"] != "line" or second["type"] != "line":
                        raise ValueError("An angular dimension requires two lines.")
                    if math.dist(first["start"], second["start"]) > 1e-6:
                        raise ValueError("Angular dimension lines must share their start vertex.")
                    c = first["start"]
                    a, b = first["end"], second["end"]
                    actual = (math.degrees(math.atan2(b[1] - c[1], b[0] - c[0]) - math.atan2(a[1] - c[1], a[0] - c[0]))) % 360
                    if not 0.001 < actual < 180:
                        raise ValueError("Supported angular dimensions have a counterclockwise angle between zero and 180 degrees.")
                    item.update(center=c, p1=a, p2=b)
                if actual <= 1e-7 or abs(actual - item["expected"]) > max(1e-6, abs(actual) * 1e-7):
                    raise ValueError(f"Dimension geometry measures {actual:g}; expected {item['expected']:g}.")
                item["actual"] = actual
                prefix = "R" if dimension.type == "radius" else "D" if dimension.type == "diameter" else ""
                suffix = " deg" if dimension.type == "angular" else ""
                label(dimension.id, f"{prefix}{actual:.4f}".rstrip("0").rstrip(".") + suffix, transform(item["label_position"]), frame, centered=True)
                dimensions.append(item)
                measurements.append({"id": dimension.id, "view_id": view.id, "expected": item["expected"], "actual": actual,
                                     "unit": "deg" if dimension.type == "angular" else "mm", "evidence_ids": list(dimension.evidence_ids), "status": "pass"})
            except ValueError as error:
                fail("dimension_geometry", dimension.id, str(error))
        views.append({**view.model_dump(), "geometry": list(geometry.values()), "dimensions": dimensions})
    present = {v["id"] for v in views}
    if len(drawing.required_view_ids) != len(set(drawing.required_view_ids)) or not set(drawing.required_view_ids) <= present:
        fail("required_views", "drawing", "Required views must be distinct and present.")
    if not measurements:
        fail("missing_dimensions", "drawing", "A technical drawing requires at least one valid native dimension.")
    for index, note in enumerate(drawing.notes):
        check_evidence(f"note_{index}", note.evidence_ids)
        label(f"note_{index}", note.text, note.position)
    marked = set()
    marked_features = set()
    marked_primitives = set()
    markers = []
    for marker in drawing.uncertainty_markers:
        unique(marker.id)
        check_evidence(marker.id, marker.evidence_ids)
        view = next((v for v in views if v["id"] == marker.view_id), None)
        primitive = next((p for p in view["geometry"] if p["id"] == marker.primitive_id), None) if view else None
        if not primitive:
            fail("marker_target", marker.id, "An uncertainty marker requires a primitive in its view.")
            continue
        if not set(marker.evidence_ids) & set(primitive["evidence_ids"]):
            fail("marker_evidence", marker.id, "Marker evidence must identify its target geometry.")
        try:
            local_position = _point(marker.position, parameters)
            position = [view["origin"][i] + view["scale"] * local_position[i] for i in (0, 1)]
            statuses = sorted({evidence[e].status for e in marker.evidence_ids if e in evidence})
            text = f"[{','.join(statuses)}] {marker.text}"
            label(marker.id, text, position, view["frame"])
            anchor = primitive["start"] if primitive["type"] == "line" else primitive["center"]
            target = [view["origin"][i] + view["scale"] * anchor[i] for i in (0, 1)]
            markers.append({**marker.model_dump(), "position": position, "target": target, "text": text})
            marked.update(marker.evidence_ids)
            marked_features.update((ref, feature) for ref in marker.evidence_ids for feature in primitive["feature_ids"])
            marked_primitives.add((view["id"], primitive["id"]))
        except ValueError as error:
            fail("marker_parameter", marker.id, str(error))
    required_markers = {e.id for e in part.evidence if e.status in {"assumed", "inferred", "unresolved"}}
    required_markers.update(e for flag in part.review_flags for e in flag.evidence_ids)
    if required_markers - marked:
        fail("unmarked_uncertainty", "drawing", f"Missing uncertainty markers for: {', '.join(sorted(required_markers - marked))}.")
    # A shared evidence identifier must not hide uncertainty at another feature.
    # A feature needs one marked location; repeated views need no duplicate mark.
    projected_features = {feature for view in views for primitive in view["geometry"] for feature in primitive["feature_ids"]}
    feature_parameters = {feature.id: {name for name, _ in _references(feature.model_dump())} for feature in part.features}
    feature_evidence = {feature.id: set(feature.evidence_ids) for feature in part.features}
    for feature, names in feature_parameters.items():
        for name in names:
            if name in parameters:
                feature_evidence[feature].update(parameters[name].evidence_ids)
    for view in views:
        for primitive in view["geometry"]:
            for feature in primitive["feature_ids"]:
                feature_evidence.setdefault(feature, set()).update(primitive["evidence_ids"])
    uncertain = {e.id for e in part.evidence if e.status in {"assumed", "inferred", "unresolved"}}
    required_features = {(ref, feature) for feature in projected_features
                         for ref in feature_evidence.get(feature, set()) & uncertain}
    for flag in part.review_flags:
        affected = {flag.target_id} if flag.target_id in features else {
            feature for feature, names in feature_parameters.items() if flag.target_id in names}
        if flag.target_id in evidence:
            affected.update(feature for feature, refs in feature_evidence.items() if flag.target_id in refs)
        required_features.update((ref, feature) for feature in affected & projected_features for ref in flag.evidence_ids)
    for ref, feature in sorted(required_features - marked_features):
        fail("unmarked_feature_uncertainty", feature,
             f"Add a visible marker for evidence {ref} at affected feature {feature}.")
    for view in views:
        dimensioned = {d["primitive"] for d in view["dimensions"] if d["type"] in {"radius", "diameter"}}
        for primitive in view["geometry"]:
            if (primitive["type"] in {"circle", "arc"} and primitive["id"] not in dimensioned
                    and (view["id"], primitive["id"]) not in marked_primitives):
                fail("unmarked_radius", primitive["id"], "A round primitive needs a radius or diameter dimension, or a visible uncertainty marker.")
    for index, first in enumerate(labels):
        for second in labels[index + 1:]:
            if _overlap(first["bounds"], second["bounds"]):
                fail("label_overlap", first["id"], f"Label overlaps {second['id']}.")
    return {"status": "fail" if defects else "pass", "defects": defects[:100], "measurements": measurements,
            "description_sha256": drawing.description_sha256, "part_revision": drawing.part_revision,
            "resolved": {**drawing.model_dump(), "views": views, "labels": labels, "uncertainty_markers": markers},
            "checks": {"binding": "fail" if any(d["code"] == "stale_binding" for d in defects) else "pass",
                       "declaration_and_layout": "fail" if defects else "pass", "source_accuracy": "not_tested",
                       "cad_equivalence": "not_tested", "projection_completeness": "not_tested"},
            "scope": "Checks supplied geometry, native dimension values, conservative label boxes, and declared view coverage. Independent source and CAD review is required."}
