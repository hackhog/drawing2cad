"""Versioned, bounded part descriptions for the maintained CAD worker."""
from __future__ import annotations

from typing import Annotated, Any, Literal
from copy import deepcopy
import math

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PART_SCHEMA_VERSION = "1.4"
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
    length: Scalar | None = Field(default=None, exclude_if=lambda value: value is None,
        description="Explicit thread length in mm from the hole entry along its signed axis. The drill tip is excluded. Only plain blind holes support this field. Omission leaves thread length unspecified.")


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
        if self.thread is not None and self.thread.length is not None and (self.extent != "blind" or self.style != "plain"):
            raise ValueError("Explicit thread length requires a plain blind hole.")
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
    expected: Annotated[list[Annotated[float, Field(gt=0, le=1e15, allow_inf_nan=False, strict=True)]], Field(
        min_length=1, max_length=3,
        description="Positive measured values in mm, except volume in mm3 and angles in degrees. bbox uses X, Y, Z order and requires three values; every other kind requires one.",
    )]
    position: tuple[Number, Number, Number] | None = Field(
        default=None,
        description="Global source anchor. For hole, use a point on the cylinder axis, not the entry surface. For arc_radius, use the circle center, not a point on the arc. For outer_diameter, use the axis at a station within one cylindrical face. For cone_angle and cone_width, use the cone axis at a station within the conical face. For surface_radius, line_angle, plane_angle, draft_angle, and fillet_radius, use the bounded target face or edge.",
    )
    axis: AxisName | None = Field(
        default=None,
        description="Signed global axis name. For a hole with entry_position, point from the opening into the part. Use direction only for the kinds listed in its field description.",
    )
    axial_length: Positive | None = None
    entry_position: tuple[Number, Number, Number] | None = Field(
        default=None, description="Optional source-derived center of the planar circular opening where the hole cavity meets the part surface. A stepped bore is one connected cavity: each of its bores uses the outer opening as entry, never an internal shoulder. The check traverses connected full cylinders, cones, and planar shoulders to that opening. If omitted, entry_side is not_tested.")
    second_position: tuple[Number, Number, Number] | None = Field(
        default=None,
        description="Second global anchor for axis_distance, plane_distance, and section_distance. For axis_distance, anchors identify distinct axes. For section_distance, anchors lie on the same measurement line.",
    )
    component: Literal["distance", "X", "Y", "Z"] = "distance"
    direction: tuple[Number, Number, Number] | None = Field(
        default=None,
        description="Optional nonzero global vector. It replaces axis only for plane_distance, section_distance, surface_radius, line_angle, plane_angle, draft_angle, and fillet_radius.",
    )
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


class ToleranceBase(ClosedModel):
    id: Identifier
    raw_text: Annotated[str, Field(min_length=1, max_length=500)]
    evidence_ids: EvidenceIds
    confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, strict=True)]
    resolution: Literal["resolved", "review_required"]
    scope: Literal["parameter", "part", "unassigned"]
    parameter_name: Identifier | None = None
    unit: Literal["mm", "deg", "dimensionless"] | None = None
    printed_nominal: Number | None = None


class DeviationTolerance(ToleranceBase):
    kind: Literal["deviation"]
    lower_deviation: Number
    upper_deviation: Number

    @model_validator(mode="after")
    def ordered(self):
        if self.lower_deviation > self.upper_deviation:
            raise ValueError("Deviation bounds must be ordered.")
        return self


class LimitsTolerance(ToleranceBase):
    kind: Literal["limits"]
    lower_limit: Number
    upper_limit: Number

    @model_validator(mode="after")
    def ordered(self):
        if self.lower_limit > self.upper_limit:
            raise ValueError("Limit bounds must be ordered.")
        return self


class FitTolerance(ToleranceBase):
    kind: Literal["fit"]
    designation: Annotated[str, Field(min_length=1, max_length=80)]


class GeneralTolerance(ToleranceBase):
    kind: Literal["general"]
    designation: Annotated[str, Field(min_length=1, max_length=160)]


class UnclearTolerance(ToleranceBase):
    kind: Literal["unclear"]
    reason: Annotated[str, Field(min_length=1, max_length=500)]


ToleranceType = Annotated[DeviationTolerance | LimitsTolerance | FitTolerance | GeneralTolerance | UnclearTolerance, Field(discriminator="kind")]


class DimensionChain(ClosedModel):
    id: Identifier
    role: Literal["part", "total"] = Field(description="The parts of a chain must add up to its total.")


class MeasuredSize(ClosedModel):
    value: Annotated[float, Field(gt=0, le=100000, allow_inf_nan=False, strict=True)] = Field(
        description="Measured size in part units at the calibrated scale of the view.")
    method: Literal["vector_geometry", "pdf_measure_distance", "pdf_measure_circle"]


class PrintedDimension(ClosedModel):
    """A printed dimension for cross-checks. It does not change the construction."""
    id: Identifier
    printed_text: Annotated[str, Field(min_length=1, max_length=120)] = Field(description="The printed text, unchanged.")
    nominal: Number
    unit: Literal["mm", "deg"] = "mm"
    evidence_ids: EvidenceIds
    dim_id: Identifier | None = Field(None, description="The same physical dimension in several views has the same dim_id.")
    chain: DimensionChain | None = None
    measured: MeasuredSize | None = None
    not_to_scale: bool = Field(False, description="True for a dimension marked as not to scale. Its measurement is not compared.")


class PartDescription(ClosedModel):
    schema_version: Literal["1.0", "1.1", "1.2", "1.3", "1.4"]
    name: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}$")]
    units: Literal["mm"]
    coordinate_system: Literal["right_handed_xyz"]
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=2000)]
    parameters: Annotated[list[Parameter], Field(max_length=1000)] = Field(default_factory=list)
    features: Annotated[list[FeatureType], Field(min_length=1, max_length=500)]
    measurements: Annotated[list[Measurement], Field(max_length=1000)] = Field(default_factory=list)
    tolerances: Annotated[list[ToleranceType], Field(max_length=1000)] = Field(default_factory=list, exclude_if=lambda value: not value)
    review_flags: Annotated[list[ReviewFlag], Field(max_length=2000)] = Field(default_factory=list)
    dimensions: Annotated[list[PrintedDimension], Field(max_length=2000)] = Field(
        default_factory=list, exclude_if=lambda value: not value)
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
    schema["x-measurement-guidance"] = {
        "value_counts": "bbox requires three positive values in X, Y, Z order. Every other kind requires one positive value.",
        "anchors": "Located kinds require position and axis or an allowed direction. direction is a nonzero global vector. It replaces axis only for plane_distance, section_distance, surface_radius, line_angle, plane_angle, draft_angle, and fillet_radius. plane_distance anchors lie on material faces, not bores or axes. section_distance anchors lie on one measurement line. axis_distance uses two distinct axes, not axial length.",
        "cylinders": "hole.position identifies the cylinder axis. axis points into the part when entry_position is supplied. arc_radius.position is the circle center, not a point on the arc. outer_diameter.position identifies the cylinder axis and a station within one cylindrical face. arc_radius measures a circular arc; outer_diameter measures a cylindrical outer face.",
        "examples": deepcopy(_MEASUREMENT_EXAMPLES),
    }
    return schema


_MEASUREMENT_EXAMPLES = {
    "bbox": {"kind": "bbox", "expected": [40.0, 20.0, 5.0]},
    "volume": {"kind": "volume", "expected": [4000.0]},
    "hole": {"kind": "hole", "expected": [6.0], "position": [10.0, 10.0, 5.0], "axis": "-Z"},
    "arc_radius": {"kind": "arc_radius", "expected": [8.0], "position": [20.0, 10.0, 0.0], "axis": "Z"},
    "outer_diameter": {"kind": "outer_diameter", "expected": [24.0], "position": [20.0, 10.0, 0.0], "axis": "Z"},
    "axis_distance": {"kind": "axis_distance", "expected": [12.0], "position": [0.0, 0.0, 0.0], "axis": "Z", "second_position": [12.0, 0.0, 0.0]},
    "plane_distance": {"kind": "plane_distance", "expected": [5.0], "position": [0.0, 0.0, 0.0], "direction": [0.0, 0.0, 1.0], "second_position": [0.0, 0.0, 5.0]},
    "section_distance": {"kind": "section_distance", "expected": [5.0], "position": [0.0, 0.0, 0.0], "axis": "Z", "second_position": [0.0, 0.0, 5.0]},
    "surface_radius": {"kind": "surface_radius", "expected": [10.0], "position": [20.0, 10.0, 0.0], "axis": "Z"},
    "cone_angle": {"kind": "cone_angle", "expected": [30.0], "position": [20.0, 10.0, 0.0], "axis": "Z"},
    "cone_width": {"kind": "cone_width", "expected": [4.0], "position": [20.0, 10.0, 0.0], "axis": "Z"},
    "line_angle": {"kind": "line_angle", "expected": [45.0], "position": [10.0, 0.0, 0.0], "direction": [1.0, 1.0, 0.0]},
    "plane_angle": {"kind": "plane_angle", "expected": [90.0], "position": [10.0, 0.0, 0.0], "direction": [0.0, 1.0, 0.0]},
    "draft_angle": {"kind": "draft_angle", "expected": [2.0], "position": [20.0, 10.0, 2.5], "axis": "Z"},
    "fillet_radius": {"kind": "fillet_radius", "expected": [2.0], "position": [20.0, 10.0, 2.5], "axis": "Z"},
}
_MEASUREMENT_EXAMPLES = {
    kind: {"id": "example", "evidence_ids": ["drawing"], "basis": "independent_measurement", **example}
    for kind, example in _MEASUREMENT_EXAMPLES.items()
}


def _pointer(parts: tuple | list, description: Any) -> str:
    # Pydantic adds union branch names. They are not keys in the input JSON.
    current, tokens = description, []
    branches = {"box", "cylinder", "extrusion", "profile_extrusion", "profile", "line", "three_point_arc", "hole", "pocket", "cut", "chamfer", "fillet", "polygon", "float", "constrained-float", "ValueRef", "deviation", "limits", "fit", "general", "unclear"}
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

    for collection in ("evidence", "parameters", "features", "measurements", "tolerances", "review_flags"):
        seen = set()
        for index, item in enumerate(getattr(part, collection)):
            key = item.name if collection == "parameters" else item.id
            if key in seen:
                defect("duplicate_id", f"/{collection}/{index}", f"Duplicate identifier: {key}.")
            seen.add(key)
    evidence = {item.id: item for item in part.evidence}
    parameters = {item.name: item for item in part.parameters}
    for collection in ("parameters", "features", "measurements", "tolerances", "review_flags", "dimensions"):
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
        if isinstance(feature, HoleFeature) and feature.thread is not None and feature.thread.length is not None:
            pointer = f"/features/{index}/thread/length"
            if part.schema_version not in {"1.2", "1.3", "1.4"}:
                defect("schema_version", pointer, "Explicit thread length requires schema_version 1.2 or later.")
            try:
                length = resolve(feature.thread.length, part)
                depth = resolve(feature.depth, part)
                if length <= 0 or length > depth:
                    defect("invalid_dimension", pointer, "Thread length must be positive and no greater than the cylindrical bore depth.")
            except (ValueError, StopIteration, TypeError):
                pass
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
    targets = set(parameters) | {item.id for item in part.features} | {item.id for item in part.tolerances} | set(evidence)
    if part.tolerances and part.schema_version not in {"1.3", "1.4"}:
        defect("schema_version", "/tolerances", "Tolerances require schema_version 1.3 or later.")
    open_flags = {flag.target_id for flag in part.review_flags if flag.status == "open"}
    for index, tolerance in enumerate(part.tolerances):
        pointer = f"/tolerances/{index}"
        if tolerance.scope == "parameter":
            parameter = parameters.get(tolerance.parameter_name)
            if parameter is None:
                defect("unknown_parameter", pointer + "/parameter_name", "A parameter tolerance requires an existing parameter_name.")
            elif tolerance.unit != parameter.unit:
                defect("parameter_unit", pointer + "/unit", "Tolerance and parameter units must agree.")
        elif tolerance.parameter_name is not None:
            defect("invalid_scope", pointer + "/parameter_name", "Only parameter scope uses parameter_name.")
        if isinstance(tolerance, (DeviationTolerance, LimitsTolerance)) and tolerance.unit is None:
            defect("missing_unit", pointer + "/unit", "Numeric tolerance bounds require a unit.")
        if (tolerance.scope == "unassigned" or isinstance(tolerance, UnclearTolerance) or tolerance.resolution == "review_required") and tolerance.id not in open_flags:
            defect("missing_review_flag", pointer, "An unresolved tolerance requires an open review flag.")
        if isinstance(tolerance, UnclearTolerance) and tolerance.resolution != "review_required":
            defect("invalid_resolution", pointer + "/resolution", "An unclear tolerance requires review.")
    for index, measurement in enumerate(part.measurements):
        if part.schema_version == "1.0" and measurement.kind in {"draft_angle", "fillet_radius"}:
            defect("schema_version", f"/measurements/{index}", "This measurement requires schema_version 1.1.")
    for index, flag in enumerate(part.review_flags):
        if flag.target_id not in targets:
            defect("unknown_target", f"/review_flags/{index}/target_id", "The review target does not exist.")
        if flag.status == "rejected":
            defect("rejected_review", f"/review_flags/{index}", "Resolve a rejected review item before construction.")
    if part.dimensions and part.schema_version != "1.4":
        defect("schema_version", "/dimensions", "Printed dimensions require schema_version 1.4.")
    seen_dimensions: set[str] = set()
    for index, item in enumerate(part.dimensions):
        if item.id in seen_dimensions:
            defect("duplicate_id", f"/dimensions/{index}", f"Duplicate identifier: {item.id}.")
        seen_dimensions.add(item.id)
    dimension_checks = _dimension_checks(part.dimensions, defect)
    review_items = [item.model_dump() for item in part.evidence if item.status != "explicit" or item.review_status == "rejected"]
    review_items += [item.model_dump() for item in part.review_flags]
    result = {"status": "fail" if defects else "pass", "defects": defects[:100], "review_items": review_items}
    if part.dimensions:
        result["dimension_checks"] = dimension_checks
    return result


# Printed against measured: the larger of an absolute and a relative limit.
DIMENSION_ABS_TOLERANCE = {"mm": 0.2, "deg": 0.5}
DIMENSION_REL_TOLERANCE = 0.01
_SUM_TOLERANCE = 1e-6


def _dimension_checks(dimensions: list[PrintedDimension], defect) -> dict[str, Any]:
    """Cross-check printed dimensions: chain sums, the same dimension in several views, and printed against measured.
    A check without the necessary data is not_tested. Messages give identifiers and numbers, never the printed text."""
    position = {}
    for n, item in enumerate(dimensions):
        position.setdefault(item.id, n)
    chains: dict[str, list[PrintedDimension]] = {}
    groups: dict[str, list[PrintedDimension]] = {}
    for item in dimensions:
        if item.chain is not None:
            chains.setdefault(item.chain.id, []).append(item)
        if item.dim_id is not None:
            groups.setdefault(item.dim_id, []).append(item)

    chain_results = []
    for chain_id, items in sorted(chains.items()):
        totals = [item for item in items if item.chain.role == "total"]
        parts = [item for item in items if item.chain.role == "part"]
        pointer = f"/dimensions/{position[items[0].id]}/chain"
        if len({item.unit for item in items}) > 1:
            defect("dimension_unit", pointer, f"Dimension chain {chain_id} mixes units.")
            chain_results.append({"chain": chain_id, "check": "fail", "reason": "mixed_units"})
            continue
        if len(totals) > 1:
            defect("dimension_chain", pointer, f"Dimension chain {chain_id} has {len(totals)} totals. A chain has one total.")
            chain_results.append({"chain": chain_id, "check": "fail", "reason": "several_totals"})
            continue
        if not totals or not parts:
            chain_results.append({"chain": chain_id, "check": "not_tested", "reason": "A chain needs one total and at least one part."})
            continue
        total, summed = totals[0].nominal, sum(item.nominal for item in parts)
        record = {"chain": chain_id, "total_id": totals[0].id, "part_ids": [item.id for item in parts],
                  "total": total, "sum_of_parts": round(summed, 9)}
        if abs(total - summed) > _SUM_TOLERANCE * max(1.0, abs(total)):
            defect("dimension_chain", pointer, f"Dimension chain {chain_id}: the parts add up to {summed:.6g}, the total is {total:.6g}.")
            chain_results.append({**record, "check": "fail"})
        else:
            chain_results.append({**record, "check": "pass"})

    view_results = []
    for dim_id, items in sorted(groups.items()):
        pointer = f"/dimensions/{position[items[0].id]}/dim_id"
        if len(items) < 2:
            view_results.append({"dim_id": dim_id, "ids": [items[0].id], "check": "not_tested", "reason": "Only one occurrence."})
            continue
        values = sorted({(item.nominal, item.unit) for item in items})
        record = {"dim_id": dim_id, "ids": [item.id for item in items], "values": [value for value, _ in values]}
        if len(values) > 1:
            defect("dimension_views", pointer, f"Dimension {dim_id} has different values: "
                   + ", ".join(f"{value:.6g} {unit}" for value, unit in values) + ".")
            view_results.append({**record, "check": "fail"})
        else:
            view_results.append({**record, "check": "pass"})

    measured_results = []
    for item in dimensions:
        if item.measured is None or item.not_to_scale:
            reason = "Marked as not to scale." if item.not_to_scale else "No measurement."
            measured_results.append({"id": item.id, "check": "not_tested", "reason": reason})
            continue
        allowed = max(DIMENSION_ABS_TOLERANCE[item.unit], DIMENSION_REL_TOLERANCE * abs(item.nominal))
        difference = item.measured.value - item.nominal
        record = {"id": item.id, "nominal": item.nominal, "measured": item.measured.value,
                  "difference": round(difference, 9), "allowed": allowed, "unit": item.unit}
        # The margin accepts a difference exactly at the limit despite binary rounding, for example 0.9 - 0.7.
        if abs(difference) > allowed + 1e-9 * max(1.0, abs(item.nominal)):
            defect("dimension_measured", f"/dimensions/{position[item.id]}/measured",
                   f"Dimension {item.id}: measured {item.measured.value:.6g} {item.unit}, printed {item.nominal:.6g} {item.unit}, "
                   f"allowed difference {allowed:.6g}. Check the reading and the calibration, or mark the dimension as not to scale.")
            measured_results.append({**record, "check": "fail"})
        else:
            measured_results.append({**record, "check": "pass"})

    every = chain_results + view_results + measured_results
    summary = {state: sum(1 for item in every if item["check"] == state) for state in ("pass", "fail", "not_tested")}
    return {"chains": chain_results, "cross_view": view_results, "measured": measured_results, "summary": summary}


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
