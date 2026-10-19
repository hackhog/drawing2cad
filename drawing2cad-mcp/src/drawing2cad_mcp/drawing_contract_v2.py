"""Declarations and rules of drawing contract 2.0: projections, isometric views, ellipses, sections, sheet data, and GPS.

Drawing contract 2.0 adds structured data for complete technical drawings. This module defines the data and its checks.
It does not derive views from a model and does not render. The renderer rejects 2.0 content that it cannot render.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import Field

from .part_schema import ClosedModel, EvidenceIds, Identifier, Number

Text = Annotated[str, Field(min_length=1, max_length=180, pattern=r"^[^\x00-\x1f\x7f\\]+$")]
Vector3 = tuple[Number, Number, Number]
Row3 = tuple[Number, Number, Number]
LOCAL_POINT = "Local view (x, y) coordinates in unscaled mm. Sheet position = view.origin + view.scale * this point."

GPS_PROFILE_ID = "drawing2cad-gps-1"
# Tolerance of the numerical projection checks. It is not a manufacturing tolerance.
PROJECTION_TOLERANCE = 1e-6
ISOMETRIC_FACTORS = {"isometric_drawing": math.sqrt(1.5), "isometric_projection": 1.0}


class Projection(ClosedModel):
    """A parallel projection from model coordinates to local view coordinates."""
    type: Literal["parallel"] = "parallel"
    view_direction: Vector3 = Field(description="Direction in model coordinates from the model toward the viewer. Its length does not matter.")
    up: Vector3 = Field(description="Model direction that points up on the sheet. It must not be parallel to view_direction.")
    handedness: Literal["right_handed"] = "right_handed"
    scale_convention: Literal["true_size", "isometric_drawing", "isometric_projection"] = Field(
        description="true_size: orthographic view at true size. isometric_drawing: each projected model axis has unit length (ISO 5456-3 simplified). "
                    "isometric_projection: the true isometric projection; each projected axis has length sqrt(2/3).")
    matrix: tuple[Row3, Row3] = Field(
        description="Rows that map a model point (x, y, z) to local view (x, y): local = matrix * model. "
                    "The rows must agree with view_direction, up, handedness, and scale_convention.")


class Ellipse(ClosedModel):
    """An ellipse or elliptical arc, for example a projected circle in an isometric view."""
    id: Identifier
    evidence_ids: EvidenceIds
    feature_ids: Annotated[list[Identifier], Field(min_length=1, max_length=100)]
    style: Literal["visible", "hidden", "center", "section"] = "visible"
    type: Literal["ellipse"]
    center: tuple[Number, Number] = Field(description=LOCAL_POINT)
    major_axis: tuple[Number, Number] = Field(description="Vector from the center to the end of the major axis, in unscaled local view mm.")
    ratio: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False, strict=True)] = Field(description="Minor axis length divided by major axis length.")
    start_parameter: Number = Field(default=0.0, description="Start parameter in degrees, counterclockwise from the major axis.")
    end_parameter: Number = Field(default=360.0, description="End parameter in degrees. 0 and 360 give a full ellipse.")
    approximation_error: Annotated[float, Field(ge=0, le=5, allow_inf_nan=False, strict=True)] = Field(
        description="Largest distance in unscaled mm between this curve and the exact projected curve. 0 for an exact ellipse.")


class CuttingPlane(ClosedModel):
    letter: Annotated[str, Field(pattern=r"^[A-Z]$")] = Field(description="Section letter. The section view label must contain 'L-L'.")
    origin: Vector3 = Field(description="A model point on the cutting plane, in mm.")
    normal: Vector3 = Field(description="Normal of the cutting plane in model coordinates.")
    viewing_side: Literal["positive_normal", "negative_normal"] = Field(
        description="The side from which the section is seen. The section arrows point from this side toward the plane.")
    source_view_id: Identifier = Field(description="The view that shows the cutting line, the arrows, and the letters.")
    line: tuple[tuple[Number, Number], tuple[Number, Number]] = Field(description="Cutting line in local coordinates of the source view.")
    evidence_ids: EvidenceIds


class Hatching(ClosedModel):
    boundary_primitive_ids: Annotated[list[Identifier], Field(min_length=1, max_length=100)] = Field(
        description="Primitives of this section view that make the closed boundary of the cut surface.")
    pattern: Literal["iso_lines"] = "iso_lines"
    angle: Annotated[float, Field(ge=0, lt=180, allow_inf_nan=False, strict=True)] = 45.0
    spacing: Annotated[float, Field(gt=0.5, le=20, allow_inf_nan=False, strict=True)] = 3.0


class TitleBlock(ClosedModel):
    """Data fields of ISO 7200. A field that the source does not state stays null and is a review finding."""
    legal_owner: Text | None = None
    identification_number: Text | None = None
    revision_index: Text | None = None
    date_of_issue: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")] | None = None
    document_type: Text | None = None
    creator: Text | None = None
    approval_person: Text | None = None
    sheet_number: Text | None = None
    language_code: Annotated[str, Field(pattern=r"^[a-z]{2}$")] | None = None


TITLE_BLOCK_MANDATORY = ("legal_owner", "identification_number", "date_of_issue", "document_type", "creator",
                         "approval_person", "sheet_number")


class Border(ClosedModel):
    zone_grid: bool = Field(default=False, description="Zone letters and numbers along the border (ISO 5457).")


class Datum(ClosedModel):
    letter: Annotated[str, Field(pattern=r"^[A-Z]{1,2}$")]
    feature_ids: Annotated[list[Identifier], Field(min_length=1, max_length=20)]
    view_id: Identifier
    primitive_id: Identifier
    evidence_ids: EvidenceIds


Characteristic = Literal["straightness", "flatness", "roundness", "cylindricity", "line_profile", "surface_profile",
                         "parallelism", "perpendicularity", "angularity", "position", "concentricity", "coaxiality",
                         "symmetry", "circular_runout", "total_runout"]
# ISO 1101 and ISO 2692 symbols. The supported profile accepts only M and L; the others are kept for review.
Modifier = Literal["M", "L", "E", "P", "F", "R", "CZ", "SZ", "T", "U", "ACS"]


class DatumReference(ClosedModel):
    letter: Annotated[str, Field(pattern=r"^[A-Z]{1,2}$")]
    modifiers: Annotated[list[Literal["M", "L"]], Field(max_length=1)] = []


class ToleranceFrame(ClosedModel):
    id: Identifier
    characteristic: Characteristic
    value: Annotated[float, Field(gt=0, le=100, allow_inf_nan=False, strict=True)] = Field(description="Tolerance value in mm.")
    zone: Literal["width", "diameter", "spherical_diameter"] = "width"
    modifiers: Annotated[list[Modifier], Field(max_length=4)] = []
    datums: Annotated[list[DatumReference], Field(max_length=3)] = Field(default=[], description="Datum references in their order: primary, secondary, tertiary.")
    feature_ids: Annotated[list[Identifier], Field(min_length=1, max_length=20)]
    view_id: Identifier
    primitive_id: Identifier
    position: tuple[Number, Number] = Field(description=LOCAL_POINT + " Use the view of view_id.")
    evidence_ids: EvidenceIds


class UnsupportedGps(ClosedModel):
    """A source GPS requirement that the supported profile cannot express. It always needs review."""
    id: Identifier
    literal_text: Text = Field(description="The requirement as the source shows it.")
    feature_ids: Annotated[list[Identifier], Field(max_length=20)] = []
    evidence_ids: EvidenceIds
    reason: Text


FORM = {"straightness", "flatness", "roundness", "cylindricity"}
PROFILE = {"line_profile", "surface_profile"}
ORIENTATION = {"parallelism", "perpendicularity", "angularity"}
LOCATION = {"position", "concentricity", "coaxiality", "symmetry"}
RUNOUT = {"circular_runout", "total_runout"}
NO_DIAMETER_ZONE = {"flatness", "roundness", "cylindricity", "line_profile", "surface_profile", "circular_runout",
                    "total_runout"}
SUPPORTED_MODIFIERS = {"M", "L"}
# Characteristics that the profile accepts automatically. Profiles need theoretically exact geometry, and
# concentricity and symmetry need derived features; the profile keeps them for review.
SUPPORTED_CHARACTERISTICS = FORM | ORIENTATION | {"position", "coaxiality"} | RUNOUT


def gps_profile() -> dict[str, Any]:
    return {"id": GPS_PROFILE_ID, "standards": ["ISO 1101:2017", "ISO 5459:2024", "ISO 8015:2011"],
            "supported_characteristics": sorted(SUPPORTED_CHARACTERISTICS),
            "supported_modifiers": sorted(SUPPORTED_MODIFIERS),
            "rules": {"form": "no datum references", "orientation_and_runout": "at least one datum reference",
                      "datum_references": "defined datum letters, distinct, at most three, in the given order",
                      "modifiers": "M and L exclude each other", "diameter_zone": "not for " + ", ".join(sorted(NO_DIAMETER_ZONE))},
            "review": "Unsupported characteristics, modifiers, datum modifiers, a position frame without datum, and unsupported requirements need review.",
            "scope": "A pass means that the declaration agrees with this bounded profile. It is not ISO conformity and not a manufacturing acceptance."}


def _vector(values) -> tuple[float, float, float]:
    return tuple(float(v) for v in values)


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a):
    length = math.sqrt(_dot(a, a))
    if length <= 1e-12:
        raise ValueError("A direction vector must not be zero.")
    return tuple(x / length for x in a)


def expected_matrix(projection: Projection) -> list[list[float]]:
    """The matrix rows that the view direction, the up direction, and the scale convention define."""
    view = _unit(_vector(projection.view_direction))
    up = _vector(projection.up)
    along = _dot(up, view)
    screen_up = tuple(u - along * v for u, v in zip(up, view))
    if math.sqrt(_dot(screen_up, screen_up)) <= 1e-9:
        raise ValueError("The up direction must not be parallel to the view direction.")
    screen_up = _unit(screen_up)
    screen_right = _cross(screen_up, view)  # Right-handed: right x up = toward the viewer.
    factor = ISOMETRIC_FACTORS.get(projection.scale_convention, 1.0)
    return [[factor * x for x in screen_right], [factor * x for x in screen_up]]


def projection_defects(kind: str, projection: Projection) -> list[str]:
    """Messages for a projection that disagrees with its declaration or with the view kind."""
    try:
        expected = expected_matrix(projection)
    except ValueError as error:
        return [str(error)]
    defects = []
    matrix = [list(map(float, row)) for row in projection.matrix]
    if any(abs(matrix[r][c] - expected[r][c]) > PROJECTION_TOLERANCE for r in range(2) for c in range(3)):
        defects.append("The matrix does not agree with view_direction, up, handedness, and scale_convention.")
    view = _unit(_vector(projection.view_direction))
    if kind == "isometric":
        if projection.scale_convention not in ISOMETRIC_FACTORS:
            defects.append("An isometric view needs the scale convention isometric_drawing or isometric_projection.")
        # Isometry: the view direction is a body diagonal, so each projected axis has the same length,
        # and the projected axes are 120 degrees apart.
        if max(abs(abs(c) - 1 / math.sqrt(3)) for c in view) > PROJECTION_TOLERANCE:
            defects.append("The view direction is not a body diagonal: the projection is dimetric or trimetric, not isometric.")
        # Use each axis in the direction that points toward the viewer. Otherwise a negative view component gives 60 degrees.
        signs = [1.0 if c >= 0 else -1.0 for c in view]
        axes = [(signs[i] * matrix[0][i], signs[i] * matrix[1][i]) for i in range(3)]
        lengths = [math.hypot(*axis) for axis in axes]
        if max(lengths) - min(lengths) > PROJECTION_TOLERANCE:
            defects.append("The projected model axes do not have equal lengths.")
        for i in range(3):
            for j in range(i + 1, 3):
                a, b = axes[i], axes[j]
                cosine = (a[0] * b[0] + a[1] * b[1]) / max(lengths[i] * lengths[j], 1e-12)
                if abs(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))) - 120) > 1e-4:
                    defects.append("The projected model axes are not 120 degrees apart.")
                    return defects
    else:
        if projection.scale_convention != "true_size":
            defects.append("An orthographic or section view needs the scale convention true_size.")
        components = sorted(abs(c) for c in view)
        if kind != "section" and components[1] > PROJECTION_TOLERANCE:
            defects.append("An orthographic view direction must be a model axis.")
    return defects


def ellipse_bounds(item: dict[str, Any]) -> list[float]:
    """Bounds of the complete ellipse. They also contain each arc of it."""
    a = math.hypot(*item["major_axis"])
    b = a * item["ratio"]
    angle = math.atan2(item["major_axis"][1], item["major_axis"][0])
    half_width = math.sqrt((a * math.cos(angle)) ** 2 + (b * math.sin(angle)) ** 2)
    half_height = math.sqrt((a * math.sin(angle)) ** 2 + (b * math.cos(angle)) ** 2)
    cx, cy = item["center"]
    return [cx - half_width, cy - half_height, cx + half_width, cy + half_height]


def frame_review(frame: ToleranceFrame) -> tuple[list[str], list[str]]:
    """Defects (invalid frame) and review reasons (outside the supported profile) of one tolerance frame."""
    defects, review = [], []
    characteristic = frame.characteristic
    letters = [reference.letter for reference in frame.datums]
    if characteristic in FORM and frame.datums:
        defects.append(f"A {characteristic} tolerance must not have datum references. Remove them.")
    if characteristic in ORIENTATION | RUNOUT and not frame.datums:
        defects.append(f"A {characteristic} tolerance needs at least one datum reference.")
    if len(letters) != len(set(letters)):
        defects.append("Datum references must be distinct: a datum letter occurs more than once.")
    if len(frame.modifiers) != len(set(frame.modifiers)):
        defects.append("A modifier occurs more than once.")
    if {"M", "L"} <= set(frame.modifiers):
        defects.append("The modifiers M and L exclude each other.")
    if frame.zone != "width" and characteristic in NO_DIAMETER_ZONE:
        defects.append(f"A {characteristic} tolerance cannot have a diameter or spherical zone. Use zone width.")
    if characteristic not in SUPPORTED_CHARACTERISTICS:
        review.append(f"The characteristic {characteristic} is outside the supported profile.")
    unsupported = sorted(set(frame.modifiers) - SUPPORTED_MODIFIERS)
    if unsupported:
        review.append("Modifiers outside the supported profile: " + ", ".join(unsupported) + ".")
    if any(reference.modifiers for reference in frame.datums):
        review.append("Datum modifiers are outside the supported profile.")
    if characteristic == "position" and not frame.datums:
        review.append("A position tolerance without datum references needs review.")
    if frame.zone == "spherical_diameter":
        review.append("A spherical tolerance zone is outside the supported profile.")
    return defects, review
