"""Versioned, bounded part descriptions for the maintained CAD worker."""
from __future__ import annotations

from typing import Annotated, Any, Literal
from copy import deepcopy
import math

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PART_SCHEMA_VERSION = "1.1"
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
Number = Annotated[float, Field(allow_inf_nan=False, ge=-100000, le=100000, strict=True)]
Positive = Annotated[float, Field(gt=0, le=100000, allow_inf_nan=False, strict=True)]
AxisName = Literal["X", "Y", "Z", "-X", "-Y", "-Z"]
FEATURE_COORDINATE_FRAMES = {
    "X": {"local_x": [0, 1, 0], "local_y": [0, 0, 1], "local_z": [1, 0, 0]},
    "-X": {"local_x": [0, 1, 0], "local_y": [0, 0, -1], "local_z": [-1, 0, 0]},
    "Y": {"local_x": [1, 0, 0], "local_y": [0, 0, -1], "local_z": [0, 1, 0]},
    "-Y": {"local_x": [1, 0, 0], "local_y": [0, 0, 1], "local_z": [0, -1, 0]},
    "Z": {"local_x": [1, 0, 0], "local_y": [0, 1, 0], "local_z": [0, 0, 1]},
    "-Z": {"local_x": [1, 0, 0], "local_y": [0, -1, 0], "local_z": [0, 0, -1]},
}
FEATURE_AXIS_DESCRIPTION = (
    "Signed local Z direction in global coordinates. Read x-feature-coordinate-frames in this schema "
    "for the local X and Y basis before supplying profile coordinates. For axis Y, local x is global +X "
    "and local y is global -Z; height or depth extends along global +Y."
)


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


DiagnosticNumber = Annotated[float, Field(allow_inf_nan=False, ge=-1e9, le=1e9, strict=True)]
DiagnosticPoint = tuple[DiagnosticNumber, DiagnosticNumber, DiagnosticNumber]


class SelectedEdgeDiagnostic(ClosedModel):
    geometry: Literal["line", "circle", "ellipse", "hyperbola", "parabola", "bezier", "bspline", "offset", "other"]
    center: DiagnosticPoint
    bbox_min: DiagnosticPoint
    bbox_max: DiagnosticPoint
    length_mm: Annotated[float, Field(allow_inf_nan=False, ge=0, le=1e9, strict=True)]

    @model_validator(mode="after")
    def ordered(self):
        if any(lo > hi for lo, hi in zip(self.bbox_min, self.bbox_max)):
            raise ValueError("Diagnostic edge bounds must be ordered.")
        return self


class EdgeSelectionDiagnostic(ClosedModel):
    expected_count: Annotated[int, Field(ge=1, le=1000, strict=True)]
    selected_count: Annotated[int, Field(ge=0, le=1000000, strict=True)]
    selected_edges: Annotated[list[SelectedEdgeDiagnostic], Field(max_length=64)]
    truncated: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def consistent_count(self):
        if len(self.selected_edges) != min(64, self.selected_count) or self.truncated != (self.selected_count > 64):
            raise ValueError("Diagnostic counts and truncation must agree.")
        return self


class SourceRegion(ClosedModel):
    source_id: Annotated[str, Field(min_length=1, max_length=200)]
    source_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    page: Annotated[int, Field(ge=1, le=10000, strict=True)]
    view: Annotated[str, Field(min_length=1, max_length=100)]
    region: tuple[Number, Number, Number, Number]
    coordinate_system: Literal["pdf_points", "pixels", "normalized_displayed"] = "pdf_points"

    @model_validator(mode="after")
    def ordered(self):
        x0, y0, x1, y1 = self.region
        if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
            raise ValueError("The source region must have nonnegative, ordered bounds.")
        if self.coordinate_system == "normalized_displayed" and (x1 > 1 or y1 > 1):
            raise ValueError("Normalized displayed source coordinates must be between zero and one.")
        return self


class Evidence(ClosedModel):
    id: Identifier
    status: Literal["explicit", "derived", "inferred", "assumed", "unresolved"]
    source: SourceRegion
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
    mandatory: bool = True
    review_status: Literal["open", "accepted", "rejected"] = "open"


class ValueRef(ClosedModel):
    parameter: Identifier


Scalar = Number | ValueRef
Vector3 = tuple[Scalar, Scalar, Scalar]
EvidenceIds = Annotated[list[Identifier], Field(min_length=1, max_length=100)]


class Parameter(ClosedModel):
    name: Identifier
    value: Number | None
    unit: Literal["mm", "deg", "dimensionless"] = "mm"
    evidence_ids: EvidenceIds


class Feature(ClosedModel):
    id: Identifier
    evidence_ids: EvidenceIds


class BoxFeature(Feature):
    type: Literal["box"]
    operation: Literal["base", "add"]
    length: Scalar
    width: Scalar
    height: Scalar
    origin: Vector3 = (0.0, 0.0, 0.0)


class CylinderFeature(Feature):
    type: Literal["cylinder"]
    operation: Literal["base", "add"]
    diameter: Scalar
    height: Scalar
    origin: Vector3 = (0.0, 0.0, 0.0)
    axis: AxisName = Field(default="Z", description=FEATURE_AXIS_DESCRIPTION)
    taper_angle: Scalar = Field(default=0.0, description="Positive degrees reduce the radius along the signed axis. Diameter is specified at origin.")


class ExtrusionFeature(Feature):
    type: Literal["extrusion"]
    operation: Literal["base", "add"]
    points: Annotated[list[tuple[Scalar, Scalar]], Field(min_length=3, max_length=256,
        description="Closed profile points in local (x, y) coordinates. Use the basis selected by axis, not the global XY plane.")]
    height: Scalar
    origin: Vector3 = (0.0, 0.0, 0.0)
    axis: AxisName = Field(default="Z", description=FEATURE_AXIS_DESCRIPTION)
    taper_angle: Scalar = 0.0


class LineSegment(ClosedModel):
    kind: Literal["line"]
    start: tuple[Scalar, Scalar]
    end: tuple[Scalar, Scalar]


class ArcSegment(ClosedModel):
    kind: Literal["three_point_arc"]
    start: tuple[Scalar, Scalar]
    mid: tuple[Scalar, Scalar]
    end: tuple[Scalar, Scalar]


class ProfileExtrusionFeature(Feature):
    type: Literal["profile_extrusion"]
    operation: Literal["base", "add"]
    segments: Annotated[list[Annotated[LineSegment | ArcSegment, Field(discriminator="kind")]],
                        Field(min_length=2, max_length=256,
                              description="Closed profile segments in local (x, y) coordinates. Use the basis selected by axis.")]
    height: Scalar
    origin: Vector3 = (0.0, 0.0, 0.0)
    axis: AxisName = Field(default="Z", description=FEATURE_AXIS_DESCRIPTION)
    taper_angle: Scalar = 0.0


class ThreadData(ClosedModel):
    designation: Annotated[str, Field(min_length=1, max_length=80)]
    pitch: Positive
    hand: Literal["right", "left"] = "right"
    representation: Literal["tap_drill"] = "tap_drill"


class HoleFeature(Feature):
    type: Literal["hole"]
    position: Vector3
    axis: AxisName = "-Z"
    diameter: Scalar
    extent: Literal["through", "blind"] = "through"
    depth: Scalar | None = None
    style: Literal["plain", "counterbore", "countersink"] = "plain"
    counter_diameter: Scalar | None = None
    counter_depth: Scalar | None = None
    angle: Scalar | None = None
    thread: ThreadData | None = None
    drill_angle: Scalar | None = None

    @model_validator(mode="after")
    def required_fields(self):
        if self.extent == "blind" and self.depth is None:
            raise ValueError("A blind hole requires depth.")
        if self.extent == "through" and self.depth is not None:
            raise ValueError("A through hole must not specify depth.")
        if self.extent != "blind" and self.drill_angle is not None:
            raise ValueError("Only a blind hole can specify drill_angle.")
        if self.style != "plain" and self.counter_diameter is None:
            raise ValueError("A counterbore or countersink requires counter_diameter.")
        if self.style == "counterbore" and self.counter_depth is None:
            raise ValueError("A counterbore requires counter_depth.")
        if self.style == "countersink" and self.angle is None:
            raise ValueError("A countersink requires its included angle.")
        if self.style == "plain" and any(v is not None for v in (self.counter_diameter, self.counter_depth, self.angle)):
            raise ValueError("A plain hole must not specify counter fields.")
        if self.style == "counterbore" and self.angle is not None:
            raise ValueError("A counterbore must not specify angle.")
        if self.style == "countersink" and self.counter_depth is not None:
            raise ValueError("A countersink depth is derived from diameter and angle.")
        return self


class BoxCut(ClosedModel):
    shape: Literal["box"]
    length: Scalar
    width: Scalar
    depth: Scalar


class CylinderCut(ClosedModel):
    shape: Literal["cylinder"]
    diameter: Scalar
    depth: Scalar


class PolygonCut(ClosedModel):
    shape: Literal["polygon"]
    points: Annotated[list[tuple[Scalar, Scalar]], Field(min_length=3, max_length=256,
        description="Profile points in local (x, y) coordinates. Use the parent cut feature's axis basis.")]
    depth: Scalar


class ProfileCut(ClosedModel):
    shape: Literal["profile"]
    segments: Annotated[list[Annotated[LineSegment | ArcSegment, Field(discriminator="kind")]], Field(min_length=2, max_length=256)]
    depth: Scalar


class CutFeature(Feature):
    type: Literal["pocket", "cut"]
    profile: Annotated[BoxCut | CylinderCut | PolygonCut | ProfileCut, Field(discriminator="shape")]
    origin: Vector3
    axis: AxisName = Field(default="Z", description=FEATURE_AXIS_DESCRIPTION)
    taper_angle: Scalar = Field(default=0.0, description="Positive degrees reduce the tool profile along the signed cut axis. The profile is specified at origin.")


class AdjacentPlane(ClosedModel):
    origin: tuple[Number, Number, Number]
    normal: tuple[Number, Number, Number]

    @model_validator(mode="after")
    def nonzero_normal(self):
        if math.hypot(*self.normal) <= 1e-9:
            raise ValueError("The adjacent plane normal must be nonzero.")
        return self


class EdgeSelector(ClosedModel):
    geometry: Literal["line", "circle", "any"] = "any"
    center_min: tuple[Number, Number, Number]
    center_max: tuple[Number, Number, Number]
    expected_count: Annotated[int, Field(ge=1, le=1000, strict=True)]
    tolerance: Positive = 0.00001
    radius: Positive | None = None
    adjacent_plane: AdjacentPlane | None = Field(default=None, description="Require a neighboring planar face on this plane. Use global coordinates; selector tolerance is in mm.")

    @model_validator(mode="after")
    def ordered(self):
        if any(lo > hi for lo, hi in zip(self.center_min, self.center_max)):
            raise ValueError("Edge selector minimum must not exceed maximum.")
        if self.radius is not None and self.geometry == "line":
            raise ValueError("A radius selector requires circular edges.")
        return self


class DressFeature(Feature):
    type: Literal["chamfer", "fillet"]
    size: Scalar
    selector: EdgeSelector


FeatureType = Annotated[BoxFeature | CylinderFeature | ExtrusionFeature | ProfileExtrusionFeature | HoleFeature | CutFeature | DressFeature, Field(discriminator="type")]


class Measurement(ClosedModel):
    id: Identifier
    kind: Literal["bbox", "volume", "hole", "arc_radius", "outer_diameter", "axis_distance", "plane_distance", "section_distance", "surface_radius", "cone_angle", "cone_width", "line_angle", "plane_angle", "draft_angle", "fillet_radius"]
    evidence_ids: EvidenceIds
    basis: Literal["printed_dimension", "independent_measurement"]
    tolerance: Positive = 0.01
    expected: Annotated[list[Annotated[float, Field(gt=0, le=1e15, allow_inf_nan=False, strict=True)]], Field(min_length=1, max_length=3)]
    position: tuple[Number, Number, Number] | None = Field(
        default=None, description="Source measurement anchor. For hole, this identifies the cylinder axis, not an entry surface. For outer_diameter, this identifies both the cylinder axis and the axial station. At a shoulder with different outer diameters, select a station within one cylindrical face.")
    axis: AxisName | None = Field(
        default=None, description="Measurement axis. For a hole with entry_position, this must point from the opening into the part.")
    axial_length: Positive | None = None
    entry_position: tuple[Number, Number, Number] | None = Field(
        default=None, description="Optional source-derived center of the planar circular opening where the hole cavity meets the part surface. A stepped bore is one connected cavity: each of its bores uses the outer opening as entry, never an internal shoulder. The check traverses connected full cylinders, cones, and planar shoulders to that opening. If omitted, entry_side is not_tested.")
    second_position: tuple[Number, Number, Number] | None = None
    component: Literal["distance", "X", "Y", "Z"] = "distance"
    direction: tuple[Number, Number, Number] | None = None
    spatial_tolerance: Positive | None = Field(default=None, description="Surface anchor tolerance in mm for draft_angle and fillet_radius; default 0.01 mm. Their numerical tolerance is separately given by tolerance (degrees or mm).")
    fillet_section_normal: tuple[Number, Number, Number] | None = Field(default=None, description="Optional global normal of the circular fillet section. Required for bounded principal-curvature measurement of a non-analytic fillet. Does not change analytic cylinder or torus axis matching.")

    @model_validator(mode="after")
    def required_fields(self):
        count = 3 if self.kind == "bbox" else 1
        if len(self.expected) != count or any(value <= 0 for value in self.expected):
            raise ValueError(f"{self.kind} requires {count} positive expected value(s).")
        located = self.kind in {"hole", "arc_radius", "outer_diameter", "axis_distance", "plane_distance", "section_distance", "surface_radius", "cone_angle", "cone_width", "line_angle", "plane_angle", "draft_angle", "fillet_radius"}
        if self.direction is not None:
            if self.kind not in {"plane_distance", "section_distance", "surface_radius", "line_angle", "plane_angle", "draft_angle", "fillet_radius"} or self.axis is not None or math.hypot(*self.direction) <= 1e-9:
                raise ValueError("A nonzero direction can replace axis only for plane, section, surface-radius, or line measurements.")
        if located and (self.position is None or (self.axis is None and self.direction is None)):
            raise ValueError(f"A {self.kind} measurement requires position and axis or a supported direction.")
        if not located and (self.position is not None or self.axis is not None):
            raise ValueError("This measurement does not use position or axis.")
        if self.spatial_tolerance is not None and self.kind not in {"draft_angle", "fillet_radius"}:
            raise ValueError("Only draft_angle and fillet_radius use spatial_tolerance.")
        if self.fillet_section_normal is not None and (self.kind != "fillet_radius" or math.hypot(*self.fillet_section_normal) <= 1e-9):
            raise ValueError("Only fillet_radius can specify a nonzero fillet_section_normal.")
        if self.kind not in {"hole", "outer_diameter"} and self.axial_length is not None:
            raise ValueError("Only a cylindrical measurement uses axial_length.")
        if self.entry_position is not None:
            if self.kind != "hole":
                raise ValueError("Only a hole measurement can specify entry_position.")
            perpendicular = [index for index, key in enumerate("XYZ") if key != self.axis[-1]]
            if math.hypot(*(self.entry_position[index] - self.position[index] for index in perpendicular)) > self.tolerance:
                raise ValueError("The hole entry must be on the measured axis within its declared tolerance.")
        if (self.kind in {"axis_distance", "plane_distance", "section_distance"}) != (self.second_position is not None):
            raise ValueError("Axis and plane distances require second_position; other measurements must omit it.")
        if self.kind == "section_distance":
            vector = self.direction or tuple((-1 if self.axis.startswith("-") else 1) if key == self.axis[-1] else 0 for key in "XYZ")
            direction = tuple(value / math.hypot(*vector) for value in vector)
            delta = tuple(b - a for a, b in zip(self.position, self.second_position))
            along = sum(a * b for a, b in zip(delta, direction))
            if math.hypot(*(value - along * unit for value, unit in zip(delta, direction))) > 1e-6:
                raise ValueError("Section distance anchors must lie on the same measurement line.")
        if self.component != "distance" and (self.kind != "axis_distance" or self.component == self.axis[-1]):
            raise ValueError("Only axis_distance supports a component perpendicular to the selected axis.")
        return self


class ReviewFlag(ClosedModel):
    id: Identifier
    target_id: Identifier
    status: Literal["open", "accepted", "rejected"]
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
    evidence_ids: EvidenceIds


class PartDescription(ClosedModel):
    schema_version: Literal["1.0", "1.1"]
    name: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}$")]
    units: Literal["mm"]
    coordinate_system: Literal["right_handed_xyz"]
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=2000)]
    parameters: Annotated[list[Parameter], Field(max_length=1000)] = Field(default_factory=list)
    features: Annotated[list[FeatureType], Field(min_length=1, max_length=500)]
    measurements: Annotated[list[Measurement], Field(max_length=1000)] = Field(default_factory=list)
    review_flags: Annotated[list[ReviewFlag], Field(max_length=2000)] = Field(default_factory=list)
    expected_solids: Literal[1] = 1


def description_schema() -> dict[str, Any]:
    """Return the public JSON Schema. Array order is feature execution order."""
    schema = PartDescription.model_json_schema()
    schema["x-feature-coordinate-frames"] = {
        "origin": "Feature origin is a point in global XYZ coordinates.",
        "transform": "global_point = origin + x * local_x + y * local_y + z * local_z",
        "extrusion": "Profile points have local z=0. Positive height or cut depth extends along local_z.",
        "basis": deepcopy(FEATURE_COORDINATE_FRAMES),
    }
    return schema


def _pointer(parts: tuple | list, description: Any) -> str:
    # Pydantic adds union branch names. They are not keys in the input JSON.
    current, tokens = description, []
    branches = {"box", "cylinder", "extrusion", "profile_extrusion", "profile", "line", "three_point_arc", "hole", "pocket", "cut", "chamfer", "fillet", "polygon", "float", "constrained-float", "ValueRef"}
    for item in parts:
        if isinstance(current, dict) and item not in current and item in branches:
            continue
        tokens.append(str(item).replace("~", "~0").replace("/", "~1"))
        if isinstance(current, dict):
            current = current.get(item)
        elif isinstance(current, (list, tuple)) and isinstance(item, int) and item < len(current):
            current = current[item]
        elif item in branches:
            tokens.pop()
        else:
            current = None
    return "/" + "/".join(tokens)


def _references(value: Any, path: str = ""):
    if isinstance(value, dict):
        if set(value) == {"parameter"}:
            yield value["parameter"], path
        else:
            for key, child in value.items():
                yield from _references(child, path + "/" + key)
    elif isinstance(value, (tuple, list)):
        for index, child in enumerate(value):
            yield from _references(child, path + "/" + str(index))


def part_validate(description: dict[str, Any]) -> dict[str, Any]:
    """Validate structure, references, and unresolved mandatory inputs."""
    defects = []
    try:
        part = PartDescription.model_validate(description)
    except ValidationError as exc:
        return {"status": "fail", "defects": [{"code": "schema", "pointer": _pointer(e["loc"], description), "message": e["msg"]} for e in exc.errors(include_input=False)[:100]], "review_items": []}

    def defect(code, pointer, message):
        defects.append({"code": code, "pointer": pointer, "message": message})

    for collection in ("evidence", "parameters", "features", "measurements", "review_flags"):
        seen = set()
        for index, item in enumerate(getattr(part, collection)):
            key = item.name if collection == "parameters" else item.id
            if key in seen:
                defect("duplicate_id", f"/{collection}/{index}", f"Duplicate identifier: {key}.")
            seen.add(key)
    evidence = {item.id: item for item in part.evidence}
    parameters = {item.name: item for item in part.parameters}
    for collection in ("parameters", "features", "measurements", "review_flags"):
        for index, item in enumerate(getattr(part, collection)):
            for ref in item.evidence_ids:
                if ref not in evidence:
                    defect("unknown_evidence", f"/{collection}/{index}/evidence_ids", f"Unknown evidence: {ref}.")
                elif evidence[ref].status == "unresolved" or evidence[ref].review_status == "rejected":
                    defect("unresolved_input", f"/{collection}/{index}/evidence_ids", f"Resolve referenced evidence {ref} before construction.")
    for index, item in enumerate(part.evidence):
        if item.mandatory and item.status == "unresolved":
            defect("unresolved_input", f"/evidence/{index}", "A mandatory input has no reasonable resolved value.")
    for name, pointer in _references(part.model_dump()):
        if name not in parameters:
            defect("unknown_parameter", pointer, f"Unknown parameter: {name}.")
        elif parameters[name].value is None:
            defect("unresolved_input", pointer, f"Parameter {name} has no value.")
        elif pointer.startswith("/features/"):
            unit = "deg" if pointer.endswith(("/angle", "/taper_angle", "/drill_angle")) else "mm"
            if parameters[name].unit != unit:
                defect("parameter_unit", pointer, f"This feature value requires {unit}.")
    for index, feature in enumerate(part.features):
        if part.schema_version == "1.0" and (
            isinstance(feature, CutFeature) and (isinstance(feature.profile, ProfileCut) or feature.taper_angle != 0.0)
            or isinstance(feature, CylinderFeature) and feature.taper_angle != 0.0
            or isinstance(feature, DressFeature) and feature.selector.adjacent_plane is not None
        ):
            defect("schema_version", f"/features/{index}", "This feature requires schema_version 1.1.")
        operation = getattr(feature, "operation", None)
        if index == 0 and operation != "base":
            defect("feature_order", "/features/0", "The first feature must be a base solid.")
        if index > 0 and operation == "base":
            defect("feature_order", f"/features/{index}", "Only the first feature can be a base solid.")
        if hasattr(feature, "taper_angle"):
            try:
                if abs(resolve(feature.taper_angle, part)) >= 45:
                    defect("invalid_taper", f"/features/{index}/taper_angle", "The taper angle magnitude must be less than 45 degrees.")
            except (ValueError, StopIteration):
                pass
        segment_profile = feature.profile if isinstance(feature, CutFeature) and isinstance(feature.profile, ProfileCut) else feature
        if isinstance(segment_profile, (ProfileExtrusionFeature, ProfileCut)):
            try:
                segments = [(segment, tuple(resolve(v, part) for v in segment.start),
                             tuple(resolve(v, part) for v in segment.end)) for segment in segment_profile.segments]
                for segment_index, (segment, start, end) in enumerate(segments):
                    prefix = "/profile" if isinstance(segment_profile, ProfileCut) else ""
                    pointer = f"/features/{index}{prefix}/segments/{segment_index}"
                    if math.dist(start, end) <= 1e-7:
                        defect("invalid_profile", pointer, "Segment endpoints must be distinct.")
                    if math.dist(end, segments[(segment_index + 1) % len(segments)][1]) > 1e-7:
                        defect("profile_gap", pointer, "Ordered segments must connect and close within 1e-7 mm.")
                    if isinstance(segment, ArcSegment):
                        middle = tuple(resolve(v, part) for v in segment.mid)
                        first = (middle[0] - start[0], middle[1] - start[1])
                        last = (end[0] - start[0], end[1] - start[1])
                        cross = abs(first[0] * last[1] - first[1] * last[0])
                        scale = math.hypot(*first) * math.hypot(*last)
                        if scale <= 1e-14 or cross <= scale * 1e-8:
                            defect("invalid_arc", pointer, "Arc start, mid, and end must be distinct and noncollinear.")
            except (ValueError, StopIteration):
                pass
        for field in ("length", "width", "height", "diameter", "depth", "counter_diameter", "counter_depth", "size", "angle", "drill_angle"):
            value = getattr(feature, field, None)
            if value is not None:
                try:
                    number = resolve(value, part)
                except (ValueError, StopIteration):
                    continue
                if number <= 0 or (field in {"angle", "drill_angle"} and number >= 180):
                    defect("invalid_dimension", f"/features/{index}/{field}", "Dimensions must be positive; included angles must be less than 180 degrees.")
        profile = getattr(feature, "profile", None)
        if profile is not None:
            for field in ("length", "width", "depth", "diameter"):
                value = getattr(profile, field, None)
                if value is not None:
                    try:
                        number = resolve(value, part)
                    except (ValueError, StopIteration):
                        continue
                    if number <= 0:
                        defect("invalid_dimension", f"/features/{index}/profile/{field}", "Profile dimensions must be positive.")
    targets = set(parameters) | {item.id for item in part.features} | set(evidence)
    for index, measurement in enumerate(part.measurements):
        if part.schema_version == "1.0" and measurement.kind in {"draft_angle", "fillet_radius"}:
            defect("schema_version", f"/measurements/{index}", "This measurement requires schema_version 1.1.")
    for index, flag in enumerate(part.review_flags):
        if flag.target_id not in targets:
            defect("unknown_target", f"/review_flags/{index}/target_id", "The review target does not exist.")
        if flag.status == "rejected":
            defect("rejected_review", f"/review_flags/{index}", "Resolve a rejected review item before construction.")
    review_items = [item.model_dump() for item in part.evidence if item.status != "explicit" or item.review_status == "rejected"]
    review_items += [item.model_dump() for item in part.review_flags]
    return {"status": "fail" if defects else "pass", "defects": defects[:100], "review_items": review_items}


def parse_description(description: dict[str, Any]) -> PartDescription:
    """Parse only a description that passes the domain checks."""
    result = part_validate(description)
    if result["status"] != "pass":
        raise ValueError(result)
    return PartDescription.model_validate(description)


def resolve(value: Scalar, part: PartDescription) -> float:
    """Resolve a literal or a named value. No expression evaluation is used."""
    if isinstance(value, ValueRef):
        number = next(item.value for item in part.parameters if item.name == value.parameter)
        if number is None:
            raise ValueError(f"Parameter {value.parameter} has no value.")
        return float(number)
    if not math.isfinite(value):
        raise ValueError("A dimension must be finite.")
    return float(value)
