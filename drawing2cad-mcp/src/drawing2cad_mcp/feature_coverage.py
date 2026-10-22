"""Feature coverage of a bound drawing: the rules FEAT-01 to FEAT-03 of the PDF verification.

The verifier derives a feature inventory from the bound STEP. It does not use the part description or the feature references
of the drawing specification. Each face of the model belongs to one feature:
- a round feature is a set of cylindrical faces with one axis, one radius, and one material side (a hole, a bore, or a boss).
  It is partial when its faces do not go around the axis, for example a fillet of a straight edge or the end of a slot,
- a conical feature is a set of conical faces with one axis, one apex, and one angle (a chamfer of a round edge or a countersink),
- a torus feature is a set of toroidal faces with one axis, one center, and two radii. With a profile arc of more than 91 degrees,
  it is a groove or a bead. Otherwise, it is a fillet of a round edge,
- a plane level is a set of planar faces with one normal and one offset (a face of a step, a pocket floor, or an end face).
  An inclined plane level is the only plane level along a normal that is not a model axis, for example a chamfer of a straight edge,
- a free-form surface is one face of another type, for example a B-spline or a sphere.
Each feature must be visible in a true-size view (FEAT-01). Each round, conical, and torus feature, each inclined plane level,
and each free-form surface must have its size (FEAT-02). A free-form surface has no supported size dimension: it needs an
uncertainty marker and a review decision. A chamfer needs two different sizes. A groove needs its profile radius and its size
across the axis. Along each model axis and each plane normal, the plane levels and the axes of the full round, conical, and torus
features must be connected by linear dimensions (FEAT-03). Along its axis, a groove also needs a position: the center of its
profile arc. An end of a full cylinder is also a position along its axis, unless a plane level or a cone or a torus to a plane
level locates it, for example the bottom of a blind hole. The adjacent faces locate a partial round feature and a fillet along its axis.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

POSITION_MM = 0.05     # A projected feature position and a drawn edge or a dimension anchor agree within this distance.
RADIUS_MM = 0.01       # A drawn radius and a model radius agree within this difference.
PARALLEL = 1e-6        # Two unit directions are parallel or perpendicular within this value.
MODEL_AXES = ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])
# Points on a curved boundary edge. For a circle, the largest gap to an extreme point is r * (1 - cos 0.5 degrees):
# less than 0.05 mm up to a radius of 1300 mm.
CURVE_SAMPLES = 360
AXIAL = {"hole", "boss", "cone", "torus"}
FULL_GAP_DEG = 5.0     # A cylinder is partial when its boundary points leave a larger angular gap around the axis.
GROOVE_SPAN_DEG = 91.0 # A torus with a larger profile arc is a groove or a bead. A fillet has a profile arc of 90 degrees or less.


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _unit(vector) -> list[float] | None:
    length = math.sqrt(_dot(vector, vector))
    return None if length <= 1e-12 else [c / length for c in vector]


def _canonical(direction) -> list[float]:
    """The direction or its opposite: the first component that is not zero is positive."""
    for value in direction:
        if abs(value) > 1e-9:
            return list(direction) if value > 0 else [-c for c in direction]
    return list(direction)


def _key(values, digits) -> tuple:
    return tuple(round(v, digits) + 0.0 for v in values)


def _edges(face) -> list[list[list[float]]]:
    """Points on each boundary edge of a face: the ends of a straight edge, and points along a curved edge."""
    from build123d import GeomType

    edges = []
    for edge in face.edges():
        count = 1 if edge.geom_type == GeomType.LINE else CURVE_SAMPLES
        points = []
        for index in range(count + 1):
            point = edge.position_at(index / count)
            points.append([round(point.X, 6), round(point.Y, 6), round(point.Z, 6)])
        edges.append(points)
    return edges


def _frame(axis) -> tuple[list[float], list[float]]:
    direction = _canonical([axis.Direction().X(), axis.Direction().Y(), axis.Direction().Z()])
    location = [axis.Location().X(), axis.Location().Y(), axis.Location().Z()]
    # The point of the axis nearest to the origin does not depend on the location along the axis.
    return direction, [location[i] - _dot(location, direction) * direction[i] for i in range(3)]


def _material_outside(surface, face, direction, foot) -> bool:
    """True if the face normal points to the axis: the material is outside, as in a hole."""
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.TopAbs import TopAbs_REVERSED

    u = (surface.FirstUParameter() + surface.LastUParameter()) / 2
    v = (surface.FirstVParameter() + surface.LastVParameter()) / 2
    props = BRepLProp_SLProps(surface, u, v, 1, 1e-6)
    point, normal = props.Value(), props.Normal()
    normal = [normal.X(), normal.Y(), normal.Z()]
    if face.wrapped.Orientation() == TopAbs_REVERSED:
        normal = [-c for c in normal]
    offset = [point.X() - foot[0], point.Y() - foot[1], point.Z() - foot[2]]
    radial = [offset[i] - _dot(offset, direction) * direction[i] for i in range(3)]
    return _dot(normal, radial) < 0


def _stations(points, direction, foot) -> list[tuple[float, float]]:
    """(station along the axis, distance from the axis) of each point."""
    result = []
    for point in points:
        offset = [point[i] - foot[i] for i in range(3)]
        station = _dot(offset, direction)
        radial = [offset[i] - station * direction[i] for i in range(3)]
        result.append((station, math.sqrt(_dot(radial, radial))))
    return result


def _around(points, direction, foot) -> list[float]:
    """The angle in degrees of each point around the axis, in a frame perpendicular to the axis."""
    helper = MODEL_AXES[min(range(3), key=lambda index: abs(direction[index]))]
    u = _unit(_cross(direction, helper))
    v = _cross(direction, u)
    result = []
    for point in points:
        offset = [point[i] - foot[i] for i in range(3)]
        radial = [offset[i] - _dot(offset, direction) * direction[i] for i in range(3)]
        if _dot(radial, radial) > 1e-12:
            result.append(math.degrees(math.atan2(_dot(radial, v), _dot(radial, u))))
    return result


def _largest_gap(angles) -> float:
    """The largest angular gap in degrees between angles on a full circle."""
    if not angles:
        return 360.0
    ordered = sorted(angle % 360 for angle in angles)
    return max([b - a for a, b in zip(ordered, ordered[1:])] + [ordered[0] + 360 - ordered[-1]])


def inventory(step_path: Path) -> dict[str, Any]:
    """The features of the bound STEP. Each face belongs to one feature."""
    from build123d import import_step
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Torus

    rounds: dict[tuple, dict] = {}
    cones: dict[tuple, dict] = {}
    tori: dict[tuple, dict] = {}
    planes: dict[tuple, dict] = {}
    surfaces: list[dict] = []
    for face in import_step(str(step_path)).faces():
        surface = BRepAdaptor_Surface(face.wrapped)
        kind = surface.GetType()
        edges = _edges(face)
        points = [point for edge in edges for point in edge]
        if kind == GeomAbs_Cylinder and points:
            cylinder = surface.Cylinder()
            direction, foot = _frame(cylinder.Axis())
            outside = _material_outside(surface, face, direction, foot)
            # The extent along the axis, from points on the boundary edges. Inclined or curved ends can pass the vertices.
            stations = [station for station, _ in _stations(points, direction, foot)]
            entry = rounds.setdefault(_key(direction, 6) + _key(foot, 4) + _key([cylinder.Radius()], 4) + (outside,),
                                      {"axis": direction, "foot": foot, "radius": cylinder.Radius(), "outside": outside, "stations": [],
                                       "angles": []})
            entry["stations"] += stations
            entry["angles"] += _around(points, direction, foot)
        elif kind == GeomAbs_Cone and points:
            cone = surface.Cone()
            direction, foot = _frame(cone.Axis())
            apex = [cone.Apex().X(), cone.Apex().Y(), cone.Apex().Z()]
            outside = _material_outside(surface, face, direction, foot)
            entry = cones.setdefault(_key(direction, 6) + _key(foot, 4) + _key(apex, 4) + _key([abs(cone.SemiAngle())], 6) + (outside,),
                                     {"axis": direction, "foot": foot, "outside": outside, "half_angle": math.degrees(abs(cone.SemiAngle())),
                                      "stations": []})
            entry["stations"] += _stations(points, direction, foot)
        elif kind == GeomAbs_Torus and points:
            torus = surface.Torus()
            direction, foot = _frame(torus.Axis())
            center = [torus.Location().X(), torus.Location().Y(), torus.Location().Z()]
            station = _dot([center[i] - foot[i] for i in range(3)], direction)
            entry = tori.setdefault(_key(direction, 6) + _key(foot, 4) + _key([station, torus.MajorRadius(), torus.MinorRadius()], 4),
                                    {"axis": direction, "foot": foot, "station": station, "major": torus.MajorRadius(),
                                     "minor": torus.MinorRadius(), "angles": [], "stations": []})
            # The angle of each boundary point around the center of the profile circle.
            entry["angles"] += [math.degrees(math.atan2(distance - entry["major"], along - station))
                                for along, distance in _stations(points, direction, foot)]
            entry["stations"] += [along for along, _ in _stations(points, direction, foot)]
        elif kind == GeomAbs_Plane and points:
            plane = surface.Plane()
            normal = _canonical([plane.Axis().Direction().X(), plane.Axis().Direction().Y(), plane.Axis().Direction().Z()])
            location = [plane.Axis().Location().X(), plane.Axis().Location().Y(), plane.Axis().Location().Z()]
            offset = _dot(normal, location)
            entry = planes.setdefault(_key(normal, 6) + _key([offset], 4), {"normal": normal, "offset": offset, "faces": []})
            entry["faces"].append(points)
        else:
            name = str(kind).split(".")[-1].removeprefix("GeomAbs_").lower()
            surfaces.append({"surface_type": name, "edges": edges})
    features = []
    for number, entry in enumerate(sorted(rounds.values(), key=lambda e: (-e["radius"], _key(e["axis"], 6), _key(e["foot"], 4),
                                                                            min(e["stations"]))), 1):
        features.append({"id": f"round_{number}", "kind": "hole" if entry["outside"] else "boss", "axis": _key(entry["axis"], 9),
                         "foot": _key(entry["foot"], 6), "radius": round(entry["radius"], 6),
                         "extent": [round(min(entry["stations"]), 6), round(max(entry["stations"]), 6)],
                         # A partial cylinder, for example a fillet of a straight edge or the end of a slot, does not go around its axis.
                         "full": _largest_gap(entry["angles"]) <= FULL_GAP_DEG})
    for number, entry in enumerate(sorted(cones.values(), key=lambda e: (_key(e["axis"], 6), _key(e["foot"], 4), min(e["stations"]))), 1):
        low, high = min(s for s, _ in entry["stations"]), max(s for s, _ in entry["stations"])
        # The radius at each end of the extent, from the boundary points at that end.
        radii = [max(r for s, r in entry["stations"] if abs(s - end) <= 1e-4) for end in (low, high)]
        features.append({"id": f"cone_{number}", "kind": "cone", "side": "hole" if entry["outside"] else "boss",
                         "axis": _key(entry["axis"], 9), "foot": _key(entry["foot"], 6), "extent": [round(low, 6), round(high, 6)],
                         "radii": [round(r, 6) for r in radii], "half_angle": round(entry["half_angle"], 6)})
    for number, entry in enumerate(sorted(tori.values(), key=lambda e: (_key(e["axis"], 6), _key(e["foot"], 4), e["station"])), 1):
        features.append({"id": f"torus_{number}", "kind": "torus", "axis": _key(entry["axis"], 9), "foot": _key(entry["foot"], 6),
                         "station": round(entry["station"], 6), "major": round(entry["major"], 6), "minor": round(entry["minor"], 6),
                         "extent": [round(min(entry["stations"]), 6), round(max(entry["stations"]), 6)],
                         "profile_span": round(360.0 - _largest_gap(entry["angles"]), 3)})
    normals: dict[tuple, int] = {}
    for entry in planes.values():
        normals[_key(entry["normal"], 6)] = normals.get(_key(entry["normal"], 6), 0) + 1
    for number, entry in enumerate(sorted(planes.values(), key=lambda e: (_key(e["normal"], 6), round(e["offset"], 4))), 1):
        # An inclined plane level: its normal is not a model axis, and no other plane level is parallel to it.
        inclined = max(abs(c) for c in entry["normal"]) < 1 - PARALLEL and normals[_key(entry["normal"], 6)] == 1
        features.append({"id": f"plane_{number}", "kind": "plane_level", "normal": _key(entry["normal"], 9),
                         "offset": round(entry["offset"], 6), "inclined": inclined, "faces": entry["faces"]})
    for number, entry in enumerate(surfaces, 1):
        features.append({"id": f"surface_{number}", "kind": "surface", **entry})
    return {"features": features}


class _View:
    """A true-size view with a model projection: local = matrix * model point."""

    def __init__(self, view: dict, model: dict):
        self.id = view["id"]
        self.rows = [[float(c) for c in row] for row in view["projection"]["matrix"]]
        self.direction = _unit(_cross(self.rows[0], self.rows[1]))
        self.model = model["geometry"]
        self.cut = model.get("cutting_plane")
        self.own = view["geometry"]
        self.dimensions = view["dimensions"]

    def point(self, p) -> list[float]:
        return [_dot(self.rows[0], p), _dot(self.rows[1], p)]

    def model_direction(self, local) -> list[float]:
        return [local[0] * self.rows[0][i] + local[1] * self.rows[1][i] for i in range(3)]


def _true_size(view: dict) -> bool:
    return (view["kind"] in {"orthographic", "section", "detail"}
            and (view.get("projection") or {}).get("scale_convention") == "true_size")


def _cross2(a, b) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _on_faces(feature: dict, view: _View, points) -> bool:
    """True if each point is on the edge-on trace of one face of the plane level, between the ends of the projected face."""
    normal = view.point(feature["normal"])
    tangent = [-normal[1], normal[0]]
    for face in feature["faces"]:
        stations = [_dot(tangent, view.point(p)) for p in face]
        low, high = min(stations), max(stations)
        if all(low - POSITION_MM <= _dot(tangent, p) <= high + POSITION_MM for p in points):
            return True
    return False


def _on_trace(feature: dict, view: _View, points) -> bool:
    """True if the plane level is edge-on in the view and each point is on its trace."""
    if abs(_dot(feature["normal"], view.direction)) > PARALLEL:
        return False
    normal = view.point(feature["normal"])
    return all(abs(_dot(normal, point) - feature["offset"]) <= POSITION_MM for point in points) and _on_faces(feature, view, points)


def _axial(feature: dict, view: _View, point) -> tuple[float, float]:
    """(station along the axis, signed distance from the axis) of a local point. The axis is in the view plane."""
    axis = _unit(view.point(feature["axis"]))
    center = view.point(feature["foot"])
    offset = [point[0] - center[0], point[1] - center[1]]
    return _dot(axis, offset), _cross2(axis, offset)


def _cut_offset(feature: dict, view: _View) -> float | None:
    """The distance of the axis from the cutting plane, if the cutting plane is parallel to the axis."""
    if view.cut is None:
        return None
    normal = _unit([float(c) for c in view.cut["normal"]])
    if abs(_dot(normal, feature["axis"])) > PARALLEL:
        return None
    return abs(_dot(normal, [feature["foot"][i] - float(view.cut["origin"][i]) for i in range(3)]))


def _cone_radius(feature: dict, station: float) -> float:
    (low, high), (r_low, r_high) = feature["extent"], feature["radii"]
    return r_low if high - low <= 1e-9 else r_low + (station - low) * (r_high - r_low) / (high - low)


def _on_cone_outline(feature: dict, view: _View, points) -> bool:
    """True if each point is on one outline of the conical feature: at the cone radius of its station, on one side of the axis."""
    sides = []
    low, high = feature["extent"]
    for point in points:
        station, side = _axial(feature, view, point)
        if not low - POSITION_MM <= station <= high + POSITION_MM or abs(abs(side) - _cone_radius(feature, station)) > POSITION_MM:
            return False
        sides.append(side)
    return all(side >= -POSITION_MM for side in sides) or all(side <= POSITION_MM for side in sides)


def _on_torus_profile(feature: dict, view: _View, points) -> bool:
    """True if each point is on one profile circle of the torus: at the minor radius from a point at the major radius from the axis."""
    for sign in (1, -1):
        if all(abs(math.hypot(station - feature["station"], side - sign * feature["major"]) - feature["minor"]) <= POSITION_MM
               for station, side in (_axial(feature, view, point) for point in points)):
            return True
    return False


def _sample(item: dict) -> list[list[float]]:
    if item["type"] == "line":
        return [item["start"], [(item["start"][0] + item["end"][0]) / 2, (item["start"][1] + item["end"][1]) / 2], item["end"]]
    if item["type"] in {"circle", "arc"}:
        start, sweep = (0.0, 360.0) if item["type"] == "circle" else (item["start_angle"], (item["end_angle"] - item["start_angle"]) % 360 or 360)
        return [[item["center"][0] + item["radius"] * math.cos(math.radians(start + sweep * f / 8)),
                 item["center"][1] + item["radius"] * math.sin(math.radians(start + sweep * f / 8))] for f in range(9)]
    if item["type"] == "ellipse":
        major = item["major_axis"]
        minor = [-major[1] * item["ratio"], major[0] * item["ratio"]]
        start, end = item.get("start_parameter", 0.0), item.get("end_parameter", 360.0)
        return [[item["center"][0] + math.cos(math.radians(a)) * major[0] + math.sin(math.radians(a)) * minor[0],
                 item["center"][1] + math.cos(math.radians(a)) * major[1] + math.sin(math.radians(a)) * minor[1]]
                for a in (start + (end - start) * f / 8 for f in range(9))]
    return []


def _segment_distance(point, a, b) -> float:
    d = [b[0] - a[0], b[1] - a[1]]
    length = d[0] ** 2 + d[1] ** 2
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((point[0] - a[0]) * d[0] + (point[1] - a[1]) * d[1]) / length))
    return math.dist(point, [a[0] + t * d[0], a[1] + t * d[1]])


def _on_boundary(feature: dict, view: _View, points) -> bool:
    """True if each point is on the projected boundary of the free-form surface."""
    edges = [[view.point(p) for p in edge] for edge in feature["edges"]]
    return all(any(_segment_distance(point, a, b) <= POSITION_MM for edge in edges for a, b in zip(edge, edge[1:] or edge))
               for point in points)


def _shows(feature: dict, view: _View, item: dict) -> bool:
    """True if the primitive is an edge of the feature in this view."""
    kind = feature["kind"]
    if kind == "plane_level":
        # The plane is edge-on. Its trace is a line at its offset along the projected normal, on the projection of one of its faces.
        return item["type"] == "line" and _on_trace(feature, view, (item["start"], item["end"]))
    if kind == "surface":
        points = _sample(item)
        return bool(points) and _on_boundary(feature, view, points)
    along = abs(_dot(feature["axis"], view.direction))
    center = view.point(feature["foot"])
    if along >= 1 - PARALLEL:
        # Along the axis, each feature shows circles: the cylinder radius, the end radii of a cone, the outer and inner radius of a torus.
        radii = ([feature["radius"]] if kind in {"hole", "boss"} else feature["radii"] if kind == "cone"
                 else [feature["major"] + feature["minor"], feature["major"] - feature["minor"]])
        return (item["type"] in {"circle", "arc"} and math.dist(item["center"], center) <= POSITION_MM
                and any(radius > RADIUS_MM and abs(item["radius"] - radius) <= RADIUS_MM for radius in radii))
    if along > PARALLEL:
        return False
    # The axis is in the view plane. A section edge counts only where the cutting plane cuts the feature.
    offset = _cut_offset(feature, view) if item["style"] == "section" else 0.0
    if offset is None:
        return False
    if kind == "torus":
        # The profile of the torus is a pair of circles at the major radius from the axis, if the cutting plane contains the axis.
        # The derivation can give the profile as arcs or as a polyline. The vertices of a polyline are on the curve, its chords are not.
        points = [item["start"], item["end"]] if item["type"] == "line" else _sample(item)
        return offset <= POSITION_MM and bool(points) and _on_torus_profile(feature, view, points)
    if item["type"] != "line":
        return False
    if kind == "cone":
        return offset <= POSITION_MM and _on_cone_outline(feature, view, (item["start"], item["end"]))
    # The outlines of a cylinder are lines parallel to the axis at the radius, within its extent.
    # A cutting plane parallel to the axis at the distance d from the axis cuts the cylinder at sqrt(r^2 - d^2) from the axis.
    if offset >= feature["radius"]:
        return False
    axis = _unit(view.point(feature["axis"]))
    line = _unit([item["end"][0] - item["start"][0], item["end"][1] - item["start"][1], 0.0])
    if line is None or abs(_cross2(axis, line)) > PARALLEL:
        return False
    low, high = feature["extent"]
    ends = [_axial(feature, view, point) for point in (item["start"], item["end"])]
    if not all(low - POSITION_MM <= station <= high + POSITION_MM for station, _ in ends):
        return False
    return abs(abs(ends[0][1]) - math.sqrt(feature["radius"] ** 2 - offset ** 2)) <= POSITION_MM


def _measure_direction(dimension: dict) -> list[float] | None:
    axis = dimension.get("axis", "horizontal")
    if axis == "horizontal":
        return [1.0, 0.0]
    if axis == "vertical":
        return [0.0, 1.0]
    vector = _unit([dimension["p2"][0] - dimension["p1"][0], dimension["p2"][1] - dimension["p1"][1], 0.0])
    return None if vector is None else vector[:2]


def _legs(dimension: dict) -> list[tuple]:
    return [(dimension["center"], dimension["p1"]), (dimension["center"], dimension["p2"])]


def _direction_tag(view: _View, measure) -> str:
    """The model direction of a measurement direction, or its opposite, as a constraint tag of a length.

    The same length in two views with different orientations gets the same tag."""
    return f"length@{_label(_key(_canonical(view.model_direction(measure)), 4))}"


def _cone_tag(feature: dict, view: _View, dimension: dict, anchor) -> str | None:
    """The constraint tag of a linear dimension with an anchor on an outline of the conical feature."""
    measure = _measure_direction(dimension)
    if measure is None:
        return None
    axis = _unit(view.point(feature["axis"]))
    along = abs(_dot(axis[:2], measure))
    if along >= 1 - PARALLEL:
        return "axial"
    if along > PARALLEL:
        return _direction_tag(view, measure)
    # Across the axis, the dimension measures the cone radius at the station of its anchor. Near an end, this is the end radius.
    station, _ = _axial(feature, view, anchor)
    radius = next((r for end, r in zip(feature["extent"], feature["radii"]) if abs(station - end) <= POSITION_MM),
                  _cone_radius(feature, station))
    return f"diameter@{radius:.3f}"


def _sizes(feature: dict, view: _View, passed: set[str]) -> list[tuple[str, str]]:
    """The passed dimensions of this view that give a size of the feature, each with its constraint tag.

    Two dimensions with the same tag give the same size. A chamfer needs two different tags: "angle", "axial" (a length along the
    axis of a cone), "diameter@<radius>" (the size of a cone at one radius), or "length@<direction>" (a length in one model
    direction). A torus has the tag "radius" (its minor radius). A groove also has the tag "major" (its size across the axis)."""
    found = []
    kind = feature["kind"]
    dimensions = [dimension for dimension in view.dimensions if dimension["id"] in passed]
    if kind == "plane_level":
        # An inclined plane level is sized by lengths to its trace and by angles with a leg along its trace.
        for dimension in dimensions:
            if dimension["type"] == "linear" and any(_on_trace(feature, view, (point,)) for point in (dimension["p1"], dimension["p2"])):
                measure = _measure_direction(dimension)
                if measure is not None:
                    found.append((dimension["id"], _direction_tag(view, measure)))
            elif dimension["type"] == "angular" and any(_on_trace(feature, view, leg) for leg in _legs(dimension)):
                found.append((dimension["id"], "angle"))
        return found
    along = abs(_dot(feature["axis"], view.direction))
    center = view.point(feature["foot"])
    # The size of a groove across its axis: the radius of its bottom, of its profile center, or of its outer edge.
    major = ([radius for radius in (feature["major"] - feature["minor"], feature["major"], feature["major"] + feature["minor"])
              if radius > RADIUS_MM] if _groove(feature) else [])
    for dimension in dimensions:
        if dimension["type"] in {"radius", "diameter"}:
            if along >= 1 - PARALLEL and math.dist(dimension["center"], center) <= POSITION_MM:
                radii = [feature["radius"]] if kind in {"hole", "boss"} else feature["radii"] if kind == "cone" else major
                radius = next((radius for radius in radii if abs(dimension["radius"] - radius) <= RADIUS_MM), None)
                if radius is not None:
                    found.append((dimension["id"], f"diameter@{radius:.3f}" if kind == "cone" else "major" if kind == "torus"
                                  else "diameter"))
            elif kind == "torus" and along <= PARALLEL and abs(dimension["radius"] - feature["minor"]) <= RADIUS_MM:
                station, side = _axial(feature, view, dimension["center"])
                if abs(station - feature["station"]) <= POSITION_MM and abs(abs(side) - feature["major"]) <= POSITION_MM:
                    found.append((dimension["id"], "radius"))
        elif along <= PARALLEL and kind == "cone":
            if dimension["type"] == "linear":
                anchors = [point for point in (dimension["p1"], dimension["p2"]) if _on_cone_outline(feature, view, (point,))]
                tag = _cone_tag(feature, view, dimension, anchors[0]) if anchors else None
                if tag is not None:
                    found.append((dimension["id"], tag))
            elif dimension["type"] == "angular" and any(_on_cone_outline(feature, view, leg) for leg in _legs(dimension)):
                found.append((dimension["id"], "angle"))
        elif along <= PARALLEL and kind in {"hole", "boss"} and dimension["type"] == "linear":
            # A linear dimension across the axis, from one outline to the other, within the extent.
            axis = _unit(view.point(feature["axis"]))
            measure = _measure_direction(dimension)
            if measure is None or abs(_dot(axis[:2], measure)) > PARALLEL:
                continue
            ends = [_axial(feature, view, point) for point in (dimension["p1"], dimension["p2"])]
            low, high = feature["extent"]
            if (all(abs(abs(side) - feature["radius"]) <= POSITION_MM and low - POSITION_MM <= station <= high + POSITION_MM
                    for station, side in ends) and ends[0][1] * ends[1][1] < 0):
                found.append((dimension["id"], "diameter"))
        elif along <= PARALLEL and major and dimension["type"] == "linear":
            # A linear dimension across the axis of a groove, between two points on opposite sides at one of its radii,
            # within the profile of the groove along the axis.
            axis = _unit(view.point(feature["axis"]))
            measure = _measure_direction(dimension)
            if measure is None or abs(_dot(axis[:2], measure)) > PARALLEL:
                continue
            ends = [_axial(feature, view, point) for point in (dimension["p1"], dimension["p2"])]
            if (ends[0][1] * ends[1][1] < 0 and all(abs(station - feature["station"]) <= feature["minor"] + POSITION_MM for station, _ in ends)
                    and any(all(abs(abs(side) - radius) <= POSITION_MM for _, side in ends) for radius in major)):
                found.append((dimension["id"], "major"))
    return found


def _sized(feature: dict, tags: list[tuple[str, str]]) -> bool:
    if _groove(feature):
        # A groove needs its profile radius and its size across the axis.
        return {"radius", "major"} <= {tag for _, tag in tags}
    if feature["kind"] in {"hole", "boss", "torus"}:
        return bool(tags)
    # A chamfer needs two different sizes. A repeated measurement of one size, for example two diameters at one end of a cone
    # or one length under two identifiers, counts once.
    return len({tag for _, tag in tags}) >= 2


def sized_radii(coverage: list[dict]) -> set[float]:
    """The radii of the round model edges of the features that FEAT-02 sized, for DIM-03: the cylinder radius,
    the end radii of a cone that are not zero, and the outer and inner radius of a torus.
    A groove gives these radii only when its size across the axis is dimensioned."""
    radii: set[float] = set()
    for item in coverage:
        if item["kind"] in {"plane_level", "surface"} or not item["size_dimensions"]:
            continue
        if item["kind"] in {"hole", "boss"}:
            values = [item["radius"]]
        elif item["kind"] == "cone":
            values = [radius for radius in item["radii"] if radius > RADIUS_MM]
        elif _groove(item) and not item.get("major_sized"):
            continue
        else:
            inner = item["major"] - item["minor"]
            values = [item["major"] + item["minor"]] + ([inner] if inner > RADIUS_MM else [])
        radii |= {round(value, 3) for value in values}
    return radii


def _directions(features: list[dict]) -> list[list[float]]:
    directions = {_key(axis, 6): list(axis) for axis in MODEL_AXES}
    for feature in features:
        if feature["kind"] == "plane_level":
            directions.setdefault(_key(feature["normal"], 6), list(feature["normal"]))
    return [directions[key] for key in sorted(directions)]


def _label(direction) -> str:
    return "[" + ", ".join(f"{c:.6g}" for c in (0.0 if abs(c) < 1e-12 else c for c in direction)) + "]"


def _groove(feature: dict) -> bool:
    return feature["kind"] == "torus" and feature.get("profile_span", 0.0) > GROOVE_SPAN_DEG


def _at(feature: dict, view: _View, point, direction) -> bool:
    if feature["kind"] == "plane_level":
        return _on_faces(feature, view, (point,))
    if _groove(feature) and abs(_dot(feature["axis"], direction)) >= 1 - PARALLEL:
        # The axial position of a groove is the center of its profile arc, in a view with the axis in the view plane.
        if abs(_dot(feature["axis"], view.direction)) > PARALLEL:
            return False
        station, side = _axial(feature, view, point)
        return abs(station - feature["station"]) <= POSITION_MM and abs(abs(side) - feature["major"]) <= POSITION_MM
    if feature["kind"] in {"hole", "boss"} and abs(_dot(feature["axis"], direction)) >= 1 - PARALLEL:
        # The axial position of a cylinder is an end of its extent, in a view with the axis in the view plane.
        # The anchor is on the end, at most the radius from the axis: the end of an outline or the bottom line of a hole.
        if abs(_dot(feature["axis"], view.direction)) > PARALLEL:
            return False
        station, side = _axial(feature, view, point)
        return abs(side) <= feature["radius"] + POSITION_MM and any(abs(station - end) <= POSITION_MM for end in feature["extent"])
    return (abs(_dot(feature["axis"], view.direction)) >= 1 - PARALLEL
            and math.dist(point, view.point(feature["foot"])) <= POSITION_MM)


def _coordinate(feature: dict, station: float, direction) -> float:
    """The coordinate along the direction of the point at the station on the axis of the feature."""
    return _dot(feature["foot"], direction) + station * _dot(feature["axis"], direction)


def _open_ends(feature: dict, features: list[dict], direction) -> list[float]:
    """The coordinates along the direction of the ends of a full cylinder with its axis along the direction,
    without the ends that are anchored.

    An end is anchored at the coordinate of a plane level, or at an end of a cone or a torus on the same axis whose
    other end is anchored, for example at the chamfer of a hole to a face. The tip of a drill point does not anchor an end."""
    anchored = [level["offset"] * (1 if _dot(level["normal"], direction) > 0 else -1) for level in features
                if level["kind"] == "plane_level" and abs(_dot(level["normal"], direction)) >= 1 - PARALLEL]
    links = []
    for other in features:
        if (other["kind"] in {"cone", "torus"} and abs(_dot(other["axis"], feature["axis"])) >= 1 - PARALLEL
                and math.dist(other["foot"], feature["foot"]) <= POSITION_MM):
            ends = other.get("extent") or [other["station"] - other["minor"], other["station"] + other["minor"]]
            links.append([_coordinate(other, end, direction) for end in ends])

    def known(value) -> bool:
        return any(abs(value - item) <= POSITION_MM for item in anchored)

    changed = True
    while changed:
        changed = False
        for first, second in links:
            for end, other_end in ((first, second), (second, first)):
                if known(other_end) and not known(end):
                    anchored.append(end)
                    changed = True
    return [value for value in (_coordinate(feature, end, direction) for end in feature["extent"]) if not known(value)]


def _positions(features: list[dict], views: list[_View], passed: set[str]) -> dict[str, dict[str, bool]]:
    """For each feature and each direction with more than one position: is the feature connected by dimensions?"""
    result: dict[str, dict[str, bool]] = {feature["id"]: {} for feature in features}
    by_id = {feature["id"]: feature for feature in features}
    for direction in _directions(features):
        # The nodes are the distinct coordinates along the direction. Coinciding features share a node.
        # A partial cylinder has no node: its adjacent faces locate it.
        coordinates: list[tuple[float, str]] = []
        for feature in features:
            if feature["kind"] == "plane_level":
                if abs(_dot(feature["normal"], direction)) >= 1 - PARALLEL:
                    coordinates.append((feature["offset"] * (1 if _dot(feature["normal"], direction) > 0 else -1), feature["id"]))
            elif feature["kind"] in AXIAL and feature.get("full", True) and abs(_dot(feature["axis"], direction)) <= PARALLEL:
                coordinates.append((_dot(feature["foot"], direction), feature["id"]))
            elif _groove(feature) and abs(_dot(feature["axis"], direction)) >= 1 - PARALLEL:
                # A groove also has a node along its axis: the center of its profile arc. A fillet follows from tangency.
                coordinates.append((_coordinate(feature, feature["station"], direction), feature["id"]))
            elif (feature["kind"] in {"hole", "boss"} and feature.get("full", True)
                  and abs(_dot(feature["axis"], direction)) >= 1 - PARALLEL):
                # An end of a full cylinder that no plane level locates is a node, for example the bottom of a blind hole.
                coordinates += [(value, feature["id"]) for value in _open_ends(feature, features, direction)]
        nodes: list[list] = []
        for value, identifier in sorted(coordinates):
            if nodes and value - nodes[-1][0] <= POSITION_MM:
                nodes[-1][1].append(identifier)
            else:
                nodes.append([value, [identifier]])
        if len(nodes) <= 1:
            continue
        parent = list(range(len(nodes)))

        def root(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def node(value, point, view):
            # The anchor must be at a feature of the node: on a face of a plane level, or at the center of an axial feature.
            for index, (coordinate, identifiers) in enumerate(nodes):
                if abs(coordinate - value) <= POSITION_MM and any(_at(by_id[identifier], view, point, direction)
                                                                  for identifier in identifiers):
                    return index
            return None

        for view in views:
            for dimension in view.dimensions:
                if dimension["type"] != "linear" or dimension["id"] not in passed:
                    continue
                measure = _measure_direction(dimension)
                if measure is None:
                    continue
                along = _dot(view.model_direction(measure), direction)
                if abs(along) < 1 - PARALLEL:
                    continue
                # Local coordinate along the measurement direction = model coordinate along the model direction.
                ends = [node(math.copysign(1, along) * _dot(measure, point), point, view) for point in (dimension["p1"], dimension["p2"])]
                if None not in ends:
                    parent[root(ends[0])] = root(ends[1])
        groups: dict[int, list[int]] = {}
        for index in range(len(nodes)):
            groups.setdefault(root(index), []).append(index)
        # The reference is the connected group with the most features, and of equal groups the one with the lowest coordinate.
        reference = max(groups.values(), key=lambda members: (sum(len(nodes[index][1]) for index in members), -min(members)))
        for index, (_, identifiers) in enumerate(nodes):
            for identifier in identifiers:
                # A cylinder with two open ends has two nodes along its axis. Both must be connected.
                result[identifier][_label(direction)] = result[identifier].get(_label(direction), True) and index in reference
    return result


def _name(feature: dict) -> str:
    kind = feature["kind"]
    if kind in {"hole", "boss"}:
        prefix = "" if feature.get("full", True) else "partial "
        return f"{prefix}{kind} {feature['id']} (radius {feature['radius']:g} mm, axis {_label(feature['axis'])})"
    if kind == "cone":
        return (f"conical {feature['side']} face {feature['id']} (radius {feature['radii'][0]:g} to {feature['radii'][1]:g} mm, "
                f"half angle {feature['half_angle']:g} degrees, axis {_label(feature['axis'])})")
    if kind == "torus":
        role = "groove" if _groove(feature) else "fillet"
        return f"torus {role} {feature['id']} (radius {feature['minor']:g} mm, axis {_label(feature['axis'])})"
    if kind == "surface":
        return f"{feature['surface_type']} surface {feature['id']}"
    prefix = "inclined plane level" if feature["inclined"] else "plane level"
    return f"{prefix} {feature['id']} (normal {_label(feature['normal'])}, offset {feature['offset']:g} mm)"


SIZE_FAILURES = {
    "hole": "has no diameter or radius dimension that agrees with the bound model",
    "boss": "has no diameter or radius dimension that agrees with the bound model",
    "cone": ("needs two different sizes that agree with the bound model: an angle and a length or diameter, or a length along the axis "
             "and a diameter, or the diameters at its two ends"),
    "torus": "has no radius dimension at its profile arc that agrees with the bound model",
    "groove": ("needs two sizes that agree with the bound model: a radius dimension at its profile arc, and a diameter or radius "
               "across its axis, for example the diameter of the groove bottom"),
    "plane_level": ("needs two different sizes that agree with the bound model: an angle and a length, "
                    "or two lengths in different directions to its trace"),
    "surface": "has no supported size dimension. Mark it with an uncertainty marker and decide it in the drawing review",
}


def check(report, views: list[dict], derived: dict[str, dict], found: dict[str, Any], passed: set[str],
          markers: list[dict]) -> list[dict]:
    """Add FEAT-01 to FEAT-03 to the report and return the coverage of each feature."""
    features = found["features"]
    usable = [_View(view, derived[view["id"]]) for view in views if view["id"] in derived and _true_size(view)]
    by_view = {view["id"]: view for view in views}
    marked: dict[str, list[str]] = {feature["id"]: [] for feature in features}
    for marker in markers:
        view = next((item for item in usable if item.id == marker["view_id"]), None)
        primitive = next((item for item in by_view.get(marker["view_id"], {}).get("geometry", []) if item["id"] == marker["primitive_id"]), None)
        if view is None or primitive is None:
            continue
        for feature in features:
            if _shows(feature, view, primitive):
                marked[feature["id"]].append(marker["id"])
    positions = _positions(features, usable, passed)
    sized_kinds = [feature for feature in features if feature["kind"] != "plane_level" or feature["inclined"]]
    if not features:
        for rule in ("FEAT-01", "FEAT-02", "FEAT-03"):
            report.add(rule, "not_applicable", "info", "The bound model has no face.")
    elif not sized_kinds:
        report.add("FEAT-02", "not_applicable", "info", "The bound model has only plane levels along model axes. FEAT-03 checks their distances.")
    elif all(feature["kind"] == "surface" for feature in features):
        report.add("FEAT-03", "not_applicable", "info", "The bound model has only free-form surfaces. They have no position rule.")

    def add(rule: str, feature: dict, ok: bool, passed_text: str, failed_text: str, observed) -> str:
        if ok:
            report.add(rule, "pass", "info", passed_text, feature=feature["id"], observed=observed)
            return "pass"
        if marked[feature["id"]]:
            report.add(rule, "needs_review", "minor", failed_text + f" It has the uncertainty marker {', '.join(marked[feature['id']])}.",
                       feature=feature["id"], observed=observed)
            return "needs_review"
        report.add(rule, "fail", "major", failed_text, feature=feature["id"], observed=observed)
        return "fail"

    # An edge or a size dimension that fits more than one feature of one kind in a view, for example the common circle of a bore
    # below a boss or the coinciding outlines of two holes behind each other, does not show which feature it belongs to.
    # It counts for none of them. An edge between features of two kinds, for example the circle between a hole and its chamfer,
    # belongs to both.
    axial = [feature for feature in features if feature["kind"] in AXIAL]

    def group(feature: dict) -> str:
        return "cylinder" if feature["kind"] in {"hole", "boss"} else feature["kind"]

    def own(feature: dict, view: _View, item: dict) -> bool:
        if not _shows(feature, view, item):
            return False
        return feature["kind"] not in AXIAL or [other["id"] for other in axial
                                                if group(other) == group(feature) and _shows(other, view, item)] == [feature["id"]]

    coverage = []
    claims: dict[tuple[str, str, str], list[str]] = {}
    roles: dict[str, list[tuple[str, str]]] = {feature["id"]: [] for feature in features}
    for feature in sized_kinds:
        for view in usable:
            for identifier, role in _sizes(feature, view, passed) if feature["kind"] != "surface" else []:
                roles[feature["id"]].append((identifier, role))
                if feature["kind"] in AXIAL:
                    claims.setdefault((group(feature), view.id, identifier), []).append(feature["id"])
    for feature in features:
        name = _name(feature)
        visible = [view.id for view in usable if any(item["style"] in {"visible", "section"} and own(feature, view, item) for item in view.model)]
        hidden = [view.id for view in usable if any(item["style"] == "hidden" and own(feature, view, item) for item in view.model)]
        statuses = [add("FEAT-01", feature, bool(visible), f"The {name} is visible in {', '.join(visible) if visible else ''}.",
                        f"No true-size view shows the {name} with visible edges."
                        + (" Only hidden lines show it. Add a section or a view." if hidden else " Add a view or a section that shows it."),
                        {"visible_in": visible, "hidden_in": hidden})]
        sizes = None
        extra = {}
        if feature in sized_kinds:
            unique = [(identifier, role) for identifier, role in roles[feature["id"]]
                      if feature["kind"] not in AXIAL or any(owners == [feature["id"]] for (kind, _, other), owners in claims.items()
                                                             if kind == group(feature) and other == identifier)]
            sizes = sorted({identifier for identifier, _ in unique})
            if _groove(feature):
                extra["major_sized"] = any(role == "major" for _, role in unique)
            statuses.append(add("FEAT-02", feature, feature["kind"] != "surface" and _sized(feature, unique),
                                f"The {name} has the size dimensions {', '.join(sizes)}.",
                                f"The {name} {SIZE_FAILURES['groove' if _groove(feature) else feature['kind']]}.", {"dimensions": sizes}))
        located = positions[feature["id"]]
        if feature["kind"] != "surface":
            open_directions = [direction for direction, ok in located.items() if not ok]
            statuses.append(add("FEAT-03", feature, not open_directions,
                                f"The position of the {name} is connected to the other features by dimensions." if located else
                                f"The position of the {name} follows from its adjacent faces." if not feature.get("full", True) else
                                f"The {name} is the only position along each checked direction.",
                                f"The position of the {name} has no dimension chain to the other features along {', '.join(open_directions)}.",
                                {"directions": located}))
        status = "fail" if "fail" in statuses else "needs_review" if "needs_review" in statuses else "pass"
        coverage.append({**{key: value for key, value in feature.items() if key not in {"faces", "edges"}}, "visible_in": visible,
                         "size_dimensions": sizes, **extra, "positions": located, "markers": marked[feature["id"]], "status": status})
    return coverage
