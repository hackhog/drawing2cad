"""Requests and service rules for views derived from the validated model.

The restricted worker derives the geometry (see view_derivation.py). This module checks the requests before the worker starts,
and it puts a stored derivation into a DrawingSpec 2.0 view. It does not import CAD libraries.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError

from .drawing_contract_v2 import Derivation, Projection, expected_matrix, projection_defects
from .part_schema import ClosedModel, Identifier, Number

Vector3 = tuple[Number, Number, Number]
MAX_VIEWS = 8
# DrawingSpec 2.0 permits 300 primitives in a view.
MAX_PRIMITIVES_PER_VIEW = 300
# The tool result keeps the geometry of each view while the result stays below this size. The artifact has all of it.
MAX_RESULT_GEOMETRY_CHARS = 60000
# Derived primitives that one drawing can contain after expansion. DrawingSpec 2.0 has at most 12 views.
MAX_EXPANDED_PRIMITIVES = 3600


class SectionRequest(ClosedModel):
    letter: Annotated[str, Field(pattern=r"^[A-Z]$")]
    origin: Vector3 = Field(description="A model point on the cutting plane, in mm.")
    normal: Vector3 = Field(description=(
        "Normal of the cutting plane. view_direction points from the part toward the viewer: "
        "+normal for positive_normal, -normal for negative_normal."))
    viewing_side: Literal["positive_normal", "negative_normal"] = Field(
        description="positive_normal: the viewer is on the positive side of the normal. The material between the viewer and the plane is removed.")
    source_view_id: Identifier = Field(description="Another requested view that shows the cutting line. It must show the plane as a line.")


class ViewRequest(ClosedModel):
    id: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,47}$")]
    kind: Literal["orthographic", "isometric", "section"]
    projection_type: Literal["parallel", "perspective"] = Field(
        default="parallel", description="Only parallel projection is supported. perspective is rejected with a reason.")
    view_direction: Vector3 | None = Field(
        default=None, description="Model direction from the part toward the viewer. Not for a section: the cutting plane gives it.")
    up: Vector3 = Field(description="Model direction that points up in the view.")
    scale_convention: Literal["true_size", "isometric_drawing", "isometric_projection"] | None = Field(
        default=None, description="Default: true_size, or isometric_drawing for an isometric view.")
    hidden_lines: bool | None = Field(default=None, description="Default: true for an orthographic view, false otherwise.")
    cutting_plane: SectionRequest | None = None


class Request(ClosedModel):
    views: Annotated[list[ViewRequest], Field(min_length=1, max_length=MAX_VIEWS)]


def _unit(vector) -> list[float]:
    values = [float(c) for c in vector]
    length = math.sqrt(sum(c * c for c in values))
    if length <= 1e-12:
        raise ValueError("A direction must not be zero.")
    return [c / length for c in values]


def normalize_requests(views: list[dict]) -> list[dict[str, Any]]:
    """Check the view requests and add the projection of each view. Raise ValueError with an actionable message."""
    try:
        request = Request.model_validate({"views": views})
    except ValidationError as error:
        fields = ["/".join(str(item) for item in detail["loc"]) + ": " + detail["type"]
                  for detail in error.errors(include_url=False, include_context=False, include_input=False)[:10]]
        raise ValueError("The view requests do not match their schema: " + "; ".join(fields) + ".") from None
    identifiers = [view.id for view in request.views]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("View ids must be unique.")
    normalized = {}
    for view in request.views:
        if view.projection_type == "perspective":
            raise ValueError(f"View {view.id}: a perspective projection is not a parallel projection. "
                             "Orthographic, isometric, and section views need a parallel projection.")
        if view.kind == "section":
            if view.cutting_plane is None or view.view_direction is not None:
                raise ValueError(f"View {view.id}: a section needs cutting_plane and no view_direction. The normal gives the direction.")
            sign = 1.0 if view.cutting_plane.viewing_side == "positive_normal" else -1.0
            direction = [sign * c for c in _unit(view.cutting_plane.normal)]
        else:
            if view.cutting_plane is not None or view.view_direction is None:
                raise ValueError(f"View {view.id}: only a section has cutting_plane. Other views need view_direction.")
            direction = _unit(view.view_direction)
        convention = view.scale_convention or ("isometric_drawing" if view.kind == "isometric" else "true_size")
        draft = Projection(view_direction=tuple(direction), up=view.up, scale_convention=convention,
                           matrix=((1, 0, 0), (0, 1, 0)))
        try:
            matrix = expected_matrix(draft)
        except ValueError as error:
            raise ValueError(f"View {view.id}: {error}") from None
        projection = Projection(view_direction=tuple(direction), up=view.up, scale_convention=convention,
                                matrix=(tuple(matrix[0]), tuple(matrix[1])))
        defects = projection_defects("section" if view.kind == "section" else view.kind, projection)
        if defects:
            raise ValueError(f"View {view.id}: " + " ".join(defects))
        normalized[view.id] = {"id": view.id, "kind": view.kind, "projection": projection.model_dump(mode="json"),
                               "hidden_lines": view.hidden_lines if view.hidden_lines is not None else view.kind == "orthographic",
                               "cutting_plane": view.cutting_plane.model_dump(mode="json") if view.cutting_plane else None}
    for view in normalized.values():
        plane = view["cutting_plane"]
        if plane is None:
            continue
        source = normalized.get(plane["source_view_id"])
        if source is None or source["kind"] == "section":
            raise ValueError(f"View {view['id']}: source_view_id must name another requested view that is not a section.")
        normal = _unit(plane["normal"])
        if abs(sum(a * b for a, b in zip(normal, source["projection"]["view_direction"]))) > 1e-6:
            raise ValueError(f"View {view['id']}: the source view must show the cutting plane as a line. "
                             "The normal must be perpendicular to the view direction of the source view.")
        view["source_projection"] = source["projection"]
    return list(normalized.values())


def binding(state: dict) -> dict[str, Any] | None:
    """The binding of the current validated build, or None without a current validated build."""
    built = state.get("build") or {}
    if (built.get("status") != "pass" or built.get("description_revision") != state["revision"]
            or built.get("description_sha256") != state["description_sha256"]):
        return None
    return {"part_revision": state["revision"], "description_sha256": state["description_sha256"],
            "candidate_sha256": built["candidate_sha256"]}


def status(record: dict | None, state: dict) -> dict[str, Any] | None:
    """Public status of the stored derivation: current or stale."""
    if record is None:
        return None
    current = binding(state)
    return {"derivation_sha256": record["derivation_sha256"], "binding": record["binding"],
            "view_ids": [view["id"] for view in record["views"]],
            "status": "current" if current == record["binding"] else "stale"}


def _failure(spec: dict, view_id: str, code: str, message: str) -> dict[str, Any]:
    declared = spec.get("schema_version")
    known = isinstance(declared, str) and declared in {"1.0", "2.0"}
    return {"status": "fail", "diagnostic_eligible": False, "schema_version": declared if known else None,
            "findings": [], "render_support": None, "defects": [{"code": code, "id": view_id, "message": message}]}


def expand(spec: Any, record: dict | None, state: dict) -> tuple[Any, dict | None]:
    """Put the derived geometry into each view that refers to a derivation.

    Return the expanded drawing and None, or the unchanged drawing and a failure report.
    """
    if not isinstance(spec, dict) or not isinstance(spec.get("views"), list):
        return spec, None
    references = [view for view in spec["views"] if isinstance(view, dict) and isinstance(view.get("derivation"), dict)]
    if not references:
        return spec, None
    if spec.get("schema_version") != "2.0":
        return spec, _failure(spec, "drawing", "schema_version", "A view with derivation needs schema_version 2.0.")
    views = {view["id"]: view for view in record["views"]} if record else {}
    # Check each reference and the expanded size before any geometry is copied.
    names: dict[str, str] = {}
    total = 0
    for view in references:
        identifier = str(view.get("id"))[:64]
        try:
            reference = Derivation.model_validate(view["derivation"])
        except ValidationError:
            return spec, _failure(spec, identifier, "derivation_invalid",
                                  "derivation needs derivation_sha256, view_id, feature_ids, and evidence_ids of the schema.")
        if reference.view_id in names:
            return spec, _failure(spec, identifier, "derivation_invalid", "Each derived view can occur only once in a drawing.")
        names[reference.view_id] = identifier
        if "geometry" in view and not isinstance(view["geometry"], list):
            return spec, _failure(spec, identifier, "derivation_invalid", "geometry of a derived view must be a list of your own primitives.")
        total += len(views.get(reference.view_id, {}).get("geometry", []))
    if total > MAX_EXPANDED_PRIMITIVES:
        return spec, _failure(spec, "drawing", "derivation_invalid",
                              f"The derived views of this drawing exceed {MAX_EXPANDED_PRIMITIVES} primitives.")
    expanded = deepcopy(spec)
    for view in expanded["views"]:
        reference = view.get("derivation") if isinstance(view, dict) else None
        if not isinstance(reference, dict):
            continue
        identifier = str(view.get("id"))
        if record is None or reference.get("derivation_sha256") != record["derivation_sha256"]:
            return spec, _failure(spec, identifier, "derivation_stale",
                                  "The view refers to a derivation that is not the stored one. Derive the views again and use the new derivation_sha256.")
        if binding(state) != record["binding"]:
            return spec, _failure(spec, identifier, "derivation_stale",
                                  "The derivation belongs to another part revision or build. Build the part, then derive the views again.")
        draft = views.get(reference.get("view_id"))
        if draft is None:
            return spec, _failure(spec, identifier, "derivation_unknown", "The derivation has no view with this view_id.")
        if view.get("kind") != draft["kind"]:
            return spec, _failure(spec, identifier, "derivation_mismatch", f"The view kind must be {draft['kind']}, as derived.")
        for name in ("projection", "cutting_plane", "hatching"):
            if view.get(name):
                return spec, _failure(spec, identifier, "derivation_mismatch",
                                      f"Do not supply {name} for a derived view. The derivation supplies it.")
        evidence = reference.get("evidence_ids")
        features = reference.get("feature_ids")
        own = view.get("geometry") if isinstance(view.get("geometry"), list) else []
        view["geometry"] = [{**primitive, "evidence_ids": evidence, "feature_ids": features} for primitive in draft["geometry"]] + own
        view["projection"] = draft["projection"]
        if draft.get("hatching"):
            view["hatching"] = draft["hatching"]
        if draft.get("cutting_plane"):
            source = names.get(draft["cutting_plane"]["source_view_id"])
            if source is None:
                return spec, _failure(spec, identifier, "derivation_source_missing",
                                      "The source view of this section must also be a derived view of this drawing.")
            # The drawing can give the derived source view another id.
            view["cutting_plane"] = {**draft["cutting_plane"], "source_view_id": source, "evidence_ids": evidence}
    return expanded, None


def public_views(views: list[dict]) -> tuple[list[dict], bool]:
    """Views for the tool result. Omit geometry when the result would exceed its size limit."""
    import json

    result, size, omitted = [], 0, False
    for view in views:
        size += len(json.dumps(view["geometry"], separators=(",", ":")))
        if size > MAX_RESULT_GEOMETRY_CHARS:
            result.append({**{key: value for key, value in view.items() if key != "geometry"}, "geometry_omitted": True})
            omitted = True
        else:
            result.append(view)
    return result, omitted
