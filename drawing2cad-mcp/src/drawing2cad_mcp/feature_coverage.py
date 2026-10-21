"""Feature coverage of a bound drawing: the rules FEAT-01 to FEAT-04 of the PDF verification.

The verifier derives a feature inventory from the bound STEP. It does not use the part description or the feature references
of the drawing specification:
- a round feature is a set of cylindrical faces with one axis and one radius (a hole, a bore, or a boss),
- a plane level is a set of planar faces with one normal and one offset (a face of a step, a pocket floor, or an end face).
Each feature must be visible in a true-size view (FEAT-01). Each round feature must have a size dimension (FEAT-02).
Along each model axis and each plane normal, the plane levels and the axes of the round features must be connected
by linear dimensions (FEAT-03). Other surfaces, for example cones and tori, are outside the inventory profile (FEAT-04).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

POSITION_MM = 0.05     # A projected feature position and a drawn edge or a dimension anchor agree within this distance.
RADIUS_MM = 0.01       # A drawn radius and a model radius agree within this difference.
PARALLEL = 1e-6        # Two unit directions are parallel or perpendicular within this value.
MODEL_AXES = ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])


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


def inventory(step_path: Path) -> dict[str, Any]:
    """The round features, the plane levels, and the counts of other surface types of the bound STEP."""
    from build123d import import_step
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.TopAbs import TopAbs_REVERSED

    rounds: dict[tuple, dict] = {}
    planes: dict[tuple, dict] = {}
    other: dict[str, int] = {}
    for face in import_step(str(step_path)).faces():
        surface = BRepAdaptor_Surface(face.wrapped)
        kind = surface.GetType()
        if kind == GeomAbs_Cylinder:
            cylinder = surface.Cylinder()
            axis = cylinder.Axis()
            direction = _canonical([axis.Direction().X(), axis.Direction().Y(), axis.Direction().Z()])
            location = [axis.Location().X(), axis.Location().Y(), axis.Location().Z()]
            # The point of the axis nearest to the origin does not depend on the location along the axis.
            foot = [location[i] - _dot(location, direction) * direction[i] for i in range(3)]
            radius = cylinder.Radius()
            # A hole has its material outside: the face normal points to the axis.
            u = (surface.FirstUParameter() + surface.LastUParameter()) / 2
            v = (surface.FirstVParameter() + surface.LastVParameter()) / 2
            props = BRepLProp_SLProps(surface, u, v, 1, 1e-6)
            point, normal = props.Value(), props.Normal()
            normal = [normal.X(), normal.Y(), normal.Z()]
            if face.wrapped.Orientation() == TopAbs_REVERSED:
                normal = [-c for c in normal]
            offset = [point.X() - foot[0], point.Y() - foot[1], point.Z() - foot[2]]
            radial = [offset[i] - _dot(offset, direction) * direction[i] for i in range(3)]
            entry = rounds.setdefault(_key(direction, 6) + _key(foot, 4) + _key([radius], 4),
                                      {"axis": direction, "foot": foot, "radius": radius, "concave": False})
            entry["concave"] = entry["concave"] or _dot(normal, radial) < 0
        elif kind == GeomAbs_Plane:
            plane = surface.Plane()
            axis = plane.Axis()
            normal = _canonical([axis.Direction().X(), axis.Direction().Y(), axis.Direction().Z()])
            location = [axis.Location().X(), axis.Location().Y(), axis.Location().Z()]
            offset = _dot(normal, location)
            planes.setdefault(_key(normal, 6) + _key([offset], 4), {"normal": normal, "offset": offset})
        else:
            name = str(kind).split(".")[-1].removeprefix("GeomAbs_").lower()
            other[name] = other.get(name, 0) + 1
    features = []
    for number, entry in enumerate(sorted(rounds.values(), key=lambda e: (-e["radius"], _key(e["axis"], 6), _key(e["foot"], 4))), 1):
        features.append({"id": f"round_{number}", "kind": "hole" if entry["concave"] else "boss", "axis": _key(entry["axis"], 9),
                         "foot": _key(entry["foot"], 6), "radius": round(entry["radius"], 6)})
    for number, entry in enumerate(sorted(planes.values(), key=lambda e: (_key(e["normal"], 6), round(e["offset"], 4))), 1):
        features.append({"id": f"plane_{number}", "kind": "plane_level", "normal": _key(entry["normal"], 9),
                         "offset": round(entry["offset"], 6)})
    return {"features": features, "other_surfaces": dict(sorted(other.items()))}


class _View:
    """A true-size view with a model projection: local = matrix * model point."""

    def __init__(self, view: dict, model: dict):
        self.id = view["id"]
        self.rows = [[float(c) for c in row] for row in view["projection"]["matrix"]]
        self.direction = _unit(_cross(self.rows[0], self.rows[1]))
        self.model = model["geometry"]
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


def _shows(feature: dict, view: _View, item: dict) -> bool:
    """True if the primitive is an edge of the feature in this view."""
    if feature["kind"] == "plane_level":
        if abs(_dot(feature["normal"], view.direction)) > PARALLEL or item["type"] != "line":
            return False
        # The plane is edge-on. Its trace is a line at its offset along the projected normal.
        normal = view.point(feature["normal"])
        return all(abs(_dot(normal, point) - feature["offset"]) <= POSITION_MM for point in (item["start"], item["end"]))
    along = abs(_dot(feature["axis"], view.direction))
    center = view.point(feature["foot"])
    if along >= 1 - PARALLEL:
        return (item["type"] in {"circle", "arc"} and math.dist(item["center"], center) <= POSITION_MM
                and abs(item["radius"] - feature["radius"]) <= RADIUS_MM)
    if along > PARALLEL or item["type"] != "line":
        return False
    # The axis is in the view plane. The outlines of the cylinder are lines parallel to the axis at the radius.
    axis = _unit(view.point(feature["axis"]))
    line = _unit([item["end"][0] - item["start"][0], item["end"][1] - item["start"][1], 0.0])
    if line is None or abs(_cross2(axis, line)) > PARALLEL:
        return False
    return abs(abs(_cross2(axis, [item["start"][0] - center[0], item["start"][1] - center[1]])) - feature["radius"]) <= POSITION_MM


def _measure_direction(dimension: dict) -> list[float] | None:
    axis = dimension.get("axis", "horizontal")
    if axis == "horizontal":
        return [1.0, 0.0]
    if axis == "vertical":
        return [0.0, 1.0]
    vector = _unit([dimension["p2"][0] - dimension["p1"][0], dimension["p2"][1] - dimension["p1"][1], 0.0])
    return None if vector is None else vector[:2]


def _sizes(feature: dict, view: _View, passed: set[str]) -> list[str]:
    """The passed dimensions of this view that give the diameter or the radius of a round feature."""
    found = []
    along = abs(_dot(feature["axis"], view.direction))
    center = view.point(feature["foot"])
    for dimension in view.dimensions:
        if dimension["id"] not in passed:
            continue
        if dimension["type"] in {"radius", "diameter"}:
            if (along >= 1 - PARALLEL and math.dist(dimension["center"], center) <= POSITION_MM
                    and abs(dimension["radius"] - feature["radius"]) <= RADIUS_MM):
                found.append(dimension["id"])
        elif dimension["type"] == "linear" and along <= PARALLEL:
            # A linear dimension across the axis, from one outline to the other.
            axis = _unit(view.point(feature["axis"]))
            measure = _measure_direction(dimension)
            if measure is None or abs(_dot(axis[:2], measure)) > PARALLEL:
                continue
            sides = [_cross2(axis, [point[0] - center[0], point[1] - center[1]]) for point in (dimension["p1"], dimension["p2"])]
            if all(abs(abs(side) - feature["radius"]) <= POSITION_MM for side in sides) and sides[0] * sides[1] < 0:
                found.append(dimension["id"])
    return found


def _directions(features: list[dict]) -> list[list[float]]:
    directions = {_key(axis, 6): list(axis) for axis in MODEL_AXES}
    for feature in features:
        if feature["kind"] == "plane_level":
            directions.setdefault(_key(feature["normal"], 6), list(feature["normal"]))
    return [directions[key] for key in sorted(directions)]


def _label(direction) -> str:
    return "[" + ", ".join(f"{c:.6g}" for c in (0.0 if abs(c) < 1e-12 else c for c in direction)) + "]"


def _positions(features: list[dict], views: list[_View], passed: set[str]) -> dict[str, dict[str, bool]]:
    """For each feature and each direction with more than one position: is the feature connected by dimensions?"""
    result: dict[str, dict[str, bool]] = {feature["id"]: {} for feature in features}
    for direction in _directions(features):
        # The nodes are the distinct coordinates along the direction. Coinciding features share a node.
        coordinates: list[tuple[float, str]] = []
        for feature in features:
            if feature["kind"] == "plane_level":
                if abs(_dot(feature["normal"], direction)) >= 1 - PARALLEL:
                    coordinates.append((feature["offset"] * (1 if _dot(feature["normal"], direction) > 0 else -1), feature["id"]))
            elif abs(_dot(feature["axis"], direction)) <= PARALLEL:
                coordinates.append((_dot(feature["foot"], direction), feature["id"]))
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

        def node(value):
            return next((index for index, (coordinate, _) in enumerate(nodes) if abs(coordinate - value) <= POSITION_MM), None)

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
                ends = [node(math.copysign(1, along) * _dot(measure, point)) for point in (dimension["p1"], dimension["p2"])]
                if None not in ends:
                    parent[root(ends[0])] = root(ends[1])
        groups: dict[int, list[int]] = {}
        for index in range(len(nodes)):
            groups.setdefault(root(index), []).append(index)
        # The reference is the connected group with the most features, and of equal groups the one with the lowest coordinate.
        reference = max(groups.values(), key=lambda members: (sum(len(nodes[index][1]) for index in members), -min(members)))
        for index, (_, identifiers) in enumerate(nodes):
            for identifier in identifiers:
                result[identifier][_label(direction)] = index in reference
    return result


def check(report, views: list[dict], derived: dict[str, dict], found: dict[str, Any], passed: set[str],
          markers: list[dict]) -> list[dict]:
    """Add FEAT-01 to FEAT-04 to the report and return the coverage of each feature."""
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
    coverage = []

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

    for feature in features:
        name = (f"{feature['kind']} {feature['id']} (radius {feature['radius']:g} mm, axis {_label(feature['axis'])})"
                if feature["kind"] != "plane_level" else f"plane level {feature['id']} (normal {_label(feature['normal'])}, offset {feature['offset']:g} mm)")
        visible = [view.id for view in usable if any(item["style"] in {"visible", "section"} and _shows(feature, view, item) for item in view.model)]
        hidden = [view.id for view in usable if any(item["style"] == "hidden" and _shows(feature, view, item) for item in view.model)]
        statuses = [add("FEAT-01", feature, bool(visible), f"The {name} is visible in {', '.join(visible) if visible else ''}.",
                        f"No true-size view shows the {name} with visible edges."
                        + (" Only hidden lines show it. Add a section or a view." if hidden else " Add a view or a section that shows it."),
                        {"visible_in": visible, "hidden_in": hidden})]
        sizes = None
        if feature["kind"] != "plane_level":
            sizes = [identifier for view in usable for identifier in _sizes(feature, view, passed)]
            statuses.append(add("FEAT-02", feature, bool(sizes), f"The {name} has the size dimension {', '.join(sizes)}.",
                                f"The {name} has no diameter or radius dimension that agrees with the bound model.", {"dimensions": sizes}))
        located = positions[feature["id"]]
        open_directions = [direction for direction, ok in located.items() if not ok]
        statuses.append(add("FEAT-03", feature, not open_directions,
                            f"The position of the {name} is connected to the other features by dimensions." if located else
                            f"The {name} is the only position along each checked direction.",
                            f"The position of the {name} has no dimension chain to the other features along {', '.join(open_directions)}.",
                            {"directions": located}))
        status = "fail" if "fail" in statuses else "needs_review" if "needs_review" in statuses else "pass"
        coverage.append({**feature, "visible_in": visible, "size_dimensions": sizes, "positions": located,
                         "markers": marked[feature["id"]], "status": status})
    if found["other_surfaces"]:
        listed = ", ".join(f"{count} {kind}" for kind, count in found["other_surfaces"].items())
        report.add("FEAT-04", "not_tested", "info", f"The feature inventory does not include these faces of the bound model: {listed}. "
                   "Their coverage is not tested.", observed=found["other_surfaces"])
    return coverage
