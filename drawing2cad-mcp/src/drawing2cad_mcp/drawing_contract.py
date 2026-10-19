"""Bounded declarations for evidence-based technical drawing sheets."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, field_validator

from .drawing_contract_v2 import (
    GPS_PROFILE_ID, TITLE_BLOCK_MANDATORY, Border, CuttingPlane, Datum, Ellipse, Hatching, Projection, TitleBlock,
    ToleranceFrame, UnsupportedGps, ellipse_bounds, frame_review, gps_profile, projection_defects,
)
from .part_schema import ClosedModel, EvidenceIds, Identifier, Number, _references, parse_description

# Version 1.0 stays the default until the renderer supports the content of version 2.0.
DRAWING_SCHEMA_VERSION = "1.0"
DRAWING_SCHEMA_VERSION_2 = "2.0"
DRAWING_SCHEMA_VERSIONS = (DRAWING_SCHEMA_VERSION, DRAWING_SCHEMA_VERSION_2)
Text = Annotated[str, Field(min_length=1, max_length=180, pattern=r"^[^\x00-\x1f\x7f\\]+$")]
Point = tuple[Number, Number]


class DrawingRef(ClosedModel):
    parameter: Identifier
    factor: Annotated[float, Field(allow_inf_nan=False, strict=True, ge=-1000, le=1000)] = 1.0
    offset: Number = 0.0


Scalar = Number | DrawingRef
ModelPoint = tuple[Scalar, Scalar]
LOCAL_POINT_DESCRIPTION = "Local view (x, y) coordinates in unscaled mm. Sheet position = view.origin + view.scale * this point."
SHEET_POINT_DESCRIPTION = "Absolute sheet (x, y) position in mm, from the bottom-left corner; +X points right and +Y points up. No view transform applies."


class Primitive(ClosedModel):
    id: Identifier
    evidence_ids: EvidenceIds
    feature_ids: Annotated[list[Identifier], Field(min_length=1, max_length=100)]
    style: Literal["visible", "hidden", "center", "section"] = "visible"


class Line(Primitive):
    type: Literal["line"]
    start: ModelPoint = Field(description=LOCAL_POINT_DESCRIPTION)
    end: ModelPoint = Field(description=LOCAL_POINT_DESCRIPTION)


class Circle(Primitive):
    type: Literal["circle"]
    center: ModelPoint = Field(description=LOCAL_POINT_DESCRIPTION)
    radius: Scalar = Field(description="Radius in unscaled view mm. The sheet radius is view.scale * radius.")


class Arc(Primitive):
    type: Literal["arc"]
    center: ModelPoint = Field(description=LOCAL_POINT_DESCRIPTION)
    radius: Scalar = Field(description="Radius in unscaled view mm. The sheet radius is view.scale * radius.")
    start_angle: Scalar = Field(description="Angle in degrees, counterclockwise from the local +X direction.")
    end_angle: Scalar = Field(description="Angle in degrees, counterclockwise from the local +X direction.")


# Ellipses need schema 2.0.
Geometry = Annotated[Line | Circle | Arc | Ellipse, Field(discriminator="type")]


class Anchor(ClosedModel):
    primitive: Identifier
    point: Literal["start", "end", "center", "left", "right", "top", "bottom"] = Field(
        description="Line: start, end, or center (midpoint). Arc: center, start, or end. Circle: center, left, right, top, or bottom.")


class Dimension(ClosedModel):
    id: Identifier
    evidence_ids: EvidenceIds
    expected: Scalar = Field(description="Unscaled measured value in mm, or degrees for an angular dimension. View scale does not change this value.")
    label_position: ModelPoint = Field(description=LOCAL_POINT_DESCRIPTION)
    theoretically_exact: bool = Field(default=False, description="Schema 2.0: a theoretically exact dimension (ISO 1101), shown in a frame.")


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
    kind: Literal["orthographic", "section", "detail", "isometric"] = Field(
        description="isometric needs schema 2.0 and a projection with an isometric scale convention.")
    orientation: Literal["front", "top", "right", "left", "bottom", "rear", "isometric", "custom"] = Field(
        description="Declared view direction. This label does not rotate geometry or create a projection.")
    projection: Projection | None = Field(default=None, description="Schema 2.0: the parallel projection of this view. Necessary for an isometric view.")
    cutting_plane: CuttingPlane | None = Field(default=None, description="Schema 2.0: the cutting plane of a section view.")
    hatching: Annotated[list[Hatching], Field(max_length=20)] = Field(default=[], description="Schema 2.0: hatched cut surfaces of a section view.")
    origin: Point = Field(description=SHEET_POINT_DESCRIPTION + " This is the sheet position of local view point (0, 0).")
    frame: tuple[Number, Number, Number, Number] = Field(
        description="Absolute sheet bounds [xmin, ymin, xmax, ymax] in mm, from the bottom-left corner. Do not translate or scale these bounds by view.origin or view.scale. Keep geometry, dimensions, and labels inside this frame and the sheet margin. Reserve space for the view label at [xmin+2, ymax-4] and any section note at [xmin+2, ymin+3].")
    scale: Annotated[float, Field(gt=0, le=100, allow_inf_nan=False, strict=True)] = Field(default=1.0,
        description="Positive factor from local view mm to sheet mm. Applies to geometry and dimension/marker positions, not frames, notes, or text height.")
    geometry: Annotated[list[Geometry], Field(min_length=1, max_length=300)]
    dimensions: Annotated[list[Dim], Field(max_length=100)]
    section_note: Text | None = None


class Note(ClosedModel):
    text: Text = Field(description="Manufacturing instruction with its affected region, such as wall draft or inside floor fillets. Include units and identify exceptions. Text is not a geometry measurement or a substitute for a required radius or angular dimension.")
    position: Point = Field(description=SHEET_POINT_DESCRIPTION)
    evidence_ids: EvidenceIds = Field(description="Source evidence for this instruction. Review the note against the source and the current model measurements; automatic source completeness is not tested.")


class Marker(ClosedModel):
    """A visible uncertainty marker. Each evidence item with status assumed, inferred, or unresolved, and each review flag,
    needs a marker. Each projected feature that depends on such evidence through its own evidence, its parameters,
    or its drawn primitives also needs one marked location. Explicit evidence without a review flag needs no marker."""
    id: Identifier
    view_id: Identifier
    primitive_id: Identifier
    text: Text
    position: ModelPoint = Field(description=LOCAL_POINT_DESCRIPTION + " Use the referenced view_id.")
    evidence_ids: EvidenceIds


class Sheet(ClosedModel):
    width: Annotated[float, Field(ge=100, le=1200, allow_inf_nan=False, strict=True)] = Field(default=297.0, description="Sheet width in mm along +X.")
    height: Annotated[float, Field(ge=100, le=1200, allow_inf_nan=False, strict=True)] = Field(default=210.0, description="Sheet height in mm along +Y.")
    margin: Annotated[float, Field(ge=5, le=30, allow_inf_nan=False, strict=True)] = Field(default=10.0, description="Inset in sheet mm from each sheet edge.")
    text_height: Annotated[float, Field(ge=1.8, le=5, allow_inf_nan=False, strict=True)] = Field(default=2.5, description="Text height in sheet mm. View scale does not change it.")


class DrawingSpec(ClosedModel):
    schema_version: Literal[DRAWING_SCHEMA_VERSION, DRAWING_SCHEMA_VERSION_2]
    part_revision: Annotated[int, Field(ge=1, strict=True)]
    description_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    units: Literal["mm"]
    title: Text
    sheet: Sheet = Field(default_factory=Sheet)
    required_view_ids: Annotated[list[Identifier], Field(min_length=1, max_length=12)]
    views: Annotated[list[View], Field(min_length=1, max_length=12)]
    notes: Annotated[list[Note], Field(max_length=40)] = []
    uncertainty_markers: Annotated[list[Marker], Field(max_length=100)] = []
    title_block: TitleBlock | None = Field(default=None, description="Schema 2.0: title block data (ISO 7200).")
    border: Border | None = Field(default=None, description="Schema 2.0: drawing border (ISO 5457).")
    projection_symbol: Literal["first_angle", "third_angle"] | None = Field(default=None, description="Schema 2.0: projection method symbol.")
    datums: Annotated[list[Datum], Field(max_length=26)] = Field(default=[], description="Schema 2.0: datum features (ISO 5459).")
    tolerance_frames: Annotated[list[ToleranceFrame], Field(max_length=100)] = Field(default=[], description="Schema 2.0: geometrical tolerance frames (ISO 1101).")
    unsupported_gps: Annotated[list[UnsupportedGps], Field(max_length=100)] = Field(default=[], description="Schema 2.0: source GPS requirements outside the supported profile.")

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


def drawing_schema(schema_version: str = DRAWING_SCHEMA_VERSION) -> dict[str, Any]:
    if schema_version not in DRAWING_SCHEMA_VERSIONS:
        raise ValueError(f"Unknown drawing schema version: {schema_version}.")
    version_2 = schema_version == DRAWING_SCHEMA_VERSION_2
    return {"schema_version": schema_version, "supported_versions": list(DRAWING_SCHEMA_VERSIONS),
            "schema": _schema_2(DrawingSpec.model_json_schema()) if version_2 else _schema_1(DrawingSpec.model_json_schema()),
            **({"version_2": {
                "content": ["isometric view with a projection matrix", "parallel projection of other views", "ellipse",
                            "cutting plane and hatching", "title block (ISO 7200)", "border", "projection symbol",
                            "datums", "tolerance frames", "theoretically exact dimensions", "unsupported GPS requirements"],
                "rendering": "drawing_render rejects ellipses, hatching, cutting planes, sheet data, and GPS data until the renderer supports them. "
                             "drawing_validate checks them.",
                "isometry": "kind isometric needs a projection with view_direction along a body diagonal, equal projected axis lengths, "
                            "and 120 degrees between the projected axes. A label or an orientation does not create a projection.",
                "gps_profile": gps_profile()}} if version_2 else {}),
            "coordinates": {"sheet_origin": "bottom_left", "sheet_units": "mm", "positive_x": "right", "positive_y": "up",
                            "view_transform": "sheet_point = view.origin + view.scale * local_point",
                            "absolute_sheet_fields": ["views[].origin", "views[].frame", "notes[].position"],
                            "local_view_fields": ["views[].geometry", "views[].dimensions[].label_position", "uncertainty_markers[].position"],
                            "frame_order": ["xmin", "ymin", "xmax", "ymax"],
                            "generated_labels": {"view": "[frame.xmin+2, frame.ymax-4]",
                                                 "section_note": "[frame.xmin+2, frame.ymin+3]",
                                                 "title": "[margin+2, margin+3]", "units": "[margin+2, margin+9]"}},
            "scope": "Supplied 2D view geometry. Native DXF dimensions and a PDF from the same entities.",
            "unsupported": ["automatic CAD projection", "automatic section extraction", "automatic source interpretation",
                            "automatic drawing-to-solid equivalence", "semantic PMI",
                            "GD&T outside the supported profile" if version_2 else "general GD&T validation"]}


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
    if item["type"] == "ellipse":
        if point != "center":
            raise ValueError("Ellipse anchors require center.")
        return item["center"]
    if item["type"] == "line":
        if point == "center":
            return [(item["start"][i] + item["end"][i]) / 2 for i in (0, 1)]
        if point not in {"start", "end"}:
            raise ValueError("Line anchors require start, end, or center.")
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
    if item["type"] == "ellipse":
        return ellipse_bounds(item)
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


def _view_transform(view_id, origin, scale):
    return {"view_id": view_id, "origin": list(origin), "scale": scale, "rule": "sheet_point = origin + scale * local_point"}


def _rounded(value):
    """Round defect details to 1e-6 so that small clipping distances and small scales stay visible."""
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (list, tuple)):
        return [_rounded(item) for item in value]
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    return value


def _segment_crosses_box(a, b, box, inset=0.05):
    """Return whether segment a-b enters the box, reduced by a small inset (Liang-Barsky clipping)."""
    x0, y0, x1, y1 = box[0] + inset, box[1] + inset, box[2] - inset, box[3] - inset
    if x1 <= x0 or y1 <= y0:
        return False
    dx, dy = b[0] - a[0], b[1] - a[1]
    low, high = 0.0, 1.0
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        r = q / p
        if p < 0:
            low = max(low, r)
        else:
            high = min(high, r)
        if low > high:
            return False
    return True


def drawing_validate(spec: dict[str, Any], description: dict[str, Any], revision: int) -> dict[str, Any]:
    """Resolve parameter references and check bounded drawing declarations."""
    defects: list[dict] = []
    findings: list[dict] = []
    gps_frames: list[dict] = []
    try:
        drawing = DrawingSpec.model_validate(spec)
        part = parse_description(description)
    except (ValidationError, ValueError) as error:
        # Never echo rejected values, paths, or validator context to clients.
        errors = error.errors(include_url=False, include_context=False, include_input=False) if isinstance(error, ValidationError) else []
        fields = [{"location": ([str(item)[:100] for item in detail["loc"][:-1][:11]] + ["[unknown_field]"]
                                if detail["type"] == "extra_forbidden" else [str(item)[:100] for item in detail["loc"][:12]]), "type": detail["type"]}
                  for detail in errors[:20]]
        declared = spec.get("schema_version") if isinstance(spec, dict) else None
        return {"status": "fail", "diagnostic_eligible": False,
                "schema_version": declared if declared in DRAWING_SCHEMA_VERSIONS else None, "findings": [],
                "render_support": None,
                "defects": [{"code": "schema", "message": "The drawing or part does not match its schema.",
                             "fields": fields, "truncated": len(errors) > len(fields)}]}

    version_2 = drawing.schema_version == DRAWING_SCHEMA_VERSION_2
    if not version_2 and (used := _version_2_content(drawing)):
        return {"status": "fail", "diagnostic_eligible": False, "schema_version": drawing.schema_version, "findings": [],
                "render_support": _render_support(drawing),
                "defects": [{"code": "schema_version", "id": "drawing", "fields": used[:20],
                             "message": "This content needs schema_version 2.0."}]}

    def fail(code, identifier, message, **details):
        # Layout defects give the computed sheet bounds, so that the agent can move the item without guessing.
        defects.append({"code": code, "id": identifier, "message": message, **{k: _rounded(v) for k, v in details.items()}})

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

    def label(identifier, text, position, bounds=usable, centered=False, transform=None):
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
            fail("label_clipping", identifier, "A label exceeds its view frame or sheet margin.",
                 label_bounds=box, allowed_bounds=list(bounds), **({"view_transform": transform} if transform else {}))
        labels.append({"id": identifier, "text": text, "position": list(position), "bounds": box, "centered": centered})

    label("sheet_title", drawing.title, (sheet.margin + 2, sheet.margin + 3))
    label("sheet_units", f"Units: mm | Part revision: {revision}", (sheet.margin + 2, sheet.margin + 9))
    for view in drawing.views:
        unique(view.id)
        frame = list(view.frame)
        if frame[2] <= frame[0] or frame[3] <= frame[1] or not _inside(frame, usable):
            fail("view_frame", view.id, "A view needs ordered bounds inside the sheet margin.", frame=frame, allowed_bounds=usable)
        for other in views:
            if _overlap(frame, other["frame"]):
                fail("view_overlap", view.id, f"View frames overlap: {other['id']}.", frame=frame, other_id=other["id"],
                     other_frame=other["frame"])
        if version_2:
            if view.kind == "isometric" and view.projection is None:
                fail("projection_missing", view.id, "An isometric view needs a projection. A label or an orientation does not create one.")
            if view.projection is not None:
                for message in projection_defects(view.kind, view.projection):
                    fail("projection", view.id, message)
            if view.kind == "section":
                if view.cutting_plane is None or not view.hatching or view.projection is None:
                    fail("section_definition", view.id, "A section view needs a cutting plane, hatching, and a projection.")
            elif view.cutting_plane is not None or view.hatching:
                fail("section_definition", view.id, "Only a section view has a cutting plane or hatching.")
        elif view.kind == "section" and (not view.section_note or not any(g.style == "section" for g in view.geometry)):
            fail("section_definition", view.id, "A supplied section needs a cutting-plane note and section line geometry.")

        def transform(p):
            return [view.origin[i] + view.scale * p[i] for i in (0, 1)]

        view_transform = _view_transform(view.id, view.origin, view.scale)

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
                elif isinstance(primitive, Ellipse):
                    item.update(center=[float(v) for v in primitive.center], major_axis=[float(v) for v in primitive.major_axis])
                    if math.hypot(*item["major_axis"]) <= 1e-7:
                        raise ValueError("An ellipse requires a nonzero major axis.")
                    if not 1e-7 < (primitive.end_parameter - primitive.start_parameter) <= 360 + 1e-9:
                        raise ValueError("An ellipse requires an increasing parameter range of at most 360 degrees.")
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
                    fail("geometry_clipping", primitive.id, "Geometry exceeds its view frame.",
                         local_bounds=box, sheet_bounds=transformed, frame=frame, view_transform=view_transform)
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
                label(dimension.id, f"{prefix}{actual:.4f}".rstrip("0").rstrip(".") + suffix, transform(item["label_position"]), frame,
                      centered=True, transform=view_transform)
                dimensions.append(item)
                measurements.append({"id": dimension.id, "view_id": view.id, "expected": item["expected"], "actual": actual,
                                     "unit": "deg" if dimension.type == "angular" else "mm", "evidence_ids": list(dimension.evidence_ids), "status": "pass"})
            except ValueError as error:
                fail("dimension_geometry", dimension.id, str(error))
        for hatch in view.hatching:
            unknown = [ref for ref in hatch.boundary_primitive_ids if ref not in geometry]
            if unknown:
                fail("hatching", view.id, "Hatching boundaries must be primitives of the section view: " + ", ".join(unknown) + ".")
            elif len(set(hatch.boundary_primitive_ids)) != len(hatch.boundary_primitive_ids):
                fail("hatching", view.id, "A hatching boundary must not repeat a primitive.")
            elif open_points := _open_ends([geometry[ref] for ref in hatch.boundary_primitive_ids]):
                fail("hatching", view.id, "The hatching boundary is not closed. Each end point must meet another end point.",
                     open_points=open_points[:6])
        views.append({**view.model_dump(), "geometry": list(geometry.values()), "dimensions": dimensions})
    present = {v["id"] for v in views}
    if version_2:
        _check_sections(drawing, views, evidence, fail, findings)
        _check_gps(drawing, views, features, evidence, fail, findings, gps_frames)
        _check_sheet_items(drawing, findings)
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
            label(marker.id, text, position, view["frame"], transform=_view_transform(view["id"], view["origin"], view["scale"]))
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
        status = {e.id: e.status for e in part.evidence}
        missing = sorted(required_markers - marked)
        fail("unmarked_uncertainty", "drawing",
             "Missing uncertainty markers for: " + ", ".join(f"{ref} ({status.get(ref, 'review flag')})" for ref in missing) + ".",
             evidence_ids=missing)
    # A shared evidence identifier must not hide uncertainty at another feature.
    # A feature needs one marked location; repeated views need no duplicate mark.
    projected_features = {feature for view in views for primitive in view["geometry"] for feature in primitive["feature_ids"]}
    feature_parameters = {feature.id: {name for name, _ in _references(feature.model_dump())} for feature in part.features}
    feature_evidence = {feature.id: set(feature.evidence_ids) for feature in part.features}
    # Record why each evidence item applies to a feature, so that a missing marker names its cause.
    origins: dict[tuple[str, str], set[str]] = {}
    for feature in part.features:
        for ref in feature.evidence_ids:
            origins.setdefault((ref, feature.id), set()).add("feature evidence")
    for feature, names in feature_parameters.items():
        for name in names:
            if name in parameters:
                feature_evidence[feature].update(parameters[name].evidence_ids)
                for ref in parameters[name].evidence_ids:
                    origins.setdefault((ref, feature), set()).add(f"parameter {name}")
    for view in views:
        for primitive in view["geometry"]:
            for feature in primitive["feature_ids"]:
                feature_evidence.setdefault(feature, set()).update(primitive["evidence_ids"])
                for ref in primitive["evidence_ids"]:
                    origins.setdefault((ref, feature), set()).add(f"primitive {primitive['id']}")
    uncertain = {e.id for e in part.evidence if e.status in {"assumed", "inferred", "unresolved"}}
    required_features = {(ref, feature) for feature in projected_features
                         for ref in feature_evidence.get(feature, set()) & uncertain}
    for flag in part.review_flags:
        affected = {flag.target_id} if flag.target_id in features else {
            feature for feature, names in feature_parameters.items() if flag.target_id in names}
        if flag.target_id in evidence:
            affected.update(feature for feature, refs in feature_evidence.items() if flag.target_id in refs)
        required_features.update((ref, feature) for feature in affected & projected_features for ref in flag.evidence_ids)
        for feature in affected & projected_features:
            for ref in flag.evidence_ids:
                origins.setdefault((ref, feature), set()).add(f"review flag {flag.id}")
    status = {e.id: e.status for e in part.evidence}
    for ref, feature in sorted(required_features - marked_features):
        causes = ", ".join(sorted(origins.get((ref, feature), {"review flag"})))
        kind = status.get(ref) if status.get(ref) in {"assumed", "inferred", "unresolved"} else "flagged"
        fail("unmarked_feature_uncertainty", feature,
             f"Add a visible marker for {kind} evidence {ref} at affected feature {feature} "
             f"(linked by {causes}). Explicit evidence without a review flag needs no marker.",
             evidence_id=ref)
    for view in views:
        dimensioned = {d["primitive"] for d in view["dimensions"] if d["type"] in {"radius", "diameter"}}
        annotated = [p for p in view["geometry"] if p["id"] in dimensioned]
        for primitive in view["geometry"]:
            if primitive["type"] not in {"circle", "arc"}:
                continue
            # Visibility can split one circular feature into several arcs.
            # Share its dimension only within one view and identical provenance.
            covered = any(
                set(primitive["feature_ids"]) == set(other["feature_ids"])
                and set(primitive["evidence_ids"]) == set(other["evidence_ids"])
                and math.dist(primitive["center"], other["center"]) <= 1e-7
                and abs(primitive["radius"] - other["radius"]) <= 1e-7
                for other in annotated
            )
            if (not covered
                    and (view["id"], primitive["id"]) not in marked_primitives):
                fail("unmarked_radius", primitive["id"], "A round primitive needs a radius or diameter dimension for the same circular feature and evidence in this view, or a visible uncertainty marker.")
    for index, first in enumerate(labels):
        for second in labels[index + 1:]:
            if _overlap(first["bounds"], second["bounds"]):
                fail("label_overlap", first["id"], f"Label overlaps {second['id']}.", label_bounds=first["bounds"],
                     other_id=second["id"], other_bounds=second["bounds"])
    for marker in markers:
        for other in labels:
            # A leader can start in its own label and end at geometry below a label. Only a crossing is a defect.
            ends = (marker["position"], marker["target"])
            if (other["id"] != marker["id"] and not any(_inside([*p, *p], other["bounds"]) for p in ends)
                    and _segment_crosses_box(*ends, other["bounds"])):
                fail("leader_overlap", marker["id"], f"The marker leader crosses label {other['id']}. Move the marker label.",
                     leader=[marker["position"], marker["target"]], other_id=other["id"], other_bounds=other["bounds"])
    layout_codes = {"label_overlap", "label_clipping", "geometry_clipping", "view_overlap", "leader_overlap"}
    isometric = [v for v in drawing.views if v.kind == "isometric"]
    version_checks = {
        "isometric_projection": ("fail" if any(d["code"] in {"projection", "projection_missing"} and d["id"] in {v.id for v in isometric}
                                               for d in defects) else "pass" if isometric else "not_tested"),
        "gps_profile": ("fail" if any(d["code"].startswith("gps") for d in defects)
                        else "needs_review" if any(f["code"].startswith("gps") for f in findings)
                        else "pass" if gps_frames else "not_applicable"),
        "sheet_items": "needs_review" if any(f["code"].startswith("sheet") or f["code"].startswith("title_block") for f in findings) else "pass",
    } if version_2 else {}
    return {"status": "fail" if defects else "pass", "defects": defects[:100], "measurements": measurements,
            "schema_version": drawing.schema_version, "findings": findings[:100], "render_support": _render_support(drawing),
            **({"gps": {"profile": GPS_PROFILE_ID, "frames": gps_frames}} if version_2 else {}),
            "diagnostic_eligible": bool(defects) and all(item["code"] in layout_codes for item in defects),
            "total_defects": len(defects), "defects_truncated": len(defects) > 100,
            "description_sha256": drawing.description_sha256, "part_revision": drawing.part_revision,
            "resolved": {**drawing.model_dump(), "views": views, "labels": labels, "uncertainty_markers": markers},
            "checks": {"binding": "fail" if any(d["code"] == "stale_binding" for d in defects) else "pass",
                       "declaration_and_layout": "fail" if defects else "pass", "source_accuracy": "not_tested",
                       "cad_equivalence": "not_tested", "projection_completeness": "not_tested", **version_checks},
            "scope": "Checks supplied geometry, native dimension values, conservative label boxes, and declared view coverage. Independent source and CAD review is required."}


def _render_support(drawing: DrawingSpec) -> dict[str, Any]:
    """Content that the renderer cannot render yet. drawing_render rejects a drawing with such content."""
    unsupported = []
    for view in drawing.views:
        if any(isinstance(g, Ellipse) for g in view.geometry):
            unsupported.append(f"views[{view.id}]: ellipse")
        if view.cutting_plane is not None or view.hatching:
            unsupported.append(f"views[{view.id}]: cutting plane or hatching")
        if any(d.theoretically_exact for d in view.dimensions):
            unsupported.append(f"views[{view.id}]: theoretically exact dimension")
    for name in ("title_block", "border", "projection_symbol"):
        if getattr(drawing, name) is not None:
            unsupported.append(name)
    for name in ("datums", "tolerance_frames", "unsupported_gps"):
        if getattr(drawing, name):
            unsupported.append(name)
    return {"renderable": not unsupported, "unsupported": unsupported}


def _check_sections(drawing: DrawingSpec, views: list[dict], evidence: dict, fail, findings) -> None:
    by_id = {view["id"]: view for view in views}
    models = {view.id: view for view in drawing.views}
    letters: dict[str, str] = {}
    for view in drawing.views:
        plane = view.cutting_plane
        if plane is None:
            continue
        if plane.letter in letters:
            fail("section_letter", view.id, f"Section letter {plane.letter} is also used by {letters[plane.letter]}.")
        letters[plane.letter] = view.id
        for ref in plane.evidence_ids:
            if ref not in evidence:
                fail("unknown_evidence", view.id, f"Unknown cutting-plane evidence: {ref}.")
        if f"{plane.letter}-{plane.letter}" not in view.label:
            fail("section_label", view.id, f"The section view label must contain {plane.letter}-{plane.letter}.")
        if math.sqrt(sum(float(c) ** 2 for c in plane.normal)) <= 1e-12:
            fail("cutting_plane", view.id, "The cutting-plane normal must not be zero.")
        source = by_id.get(plane.source_view_id)
        if source is None or plane.source_view_id == view.id:
            fail("cutting_plane", view.id, "The cutting line needs another view of this sheet as its source view.")
            continue
        start, end = ([source["origin"][i] + source["scale"] * float(p[i]) for i in (0, 1)] for p in plane.line)
        if math.dist(start, end) <= 1e-7:
            fail("cutting_plane", view.id, "The cutting line needs distinct endpoints.")
        box = [min(start[0], end[0]), min(start[1], end[1]), max(start[0], end[0]), max(start[1], end[1])]
        if not _inside(box, source["frame"]):
            fail("cutting_plane", view.id, "The cutting line exceeds the frame of its source view.", sheet_bounds=box,
                 frame=source["frame"])
        _check_trace(view.id, plane, models[plane.source_view_id].projection, fail, findings)
        if view.projection is not None:
            normal = [float(c) for c in plane.normal]
            length = math.sqrt(sum(c * c for c in normal))
            direction = [float(c) for c in view.projection.view_direction]
            direction_length = math.sqrt(sum(c * c for c in direction)) or 1.0
            sign = 1 if plane.viewing_side == "positive_normal" else -1
            cosine = sign * sum(a * b for a, b in zip(normal, direction)) / (length * direction_length or 1.0)
            if cosine < 1 - 1e-6:
                fail("cutting_plane", view.id, "The section view direction must agree with the cutting-plane normal and its viewing side.")


def _check_gps(drawing: DrawingSpec, views: list[dict], features: set[str], evidence: dict, fail, findings, frames) -> None:
    primitives = {(view["id"], primitive["id"]) for view in views for primitive in view["geometry"]}
    datum_letters: set[str] = set()
    invalid_datums: set[str] = set()
    for datum in drawing.datums:
        problems = []
        if datum.letter in datum_letters:
            problems.append(f"Datum letter {datum.letter} is defined more than once.")
        datum_letters.add(datum.letter)
        if not set(datum.feature_ids) <= features:
            problems.append("A datum must identify existing part features.")
        if (datum.view_id, datum.primitive_id) not in primitives:
            problems.append("A datum needs a primitive in its view.")
        problems += [f"Unknown evidence: {ref}." for ref in datum.evidence_ids if ref not in evidence]
        for message in problems:
            fail("gps_datum", datum.letter, message)
        if problems:
            invalid_datums.add(datum.letter)
    for frame in drawing.tolerance_frames:
        defects, review = frame_review(frame)
        unknown = [reference.letter for reference in frame.datums if reference.letter not in datum_letters]
        if unknown:
            defects.append("Unknown datum letters: " + ", ".join(unknown) + ".")
        invalid = sorted({reference.letter for reference in frame.datums} & invalid_datums)
        if invalid:
            defects.append("The frame refers to invalid datums: " + ", ".join(invalid) + ".")
        if not set(frame.feature_ids) <= features:
            defects.append("A tolerance frame must identify existing part features.")
        if (frame.view_id, frame.primitive_id) not in primitives:
            defects.append("A tolerance frame needs a primitive in its view.")
        defects += [f"Unknown evidence: {ref}." for ref in frame.evidence_ids if ref not in evidence]
        for message in defects:
            fail("gps_frame", frame.id, message)
        for message in review:
            findings.append({"code": "gps_unsupported", "id": frame.id, "status": "needs_review", "message": message})
        frames.append({"id": frame.id, "characteristic": frame.characteristic,
                       "status": "fail" if defects else "needs_review" if review else "pass",
                       "defects": defects, "review": review})
    for item in drawing.unsupported_gps:
        unknown = [f"Unknown evidence: {ref}." for ref in item.evidence_ids if ref not in evidence]
        for message in unknown:
            fail("gps_evidence", item.id, message)
        findings.append({"code": "gps_unsupported", "id": item.id, "status": "needs_review",
                         "message": f"Outside the supported profile: {item.literal_text} ({item.reason})"})
        frames.append({"id": item.id, "characteristic": None, "status": "fail" if unknown else "needs_review",
                       "defects": unknown, "review": [item.reason]})


def _check_sheet_items(drawing: DrawingSpec, findings) -> None:
    """Required items of a complete drawing. A missing item is a review finding, not a layout defect."""
    def need(code, identifier, message):
        findings.append({"code": code, "id": identifier, "status": "needs_review", "message": message})

    if not any(view.kind == "isometric" for view in drawing.views):
        need("sheet_isometric_view", "drawing", "A complete-service drawing needs an isometric view.")
    if drawing.border is None:
        need("sheet_border", "drawing", "The drawing has no border.")
    if drawing.projection_symbol is None:
        need("sheet_projection_symbol", "drawing", "The drawing has no projection symbol.")
    if drawing.title_block is None:
        need("title_block_missing", "drawing", "The drawing has no title block.")
    else:
        for name in TITLE_BLOCK_MANDATORY:
            if getattr(drawing.title_block, name) is None:
                need("title_block_field", name, f"The title block field {name} is empty. Record it from the source or as a decision.")


def render_gate(report: dict[str, Any]) -> dict[str, Any]:
    """Reject validated content that the renderer cannot draw. Return the report unchanged otherwise."""
    support = report.get("render_support")
    if not support or support["renderable"]:
        return report
    defect = {"code": "render_unsupported", "id": "drawing",
              "message": "drawing_render cannot render this content yet: " + ", ".join(support["unsupported"][:20]) + "."}
    total = report.get("total_defects", len(report["defects"])) + 1
    checks = {**report.get("checks", {}), "render_support": "fail"}
    return {**report, "status": "fail", "diagnostic_eligible": False, "defects": [defect, *report["defects"]][:100],
            "total_defects": total, "defects_truncated": total > 100, "checks": checks}


def _version_2_content(drawing: DrawingSpec) -> list[str]:
    """Fields of a drawing that only schema 2.0 permits."""
    used = [name for name in ("title_block", "border", "projection_symbol") if getattr(drawing, name) is not None]
    used += [name for name in ("datums", "tolerance_frames", "unsupported_gps") if getattr(drawing, name)]
    for view in drawing.views:
        if view.kind == "isometric" or view.orientation == "isometric":
            used.append(f"views[{view.id}].kind")
        used += [f"views[{view.id}].{name}" for name in ("projection", "cutting_plane", "hatching") if getattr(view, name)]
        if any(isinstance(g, Ellipse) for g in view.geometry):
            used.append(f"views[{view.id}].geometry")
        if any(d.theoretically_exact for d in view.dimensions):
            used.append(f"views[{view.id}].dimensions")
    return used


VERSION_2_DEFINITIONS = {"Projection", "Ellipse", "CuttingPlane", "Hatching", "TitleBlock", "Border", "Datum", "DatumReference",
                         "ToleranceFrame", "UnsupportedGps"}
VERSION_2_PROPERTIES = {"title_block", "border", "projection_symbol", "datums", "tolerance_frames", "unsupported_gps"}
VERSION_2_VIEW_PROPERTIES = {"projection", "cutting_plane", "hatching"}


def _schema_1(schema: dict[str, Any]) -> dict[str, Any]:
    """The JSON schema of version 1.0: the same model without the content that only version 2.0 permits."""
    definitions = schema.get("$defs", {})
    for name in VERSION_2_DEFINITIONS:
        definitions.pop(name, None)
    for name in VERSION_2_PROPERTIES:
        schema["properties"].pop(name, None)
    schema["properties"]["schema_version"] = {"const": DRAWING_SCHEMA_VERSION, "type": "string", "title": "Schema Version"}
    view = definitions["View"]["properties"]
    for name in VERSION_2_VIEW_PROPERTIES:
        view.pop(name, None)
    for name in ("kind", "orientation"):
        view[name]["enum"] = [value for value in view[name]["enum"] if value != "isometric"]
    for definition in definitions.values():
        definition.get("properties", {}).pop("theoretically_exact", None)

    def prune(node):
        if isinstance(node, dict):
            for key in ("oneOf", "anyOf"):
                if key in node:
                    node[key] = [item for item in node[key]
                                 if not (isinstance(item, dict) and item.get("$ref", "").removeprefix("#/$defs/") in VERSION_2_DEFINITIONS)]
            mapping = node.get("discriminator", {}).get("mapping")
            if mapping:
                node["discriminator"]["mapping"] = {k: v for k, v in mapping.items()
                                                    if v.removeprefix("#/$defs/") not in VERSION_2_DEFINITIONS}
            for value in node.values():
                prune(value)
        elif isinstance(node, list):
            for value in node:
                prune(value)
    prune(schema)
    return schema


def _open_ends(items: list[dict]) -> list[list[float]]:
    """End points of a boundary that do not meet another end point. Circles and full ellipses are closed."""
    ends: list[list[float]] = []
    for item in items:
        if item["type"] == "line":
            ends += [item["start"], item["end"]]
        elif item["type"] == "arc":
            ends += [[item["center"][i] + item["radius"] * f(math.radians(item[key + "_angle"])) for i, f in ((0, math.cos), (1, math.sin))]
                     for key in ("start", "end")]
        elif item["type"] == "ellipse" and item["end_parameter"] - item["start_parameter"] < 360 - 1e-9:
            major = item["major_axis"]
            minor = [-major[1] * item["ratio"], major[0] * item["ratio"]]
            for key in ("start_parameter", "end_parameter"):
                angle = math.radians(item[key])
                ends.append([item["center"][i] + math.cos(angle) * major[i] + math.sin(angle) * minor[i] for i in (0, 1)])
    unmatched = []
    for index, point in enumerate(ends):
        partners = sum(1 for other, candidate in enumerate(ends) if other != index and math.dist(point, candidate) <= 1e-6)
        if partners % 2 == 0:
            unmatched.append([round(point[0], 6), round(point[1], 6)])
    return unmatched


def _schema_2(schema: dict[str, Any]) -> dict[str, Any]:
    """The JSON schema of version 2.0. It accepts only the version value 2.0."""
    schema["properties"]["schema_version"] = {"const": DRAWING_SCHEMA_VERSION_2, "type": "string", "title": "Schema Version"}
    return schema


def _check_trace(view_id: str, plane, projection, fail, findings) -> None:
    """Compare the cutting line with the trace of the cutting plane in the source view.

    The projection has no translation, so this check covers the directions only. It does not check plane.origin.
    """
    if projection is None:
        findings.append({"code": "section_trace", "id": view_id, "status": "needs_review",
                         "message": "The source view has no projection. The cutting line is not checked against the cutting plane."})
        return
    normal = [float(c) for c in plane.normal]
    direction = [float(c) for c in projection.view_direction]
    normal_length = math.sqrt(sum(c * c for c in normal))
    direction_length = math.sqrt(sum(c * c for c in direction))
    if normal_length <= 1e-12 or direction_length <= 1e-12:
        return
    if abs(sum(a * b for a, b in zip(normal, direction))) / (normal_length * direction_length) > 1e-6:
        fail("cutting_plane", view_id, "The source view must show the cutting plane as a line: the normal must be perpendicular to its view direction.")
        return
    projected = [sum(float(m) * n for m, n in zip(row, normal)) for row in projection.matrix]
    line = [float(plane.line[1][i]) - float(plane.line[0][i]) for i in (0, 1)]
    scale = math.hypot(*projected) * math.hypot(*line)
    if scale > 1e-12 and abs(projected[0] * line[0] + projected[1] * line[1]) / scale > 1e-6:
        fail("cutting_plane", view_id, "The cutting line is not parallel to the trace of the cutting plane in the source view.")
