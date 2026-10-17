"""Measure imported kernel geometry without replaying the feature construction."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
from typing import Any

from .adapters.p21 import P21Typed, sth_p21_parse, sth_p21_validate_refs
from .part_schema import PartDescription, parse_description


def axis_vector(axis: str) -> tuple[float, float, float]:
    index = {"X": 0, "Y": 1, "Z": 2}[axis[-1]]
    result = [0.0, 0.0, 0.0]
    result[index] = -1.0 if axis.startswith("-") else 1.0
    return tuple(result)


def check(name: str, passed: bool, **data) -> dict[str, Any]:
    return {"check": name, "status": "pass" if passed else "fail", **data}


def step_metadata(path: Path, name: str) -> dict[str, Any]:
    """Check bounded Part 21 data. This is not EXPRESS conformance testing."""
    with path.open("rb") as stream:
        raw = stream.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("The STEP file exceeds the 32 MiB inspection limit.")
    text = raw.decode("utf-8-sig")
    records = sth_p21_parse(text, exchange=True)
    refs = sth_p21_validate_refs(records)
    schemas = re.findall(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", text[:16384], re.I)
    products, length_units = [], []
    for entity_type, arguments in records.values():
        if entity_type == "PRODUCT" and len(arguments) >= 2:
            products.append(arguments[1])
        components = arguments if entity_type == "__COMPLEX__" else [P21Typed(entity_type, arguments)]
        names = {component.name for component in components if isinstance(component, P21Typed)}
        if "LENGTH_UNIT" in names:
            si = next((component.args for component in components if isinstance(component, P21Typed) and component.name == "SI_UNIT"), None)
            length_units.append(si)
    millimetres = bool(length_units) and all(unit == ["MILLI", "METRE"] for unit in length_units)
    named = name in products or any(isinstance(value, str) and re.fullmatch(re.escape(name) + r"-\d+", value) for value in products)
    checks = [
        check("step_references", refs),
        check("step_product_name", named, expected=name, actual=products),
        check("step_units_mm", millimetres, actual=length_units),
        check("step_schema_present", bool(schemas), actual=schemas),
        {"check": "independent_step_conformance", "status": "not_tested", "reason": "Geometry import does not run independent schema checks. Read the separate independent analysis report."},
        {"check": "target_cad_open", "status": "not_tested", "reason": "No target CAD opening test was run."},
        {"check": "semantic_pmi", "status": "not_tested", "reason": "Geometry import does not test PMI semantics or associations. Read the separate PMI report."},
        {"check": "step_editable_construction", "status": "not_tested", "reason": "Geometry import does not reconstruct features. Read the separate construction adapter report."},
    ]
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "schemas": schemas, "products": products, "length_units": length_units, "checks": checks}


def _cylinders(shape) -> list[dict[str, Any]]:
    """Measure full cylindrical faces and distinguish concave from convex faces."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder

    cylinders = []
    for face_index, face in enumerate(shape.faces()):
        surface = BRepAdaptor_Surface(face.wrapped)
        if surface.GetType() != GeomAbs_Cylinder:
            continue
        if surface.LastUParameter() - surface.FirstUParameter() < 2 * math.pi - 1e-5:
            continue
        cylinder = surface.Cylinder()
        origin = cylinder.Location()
        axis = cylinder.Axis().Direction()
        direction = (axis.X(), axis.Y(), axis.Z())
        location = (origin.X(), origin.Y(), origin.Z())
        point = surface.Value((surface.FirstUParameter() + surface.LastUParameter()) / 2, (surface.FirstVParameter() + surface.LastVParameter()) / 2)
        point_tuple = (point.X(), point.Y(), point.Z())
        delta = [point_tuple[i] - location[i] for i in range(3)]
        along = sum(delta[i] * direction[i] for i in range(3))
        radial = [delta[i] - along * direction[i] for i in range(3)]
        normal = tuple(face.normal_at(point_tuple))
        concave = sum(radial[i] * normal[i] for i in range(3)) < 0
        cylinders.append({"diameter": float(2 * cylinder.Radius()), "axis_origin": location,
                          "axis_direction": direction, "axial_length": float(surface.LastVParameter() - surface.FirstVParameter()),
                          "concave": concave, "face_index": face_index})
    return cylinders


def _holes(shape) -> list[dict[str, Any]]:
    """Retain the public helper for full concave cylindrical faces."""
    return [item for item in _cylinders(shape) if item["concave"]]


def _circular_edges(shape) -> list[dict[str, Any]]:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Circle

    result = []
    for edge in shape.edges():
        curve = BRepAdaptor_Curve(edge.wrapped)
        if curve.GetType() != GeomAbs_Circle:
            continue
        circle = curve.Circle()
        origin, direction = circle.Location(), circle.Axis().Direction()
        result.append({"radius": float(circle.Radius()), "center": (origin.X(), origin.Y(), origin.Z()),
                       "axis_direction": (direction.X(), direction.Y(), direction.Z()),
                       "sweep_degrees": math.degrees(curve.LastParameter() - curve.FirstParameter())})
    return result


def _cones(shape) -> list[dict[str, Any]]:
    """Measure complete conical faces for drill tips and circular chamfers."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cone

    result = []
    for face_index, face in enumerate(shape.faces()):
        surface = BRepAdaptor_Surface(face.wrapped)
        if surface.GetType() != GeomAbs_Cone or surface.LastUParameter() - surface.FirstUParameter() < 2 * math.pi - 1e-5:
            continue
        cone = surface.Cone()
        origin, direction = cone.Location(), cone.Axis().Direction()
        bounds = face.bounding_box()
        point = surface.Value((surface.FirstUParameter() + surface.LastUParameter()) / 2,
                              (surface.FirstVParameter() + surface.LastVParameter()) / 2)
        point_tuple = (point.X(), point.Y(), point.Z())
        delta = (point.X() - origin.X(), point.Y() - origin.Y(), point.Z() - origin.Z())
        axis = (direction.X(), direction.Y(), direction.Z())
        along = sum(a * b for a, b in zip(delta, axis))
        radial = tuple(value - along * unit for value, unit in zip(delta, axis))
        concave = sum(a * b for a, b in zip(radial, face.normal_at(point_tuple))) < 0
        result.append({"axis_origin": (origin.X(), origin.Y(), origin.Z()),
                       "axis_direction": (direction.X(), direction.Y(), direction.Z()),
                       "angle_degrees": abs(math.degrees(cone.SemiAngle())),
                       "radial_width": abs((surface.LastVParameter() - surface.FirstVParameter()) * math.sin(cone.SemiAngle())),
                       "bbox_min": list(bounds.min), "bbox_max": list(bounds.max),
                       "concave": concave, "face_index": face_index})
    return result


def _matching_cylinders(cylinders, position, direction, tolerance):
    result = []
    for cylinder in cylinders:
        parallel = abs(sum(a * b for a, b in zip(direction, cylinder["axis_direction"])))
        delta = [position[i] - cylinder["axis_origin"][i] for i in range(3)]
        along = sum(delta[i] * direction[i] for i in range(3))
        distance = math.sqrt(sum((delta[i] - along * direction[i]) ** 2 for i in range(3)))
        if parallel >= 1 - 1e-7 and distance <= tolerance:
            result.append(cylinder)
    return result


def _hole_entry_positions(shape, candidates, cylinders, cones, direction, tolerance):
    """Find circular cavity openings through connected supported BREP faces.

    Position remains an axis anchor. Entry validation uses topology, including
    counterbore shoulders and conical transitions, instead of cylinder origins.
    Partial cylinders and other transitions have no supported entry result.
    """
    from build123d import Vector
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane

    faces = list(shape.faces())
    axis_index = next(index for index, value in enumerate(direction) if value)
    rings = _circular_edges(shape)
    positions = []
    for candidate in candidates:
        coaxial = _matching_cylinders(
            [item for item in [*cylinders, *cones] if item["concave"]],
            candidate["axis_origin"], direction, tolerance)
        permitted = {item["face_index"] for item in coaxial}
        planes = {}
        for index, face in enumerate(faces):
            surface = BRepAdaptor_Surface(face.wrapped)
            if surface.GetType() != GeomAbs_Plane:
                continue
            normal = surface.Plane().Axis().Direction()
            if abs(sum(a * b for a, b in zip(direction, (normal.X(), normal.Y(), normal.Z())))) >= 1 - 1e-7:
                permitted.add(index)
                point = surface.Plane().Location()
                planes[index] = (point.X(), point.Y(), point.Z())[axis_index]
        edges = {index: list(faces[index].edges()) for index in permitted}
        connected = {candidate["face_index"]}
        pending = [candidate["face_index"]]
        while pending:
            current = pending.pop()
            for index in permitted - connected:
                if any(first.is_same(second) for first in edges[current] for second in edges[index]):
                    connected.add(index)
                    pending.append(index)
        coordinates = []
        for index in connected:
            if index in planes:
                coordinates.append(planes[index])
                continue
            surface = BRepAdaptor_Surface(faces[index].wrapped)
            u = (surface.FirstUParameter() + surface.LastUParameter()) / 2
            for v in (surface.FirstVParameter(), surface.LastVParameter()):
                point = surface.Value(u, v)
                coordinates.append((point.X(), point.Y(), point.Z())[axis_index])
        coordinate = min(coordinates) if direction[axis_index] > 0 else max(coordinates)
        if not any(index in connected and abs(value - coordinate) <= 1e-7 for index, value in planes.items()):
            continue
        position = list(candidate["axis_origin"])
        position[axis_index] = coordinate
        # A blind bottom cap or drill apex is material at the axis. An open
        # circular entry has a positive distance from the axis to the solid.
        if shape.is_inside(tuple(position)) or shape.distance_to(Vector(position)) <= 1e-7:
            continue
        # The cavity boundary must reach this plane. Do not infer an entry
        # across an unsupported transition such as an unmeasured toroidal lip.
        if not any(math.dist(item["center"], position) <= tolerance
                   and item["sweep_degrees"] >= 360 - 1e-5
                   and abs(sum(a * b for a, b in zip(direction, item["axis_direction"]))) >= 1 - 1e-7
                   for item in rings):
            continue
        positions.append(position)
    return positions


def _plane_locations(shape, position, direction, tolerance):
    """Select actual planar faces at source-derived anchors, not infinite planes."""
    from build123d import Vector
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane

    locations = []
    for face in shape.faces():
        surface = BRepAdaptor_Surface(face.wrapped)
        if surface.GetType() != GeomAbs_Plane:
            continue
        plane = surface.Plane()
        normal = plane.Axis().Direction()
        if abs(sum(a * b for a, b in zip(direction, (normal.X(), normal.Y(), normal.Z())))) < 1 - 1e-7:
            continue
        if face.distance_to(Vector(position)) > tolerance:
            continue
        point = plane.Location()
        locations.append(sum(a * b for a, b in zip(direction, (point.X(), point.Y(), point.Z()))))
    return locations


def _measurement_direction(measurement):
    if measurement.direction is None:
        return axis_vector(measurement.axis)
    length = math.hypot(*measurement.direction)
    return tuple(value / length for value in measurement.direction)


def _section_crossings(shape, anchor, origin, direction, tolerance):
    """Intersect a measurement line with trimmed planar faces near an anchor."""
    from build123d import Vector
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane

    locations = []
    for face in shape.faces():
        surface = BRepAdaptor_Surface(face.wrapped)
        if surface.GetType() != GeomAbs_Plane or face.distance_to(Vector(anchor)) > tolerance:
            continue
        plane = surface.Plane()
        normal = plane.Axis().Direction()
        normal = (normal.X(), normal.Y(), normal.Z())
        denominator = sum(a * b for a, b in zip(normal, direction))
        if abs(denominator) < 1e-9:
            continue
        point = plane.Location()
        delta = [value - origin[i] for i, value in enumerate((point.X(), point.Y(), point.Z()))]
        distance = sum(a * b for a, b in zip(normal, delta)) / denominator
        intersection = Vector(tuple(origin[i] + distance * direction[i] for i in range(3)))
        if face.distance_to(intersection) <= tolerance:
            locations.append(distance)
    return locations


def _surface_radii(shape, position, direction, tolerance):
    """Measure cylindrical surfaces at face anchors, including trimmed fillets."""
    from build123d import Vector
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder

    radii = []
    for face in shape.faces():
        surface = BRepAdaptor_Surface(face.wrapped)
        if surface.GetType() != GeomAbs_Cylinder or face.distance_to(Vector(position)) > tolerance:
            continue
        cylinder = surface.Cylinder()
        axis = cylinder.Axis().Direction()
        if abs(sum(a * b for a, b in zip(direction, (axis.X(), axis.Y(), axis.Z())))) >= 1 - 1e-7:
            radii.append(float(cylinder.Radius()))
    return radii


def _line_angles(shape, position, direction, tolerance):
    from build123d import Vector
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Line

    angles = []
    for edge in shape.edges():
        curve = BRepAdaptor_Curve(edge.wrapped)
        if curve.GetType() != GeomAbs_Line or edge.distance_to(Vector(position)) > tolerance:
            continue
        actual = curve.Line().Direction()
        cosine = abs(sum(a * b for a, b in zip(direction, (actual.X(), actual.Y(), actual.Z()))))
        angles.append(math.degrees(math.acos(min(1.0, cosine))))
    return angles


def _plane_angles(shape, position, direction, tolerance):
    from build123d import Vector
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane

    angles = []
    for face in shape.faces():
        surface = BRepAdaptor_Surface(face.wrapped)
        if surface.GetType() != GeomAbs_Plane or face.distance_to(Vector(position)) > tolerance:
            continue
        normal = surface.Plane().Axis().Direction()
        cosine = abs(sum(a * b for a, b in zip(direction, (normal.X(), normal.Y(), normal.Z()))))
        angles.append(math.degrees(math.acos(min(1.0, cosine))))
    return angles


def _sample_fillet_curvature(face, measurement):
    """Measure a regular fillet section and a small, trimmed neighborhood."""
    from build123d import Vector
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.GeomLProp import GeomLProp_SLProps
    from OCP.gp import gp_Dir, gp_Pnt

    report = {"method": "bounded_principal_curvature", "sample_count": 0,
              "scope": "Five local trimmed-face samples. This does not prove constant radius over the complete face.",
              "maximum_secondary_curvature_ratio": 0.5,
              "section_direction_dot_tolerance": 0.0001}
    if measurement.fillet_section_normal is None:
        return [], "not_tested", {**report, "reason": "A non-analytic fillet requires fillet_section_normal."}
    section = tuple(x / math.hypot(*measurement.fillet_section_normal) for x in measurement.fillet_section_normal)
    surface = BRep_Tool.Surface_s(face.wrapped)
    bounds = BRepAdaptor_Surface(face.wrapped)
    projection = GeomAPI_ProjectPointOnSurf(gp_Pnt(*measurement.position), surface,
        bounds.FirstUParameter(), bounds.LastUParameter(), bounds.FirstVParameter(), bounds.LastVParameter())
    if projection.NbPoints() == 0:
        return [], "not_tested", {**report, "reason": "The surface anchor has no bounded projection."}
    u, v = projection.LowerDistanceParameters()

    def curvature(pu, pv):
        point = surface.Value(pu, pv)
        if face.distance_to(Vector(point.X(), point.Y(), point.Z())) > 1e-7:
            return None
        props = GeomLProp_SLProps(surface, pu, pv, 2, 1e-9)
        if not props.IsCurvatureDefined() or props.IsUmbilic():
            return None
        major, minor = props.MaxCurvature(), props.MinCurvature()
        high, low = gp_Dir(), gp_Dir()
        props.CurvatureDirections(high, low)
        if abs(major) < abs(minor):
            major, minor, high, low = minor, major, low, high
        if not math.isfinite(major) or not math.isfinite(minor) or abs(major) <= 1e-9 or abs(minor) > abs(major) * 0.5:
            return None
        return 1 / abs(major), low, props

    anchor = curvature(u, v)
    if anchor is None:
        return [], "not_tested", {**report, "reason": "The anchor has no separated, regular fillet curvature."}
    radius, tangent, props = anchor
    alignment = abs(sum(a * b for a, b in zip(section, (tangent.X(), tangent.Y(), tangent.Z()))))
    if alignment < 1 - 1e-4:
        return [], "fail", {**report, "reason": "The section normal does not match the local fillet spine direction."}
    distance = min(0.25, radius * 0.1)
    du_length, dv_length = props.D1U().Magnitude(), props.D1V().Magnitude()
    if min(du_length, dv_length) <= 1e-9:
        return [], "not_tested", {**report, "reason": "The local surface parameter directions are singular."}
    du, dv = distance / du_length, distance / dv_length
    values = [radius]
    for pu, pv in ((u - du, v), (u + du, v), (u, v - dv), (u, v + dv)):
        if not (bounds.FirstUParameter() <= pu <= bounds.LastUParameter() and bounds.FirstVParameter() <= pv <= bounds.LastVParameter()):
            return [], "not_tested", {**report, "reason": "The curvature neighborhood exceeds the face parameter bounds."}
        sampled = curvature(pu, pv)
        if sampled is None:
            return [], "not_tested", {**report, "reason": "The curvature neighborhood exceeds the trimmed regular fillet region."}
        values.append(sampled[0])
    spread = max(values) - min(values)
    report.update(sample_count=len(values), radius_spread_mm=spread, approximate_sample_spacing_mm=distance)
    if spread > measurement.tolerance:
        return [], "not_tested", {**report, "reason": "The sampled radius is not constant within the measurement tolerance."}
    return values, "pass", report


def _draft_or_fillet_values(shape, measurement):
    """Measure analytic surfaces at a bounded anchor, not their unbounded extensions."""
    from build123d import Vector
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Torus, GeomAbs_Sphere, GeomAbs_BSplineSurface
    from OCP.BRep import BRep_Tool
    from OCP.GeomLib import GeomLib_IsPlanarSurface
    from OCP.ShapeAnalysis import ShapeAnalysis_CanonicalRecognition
    from OCP.gp import gp_Cylinder

    values, unsupported, sampling = [], False, []
    tolerance = measurement.spatial_tolerance or 0.01
    direction = _measurement_direction(measurement)

    def aligned(axis):
        vector = axis.Direction()
        return abs(sum(a * b for a, b in zip(direction, (vector.X(), vector.Y(), vector.Z())))) >= 1 - 1e-7

    for face in shape.faces():
        if face.distance_to(Vector(measurement.position)) > tolerance:
            continue
        surface = BRepAdaptor_Surface(face.wrapped)
        kind = surface.GetType()
        if measurement.kind == "draft_angle":
            if kind not in {GeomAbs_Plane, GeomAbs_Cone, GeomAbs_Cylinder} and not GeomLib_IsPlanarSurface(BRep_Tool.Surface_s(face.wrapped), 1e-7).IsPlanar():
                unsupported = True
                continue
            normal = tuple(face.normal_at(Vector(measurement.position)))
            sine = abs(sum(a * b for a, b in zip(normal, direction)))
            values.append(math.degrees(math.asin(min(1.0, sine))))
        elif kind == GeomAbs_Cylinder:
            if aligned(surface.Cylinder().Axis()):
                values.append(float(surface.Cylinder().Radius()))
        elif kind == GeomAbs_Torus:
            if aligned(surface.Torus().Axis()):
                values.append(float(surface.Torus().MinorRadius()))
        elif kind == GeomAbs_Sphere:
            values.append(float(surface.Sphere().Radius()))
        elif kind != GeomAbs_Plane:
            cylinder = gp_Cylinder()
            if ShapeAnalysis_CanonicalRecognition(face.wrapped).IsCylinder(1e-7, cylinder):
                if aligned(cylinder.Axis()):
                    values.append(float(cylinder.Radius()))
            elif kind != GeomAbs_BSplineSurface:
                unsupported = True
            else:
                try:
                    sampled, status, report = _sample_fillet_curvature(face, measurement)
                except MemoryError:
                    raise
                except Exception:
                    sampled, status, report = [], "not_tested", {
                        "method": "bounded_principal_curvature", "sample_count": 0,
                        "reason": "The bounded surface projection or curvature calculation failed."}
                values.extend(sampled)
                sampling.append({**report, "status": status})
                unsupported = unsupported or status == "not_tested"
    return values, unsupported, sampling


def measure_shape(shape, part: PartDescription) -> dict[str, Any]:
    """Compare measured geometry with separately supplied drawing measurements."""
    bounds = shape.bounding_box()
    size = list(bounds.size)
    solids = len(shape.solids())
    volume = float(shape.volume)
    checks = [check("solid_validity", bool(shape.is_valid)), check("solid_count", solids == part.expected_solids, expected=part.expected_solids, actual=solids), check("positive_volume", math.isfinite(volume) and volume > 0, actual=volume)]
    cylinders = _cylinders(shape)
    holes = [item for item in cylinders if item["concave"]]
    circular_edges = _circular_edges(shape)
    cones = _cones(shape)
    measurements = []
    for expected in part.measurements:
        unsupported = False
        sampling = []
        if expected.kind == "bbox":
            measured = size
            passed = all(abs(a - b) <= expected.tolerance for a, b in zip(measured, expected.expected))
        elif expected.kind == "volume":
            measured = [volume]
            passed = abs(volume - expected.expected[0]) <= expected.tolerance
        elif expected.kind in {"hole", "outer_diameter"}:
            direction = axis_vector(expected.axis)
            pool = holes if expected.kind == "hole" else [item for item in cylinders if not item["concave"]]
            candidates = _matching_cylinders(pool, expected.position, direction, expected.tolerance)
            measured = [item["diameter"] for item in candidates]
            matching = [item for item in candidates if abs(item["diameter"] - expected.expected[0]) <= expected.tolerance
                        and (expected.axial_length is None or abs(item["axial_length"] - expected.axial_length) <= expected.tolerance)]
            passed = bool(matching)
            entry_positions = []
            if expected.kind == "hole" and expected.entry_position is not None:
                entry_positions = _hole_entry_positions(shape, matching, cylinders, cones, direction, expected.tolerance)
                passed = passed and any(math.dist(position, expected.entry_position) <= expected.tolerance for position in entry_positions)
        elif expected.kind == "arc_radius":
            direction = axis_vector(expected.axis)
            candidates = [item for item in circular_edges if math.dist(item["center"], expected.position) <= expected.tolerance
                          and abs(sum(a * b for a, b in zip(direction, item["axis_direction"]))) >= 1 - 1e-7]
            measured = [item["radius"] for item in candidates]
            passed = any(abs(value - expected.expected[0]) <= expected.tolerance for value in measured)
        elif expected.kind == "axis_distance":
            direction = axis_vector(expected.axis)
            first = _matching_cylinders(holes, expected.position, direction, expected.tolerance)
            second = _matching_cylinders(holes, expected.second_position, direction, expected.tolerance)
            measured = []
            for a in first:
                for b in second:
                    delta = [b["axis_origin"][i] - a["axis_origin"][i] for i in range(3)]
                    along = sum(delta[i] * direction[i] for i in range(3))
                    projected = [delta[i] - along * direction[i] for i in range(3)]
                    value = math.sqrt(sum(v * v for v in projected)) if expected.component == "distance" else abs(projected[{"X": 0, "Y": 1, "Z": 2}[expected.component]])
                    measured.append(value)
            passed = any(abs(value - expected.expected[0]) <= expected.tolerance for value in measured)
        elif expected.kind == "plane_distance":
            direction = _measurement_direction(expected)
            first = _plane_locations(shape, expected.position, direction, expected.tolerance)
            second = _plane_locations(shape, expected.second_position, direction, expected.tolerance)
            measured = [abs(b - a) for a in first for b in second]
            passed = any(abs(value - expected.expected[0]) <= expected.tolerance for value in measured)
        elif expected.kind == "section_distance":
            direction = _measurement_direction(expected)
            first = _section_crossings(shape, expected.position, expected.position, direction, expected.tolerance)
            second = _section_crossings(shape, expected.second_position, expected.position, direction, expected.tolerance)
            measured = [abs(b - a) for a in first for b in second]
            passed = any(abs(value - expected.expected[0]) <= expected.tolerance for value in measured)
        elif expected.kind == "surface_radius":
            measured = _surface_radii(shape, expected.position, _measurement_direction(expected), expected.tolerance)
            passed = any(abs(value - expected.expected[0]) <= expected.tolerance for value in measured)
        elif expected.kind == "line_angle":
            measured = _line_angles(shape, expected.position, _measurement_direction(expected), expected.tolerance)
            passed = any(abs(value - expected.expected[0]) <= expected.tolerance for value in measured)
        elif expected.kind == "plane_angle":
            measured = _plane_angles(shape, expected.position, _measurement_direction(expected), expected.tolerance)
            passed = any(abs(value - expected.expected[0]) <= expected.tolerance for value in measured)
        elif expected.kind in {"draft_angle", "fillet_radius"}:
            measured, unsupported, sampling = _draft_or_fillet_values(shape, expected)
            passed = bool(measured) and all(abs(value - expected.expected[0]) <= expected.tolerance for value in measured) and not any(row["status"] == "fail" for row in sampling)
        elif expected.kind in {"cone_angle", "cone_width"}:
            direction = axis_vector(expected.axis)
            axis_index = {"X": 0, "Y": 1, "Z": 2}[expected.axis[-1]]
            candidates = _matching_cylinders(cones, expected.position, direction, expected.tolerance)
            candidates = [item for item in candidates
                          if item["bbox_min"][axis_index] - expected.tolerance <= expected.position[axis_index]
                          <= item["bbox_max"][axis_index] + expected.tolerance]
            key = "angle_degrees" if expected.kind == "cone_angle" else "radial_width"
            measured = [item[key] for item in candidates]
            passed = any(abs(value - expected.expected[0]) <= expected.tolerance for value in measured)
        measurements.append({"check": expected.id, "kind": expected.kind, "status": "pass" if passed else "fail", "expected": expected.expected, "actual": measured, "tolerance": expected.tolerance, "evidence_ids": expected.evidence_ids, "basis": expected.basis})
        if expected.kind in {"draft_angle", "fillet_radius"}:
            measurements[-1].update(unit="deg" if expected.kind == "draft_angle" else "mm", spatial_tolerance=expected.spatial_tolerance or 0.01)
            if sampling:
                measurements[-1]["surface_sampling"] = sampling
            if unsupported:
                measurements[-1].update(status="not_tested", reason="The surface measurement could not be completed. Inspect the anchor, supported surface type, and any local sampling report; release is blocked.")
        if expected.kind in {"hole", "outer_diameter"}:
            measurements[-1].update(expected_axial_length=expected.axial_length,
                                    actual_axial_lengths=[item["axial_length"] for item in candidates])
        if expected.kind == "hole":
            measurements[-1].update(
                expected_entry_position=expected.entry_position,
                actual_entry_positions=entry_positions,
                entry_side="not_tested" if expected.entry_position is None else ("pass" if passed else "fail"),
                entry_scope="Explicit entry uses the inward axis and connected full cylindrical/conical faces with planar opening rims. A stepped bore has one entry at its outer opening; an internal shoulder is not an entry. Other transitions are unsupported.")
    checks.extend(measurements)
    checks.append({"check": "drawing_measurements", "status": "not_tested" if not measurements else ("pass" if all(item["status"] == "pass" for item in measurements) else "fail"), "reason": "Expected values are supplied drawing evidence; their interpretation requires source review."})
    return {"status": "fail" if any(item["status"] == "fail" for item in checks) else "pass", "checks": checks, "measured": {"bbox_min": list(bounds.min), "bbox_max": list(bounds.max), "bbox_size": size, "volume_mm3": volume, "solid_count": solids, "holes": holes, "outer_cylinders": [item for item in cylinders if not item["concave"]], "circular_edges": circular_edges, "cones": cones}}


def validate_step(step_path: str | Path, description: dict[str, Any]) -> dict[str, Any]:
    """Import the candidate. The caller must start a fresh restricted worker."""
    from build123d import import_step

    part = parse_description(description)
    path = Path(step_path)
    metadata = step_metadata(path, part.name)
    try:
        shape = import_step(path)
        result = measure_shape(shape, part)
    except Exception as error:
        return {"status": "fail", "checks": [check("step_reimport", False, reason=str(error)[:1000])], "step": metadata}
    result["checks"] = [check("step_reimport", True), *result["checks"], *metadata["checks"]]
    result["status"] = "fail" if any(item["status"] == "fail" for item in result["checks"]) else "pass"
    result["step"] = {key: value for key, value in metadata.items() if key != "checks"}
    return result
