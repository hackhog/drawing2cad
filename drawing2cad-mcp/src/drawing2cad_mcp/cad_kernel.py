"""Bounded build123d feature construction. Invoke only in a restricted worker."""

from __future__ import annotations

from importlib.metadata import version
import math
from pathlib import Path
from typing import Any

from .part_schema import PartDescription, parse_description, resolve
from .cad_validation import axis_vector, measure_shape, step_metadata


class CadBuildError(ValueError):
    """A failed operation with an actionable feature identifier."""

    def __init__(self, code: str, message: str, feature_id: str | None = None, *, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.feature_id = code, message, feature_id
        self.details = details

    def as_dict(self):
        result = {"code": self.code, "message": self.message, "feature_id": self.feature_id}
        if self.details is not None:
            result["details"] = self.details
        return result


def _positive(value, part):
    value = resolve(value, part)
    if value <= 0:
        raise CadBuildError("INVALID_DIMENSION", "A feature dimension must be greater than zero.")
    return value


def _plane(origin, axis, part):
    from build123d import Plane

    direction = axis_vector(axis)
    x_direction = (0, 1, 0) if axis[-1] == "X" else (1, 0, 0)
    return Plane(origin=tuple(resolve(value, part) for value in origin), x_dir=x_direction, z_dir=direction)


def _primitive(feature, part, *, cutting=False):
    from build123d import Edge, Face, Solid, Wire

    profile = feature.profile if cutting else feature
    kind = profile.shape if cutting else feature.type
    plane = _plane(feature.origin, getattr(feature, "axis", "Z"), part)
    depth = _positive(profile.depth if cutting else feature.height, part)
    taper = resolve(getattr(feature, "taper_angle", 0.0), part)
    if kind == "box":
        length, width = _positive(profile.length, part), _positive(profile.width, part)
        if not taper:
            return Solid.make_box(length, width, depth, plane)
        wire = Wire.make_polygon([(0, 0, 0), (length, 0, 0), (length, width, 0), (0, width, 0)], close=True)
    if kind == "cylinder":
        radius = _positive(profile.diameter, part) / 2
        if not taper:
            return Solid.make_cylinder(radius, depth, plane)
        end_radius = radius - depth * math.tan(math.radians(taper))
        if end_radius <= 0:
            raise CadBuildError("INVALID_TAPER", "The tapered cut must retain a positive end radius.")
        return Solid.make_cone(radius, end_radius, depth, plane)
    if kind in {"profile_extrusion", "profile"}:
        edges = []
        for segment in profile.segments:
            start = (*[resolve(value, part) for value in segment.start], 0)
            end = (*[resolve(value, part) for value in segment.end], 0)
            if segment.kind == "line":
                edges.append(Edge.make_line(start, end))
            else:
                middle = (*[resolve(value, part) for value in segment.mid], 0)
                edges.append(Edge.make_three_point_arc(start, middle, end))
        wire = Wire(edges)
    elif kind != "box":
        points = [(resolve(x, part), resolve(y, part), 0) for x, y in profile.points]
        wire = Wire.make_polygon(points, close=True)
    if not wire.is_closed or not wire.is_valid:
        raise CadBuildError("INVALID_PROFILE", "The profile must be one closed, valid wire.")
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt

    # Set the underlying plane, not only the face orientation. The tapered
    # prism uses the plane normal even when a clockwise face is reversed.
    face = Face(BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), wire.wrapped, True).Face())
    if not face.is_valid or face.area <= 1e-9:
        raise CadBuildError("INVALID_PROFILE", "The profile must be simple and have positive area.")
    # Normalize winding so the same signed taper has the same meaning for all
    # input contours. Positive taper reduces the profile along the extrusion.
    if face.normal_at().Z < 0:
        face = -face
    solid = Solid.extrude_taper(face, (0, 0, depth), taper) if taper else Solid.extrude(face, (0, 0, depth))
    return plane.location * solid


def _hole(shape, feature, part):
    from build123d import Solid

    plane = _plane(feature.position, feature.axis, part)
    diameter = _positive(feature.diameter, part)
    axis = axis_vector(feature.axis)
    entry = tuple(resolve(value, part) for value in feature.position)
    if (shape.is_inside(tuple(entry[i] - axis[i] * 0.0001 for i in range(3)))
            or not shape.is_inside(tuple(entry[i] + axis[i] * 0.0001 for i in range(3)))):
        raise CadBuildError("HOLE_ENTRY", "The hole position must be on an entry surface with material immediately along its axis.")
    if feature.extent == "through":
        bounds = shape.bounding_box()
        index = {"X": 0, "Y": 1, "Z": 2}[feature.axis[-1]]
        endpoint = list(bounds.min if axis[index] < 0 else bounds.max)[index]
        start = resolve(feature.position[index], part)
        depth = (endpoint - start) * axis[index]
        if depth <= 0:
            raise CadBuildError("HOLE_DIRECTION", "The hole entry and direction do not intersect the solid.")
        # The extra tolerance avoids coincident end faces in the Boolean cut.
        depth += 0.00001
    else:
        depth = _positive(feature.depth, part)
        tip_depth = 0.0
        if feature.drill_angle is not None:
            tip_depth = diameter / (2 * math.tan(math.radians(resolve(feature.drill_angle, part) / 2)))
        if not shape.is_inside(tuple(entry[i] + axis[i] * (depth + tip_depth + 0.0001) for i in range(3))):
            raise CadBuildError("BLIND_HOLE_BREAKTHROUGH", "The blind-hole depth must leave material below its bottom.")
    tool = Solid.make_cylinder(diameter / 2, depth, plane)
    if feature.extent == "blind" and feature.drill_angle is not None:
        tip_origin = tuple(entry[i] + axis[i] * depth for i in range(3))
        tool = tool.fuse(Solid.make_cone(diameter / 2, 0, tip_depth, _plane(tip_origin, feature.axis, part)))
    if feature.style != "plain":
        counter_diameter = _positive(feature.counter_diameter, part)
        if counter_diameter <= diameter:
            raise CadBuildError("INVALID_HOLE", "The counter diameter must exceed the hole diameter.")
        if feature.style == "counterbore":
            counter_depth = _positive(feature.counter_depth, part)
            if counter_depth >= depth:
                raise CadBuildError("INVALID_HOLE", "The counterbore must be shorter than the hole.")
            tool = tool.fuse(Solid.make_cylinder(counter_diameter / 2, counter_depth, plane))
        else:
            angle = _positive(feature.angle, part)
            if not 0 < angle < 180:
                raise CadBuildError("INVALID_HOLE", "The included countersink angle must be between 0 and 180 degrees.")
            counter_depth = (counter_diameter - diameter) / (2 * math.tan(math.radians(angle / 2)))
            if counter_depth >= depth:
                raise CadBuildError("INVALID_HOLE", "The countersink must be shorter than the hole.")
            tool = tool.fuse(Solid.make_cone(counter_diameter / 2, diameter / 2, counter_depth, plane))
    return shape.cut(tool)


def _adjacent_to_plane(shape, edge, plane, tolerance):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane

    normal = tuple(value / math.hypot(*plane.normal) for value in plane.normal)
    for face in shape.faces():
        if not any(edge.is_same(candidate) for candidate in face.edges()):
            continue
        surface = BRepAdaptor_Surface(face.wrapped)
        if surface.GetType() != GeomAbs_Plane:
            continue
        actual = surface.Plane()
        direction, location = actual.Axis().Direction(), actual.Location()
        if abs(sum(a * b for a, b in zip(normal, (direction.X(), direction.Y(), direction.Z())))) < 1 - 1e-9:
            continue
        offset = sum(n * (p - q) for n, p, q in zip(normal, (location.X(), location.Y(), location.Z()), plane.origin))
        if abs(offset) <= tolerance:
            return True
    return False


def _edge_selection_details(selected, expected_count):
    """Bound the geometric evidence needed to correct an edge selector."""
    summaries = []
    for edge in selected[:64]:
        geometry = edge.geom_type.name.lower()
        bounds = edge.bounding_box(optimal=False)
        center = edge.arc_center if geometry == "circle" else edge.center()
        summaries.append({"geometry": geometry, "center": list(center),
                          "bbox_min": list(bounds.min), "bbox_max": list(bounds.max),
                          "length_mm": float(edge.length)})
    return {"expected_count": expected_count, "selected_count": len(selected),
            "selected_edges": summaries, "truncated": len(selected) > len(summaries)}


def _dress(shape, feature, part):
    selector = feature.selector
    selected = []
    for edge in shape.edges():
        geometry = edge.geom_type.name.lower()
        center = tuple(edge.arc_center if geometry == "circle" else edge.center())
        if selector.geometry != "any" and selector.geometry != geometry:
            continue
        if selector.radius is not None and (geometry != "circle" or abs(edge.radius - selector.radius) > selector.tolerance):
            continue
        if not all(lo - selector.tolerance <= value <= hi + selector.tolerance for lo, value, hi in zip(selector.center_min, center, selector.center_max)):
            continue
        if selector.adjacent_plane is not None and not _adjacent_to_plane(shape, edge, selector.adjacent_plane, selector.tolerance):
            continue
        selected.append(edge)
    if len(selected) != selector.expected_count:
        raise CadBuildError("EDGE_SELECTION", f"Expected {selector.expected_count} edges; the geometric selector found {len(selected)}. Narrow the region or correct expected_count.",
                            details=_edge_selection_details(selected, selector.expected_count))
    size = _positive(feature.size, part)
    return shape.fillet(size, selected) if feature.type == "fillet" else shape.chamfer(size, None, selected)


def export_shape(shape, description: dict[str, Any], output_dir: str | Path, *, export_profile: str = "ap214", pmi: dict | None = None) -> dict[str, Any]:
    """Write a candidate only. A separate import worker must approve release."""
    from build123d import Shape, Unit, export_step
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_Controller

    if export_profile not in {"ap214", "ap242"}:
        raise CadBuildError("UNSUPPORTED_EXPORT_PROFILE", "Use ap214 or ap242.")
    if pmi is not None and export_profile != "ap242":
        raise CadBuildError("UNSUPPORTED_PMI_PROFILE", "Semantic PMI requires the AP242 profile.")
    part = parse_description(description)
    if not isinstance(shape, Shape):
        raise CadBuildError("INVALID_RESULT", "The worker result must be a build123d Shape.")
    measured = measure_shape(shape, part)
    if measured["status"] != "pass":
        return {**measured, "candidate_step": None}
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / "candidate.step"
    if candidate.exists():
        raise CadBuildError("OUTPUT_EXISTS", "The candidate path already exists; use a fresh job directory.")
    shape.label = part.name
    if export_profile == "ap242":
        from .adapters.ap242 import export_ap242_candidate
        return export_ap242_candidate(shape, description, directory, pmi=pmi)
    STEPControl_Controller.Init_s()
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    export_step(shape, candidate, unit=Unit.MM)
    metadata = step_metadata(candidate, part.name)
    checks = [*measured["checks"], *metadata["checks"], {"check": "fresh_worker_reimport", "status": "not_tested", "reason": "The service must import this candidate in a separate restricted worker."}]
    return {"status": "fail" if any(item["status"] == "fail" for item in checks) else "pass", "candidate_step": str(candidate), "checks": checks, "measured": measured["measured"], "step": {key: value for key, value in metadata.items() if key != "checks"}, "versions": {"build123d": version("build123d"), "ocp": version("cadquery-ocp-novtk")}}


def build_shape(description: dict[str, Any]):
    """Replay the ordered feature list and measure each resulting solid."""
    part = parse_description(description)
    shape = None
    feature_results = []
    for feature in part.features:
        before = float(shape.volume) if shape is not None else 0
        try:
            if feature.type in {"box", "cylinder", "extrusion", "profile_extrusion"}:
                addition = _primitive(feature, part)
                shape = addition if shape is None else shape.fuse(addition)
            elif feature.type == "hole":
                shape = _hole(shape, feature, part)
            elif feature.type in {"pocket", "cut"}:
                shape = shape.cut(_primitive(feature, part, cutting=True))
            else:
                shape = _dress(shape, feature, part)
            if not shape.is_valid or len(shape.solids()) != 1 or shape.volume <= 0:
                raise CadBuildError("INVALID_SOLID", "The feature must leave one valid solid with positive volume.")
            after = float(shape.volume)
            if feature.type in {"hole", "pocket", "cut"} and after >= before - 1e-8:
                raise CadBuildError("NO_MATERIAL_REMOVED", "The operation did not remove material. Check its position and extent.")
            if feature.type in {"chamfer", "fillet"} and abs(after - before) <= 1e-8:
                raise CadBuildError("NO_MATERIAL_CHANGED", "The edge operation did not change material.")
            if getattr(feature, "operation", None) == "add" and after <= before + 1e-8:
                raise CadBuildError("NO_MATERIAL_ADDED", "The additive feature did not add material.")
            feature_results.append({"feature_id": feature.id, "type": feature.type, "status": "pass", "volume_before_mm3": before, "volume_after_mm3": after})
        except CadBuildError as error:
            error.feature_id = feature.id
            error.checks = [*({"check": "feature_execution", "feature_id": item["feature_id"], "status": "pass"}
                               for item in feature_results),
                            {"check": "feature_execution", "feature_id": feature.id, "status": "fail"}]
            raise
        except Exception as error:
            failure = CadBuildError("KERNEL_OPERATION", str(error)[:1000], feature.id)
            failure.checks = [*({"check": "feature_execution", "feature_id": item["feature_id"], "status": "pass"}
                                for item in feature_results),
                              {"check": "feature_execution", "feature_id": feature.id, "status": "fail"}]
            raise failure from error
    return shape, feature_results


def build(description: dict[str, Any], output_dir: str | Path, *, export_profile: str = "ap214", pmi: dict | None = None) -> dict[str, Any]:
    """Build a candidate with the selected exchange adapter."""
    shape, feature_results = build_shape(description)
    part = parse_description(description)
    result = export_shape(shape, description, output_dir, export_profile=export_profile, pmi=pmi)
    result["feature_results"] = feature_results
    result["coverage"] = {"constructed_features": len(feature_results), "declared_features": len(part.features), "status": "pass", "source_feature_coverage": "not_tested", "reason": "Execution coverage is not proof that all source features were declared."}
    return result
