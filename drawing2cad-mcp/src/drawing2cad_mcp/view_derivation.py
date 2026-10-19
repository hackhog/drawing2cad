"""Derive orthographic, isometric, and section views from a validated STEP candidate.

This module runs in the restricted CAD worker. It reads only the files in its work directory.
Local view coordinates are the projection matrix applied to model coordinates: local = matrix * model point.
The output primitives use the DrawingSpec 2.0 types without evidence and feature references. The service adds them.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .derived_views import MAX_PRIMITIVES_PER_VIEW

# A projected edge shorter than this is noise of the hidden-line removal.
MIN_EDGE_MM = 1e-6
# Chord tolerance for curves that are not lines, circles, or ellipses.
CURVE_TOLERANCE_MM = 0.01
MAX_CURVE_SAMPLES = 400
# Center lines extend past the feature by this length (ISO 128-2 recommends a short extension).
CENTER_EXTENSION_MM = 2.0
# The cutting line extends past the part outline by this length.
CUTTING_EXTENSION_MM = 5.0
COINCIDENCE_MM = 1e-4


def _round(values):
    return [round(float(v), 6) for v in values]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


class _Projector:
    def __init__(self, projection: dict[str, Any]):
        self.matrix = [[float(c) for c in row] for row in projection["matrix"]]
        self.view = [float(c) for c in projection["view_direction"]]
        length = math.sqrt(_dot(self.view, self.view))
        self.view = [c / length for c in self.view]
        self.factor = math.sqrt(_dot(self.matrix[0], self.matrix[0]))
        self.right = [c / self.factor for c in self.matrix[0]]

    def point(self, p) -> list[float]:
        return [_dot(self.matrix[0], p), _dot(self.matrix[1], p)]


def _angle(center, point) -> float:
    return math.degrees(math.atan2(point[1] - center[1], point[0] - center[0])) % 360


def _ccw(start: float, end: float, middle: float) -> tuple[float, float]:
    """Order two angles so that the counterclockwise sweep from the first to the second contains middle."""
    if (middle - start) % 360 <= (end - start) % 360:
        return start, end
    return end, start


class _Converter:
    """Convert edges to DrawingSpec primitives. Record the approximation error of sampled curves."""

    def __init__(self, view_id: str):
        self.view_id = view_id
        self.counts: dict[str, int] = {}
        self.primitives: list[dict] = []
        self.approximations: list[dict] = []

    def _id(self, prefix: str) -> str:
        self.counts[prefix] = self.counts.get(prefix, 0) + 1
        return f"{self.view_id}_{prefix}{self.counts[prefix]}"

    def add(self, primitive: dict, prefix: str) -> dict:
        if len(self.primitives) >= MAX_PRIMITIVES_PER_VIEW:
            raise _TooComplex(self.view_id)
        primitive = {"id": self._id(prefix), **primitive}
        self.primitives.append(primitive)
        return primitive

    def line(self, start, end, style, prefix) -> dict | None:
        if math.dist(start, end) <= MIN_EDGE_MM:
            return None
        return self.add({"type": "line", "start": _round(start), "end": _round(end), "style": style}, prefix)

    def edge(self, adaptor, to_2d, scale: float, style: str, prefix: str, planar_3d: bool) -> list[dict]:
        """Convert one edge. to_2d maps a curve point to local view coordinates.

        planar_3d is true for a 3D edge in a plane perpendicular to the view direction (a section face).
        It is false for an edge from the hidden-line removal, which is already in the view plane.
        """
        from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Ellipse, GeomAbs_Line

        first, last = adaptor.FirstParameter(), adaptor.LastParameter()

        def value(t):
            p = adaptor.Value(t)
            return to_2d((p.X(), p.Y(), p.Z()))

        kind = adaptor.GetType()
        closed = abs((last - first) - 2 * math.pi) <= 1e-9
        start, end, middle = value(first), value(last), value((first + last) / 2)
        if kind == GeomAbs_Line:
            item = self.line(start, end, style, prefix)
            return [item] if item else []
        if kind == GeomAbs_Circle:
            circle = adaptor.Circle()
            location = circle.Location()
            center = to_2d((location.X(), location.Y(), location.Z()))
            radius = circle.Radius() * scale
            if radius > MIN_EDGE_MM:
                if closed:
                    return [self.add({"type": "circle", "center": _round(center), "radius": round(radius, 6), "style": style}, prefix)]
                a, b = _ccw(_angle(center, start), _angle(center, end), _angle(center, middle))
                return [self.add({"type": "arc", "center": _round(center), "radius": round(radius, 6),
                                  "start_angle": round(a, 6), "end_angle": round(b, 6), "style": style}, prefix)]
        if kind == GeomAbs_Ellipse and not planar_3d:
            ellipse = adaptor.Ellipse()
            location = ellipse.Location()
            axis = ellipse.XAxis().Direction()
            center = to_2d((location.X(), location.Y(), location.Z()))
            major = [axis.X() * ellipse.MajorRadius() * scale, axis.Y() * ellipse.MajorRadius() * scale]
            a = math.hypot(*major)
            ratio = ellipse.MinorRadius() / ellipse.MajorRadius()
            if a > MIN_EDGE_MM and ratio > 1e-6:
                unit = [major[0] / a, major[1] / a]
                normal = [-unit[1], unit[0]]

                def parameter(point):
                    d = [point[0] - center[0], point[1] - center[1]]
                    return math.degrees(math.atan2(_dot(d, normal) / (a * ratio), _dot(d, unit) / a)) % 360

                if closed:
                    start_parameter, end_parameter = 0.0, 360.0
                else:
                    start_parameter, end_parameter = _ccw(parameter(start), parameter(end), parameter(middle))
                    if end_parameter <= start_parameter:
                        end_parameter += 360.0
                return [self.add({"type": "ellipse", "center": _round(center), "major_axis": _round(major), "ratio": round(min(ratio, 1.0), 9),
                                  "start_parameter": round(start_parameter, 6), "end_parameter": round(end_parameter, 6),
                                  "approximation_error": 0.0, "style": style}, prefix)]
        return self._sampled(value, first, last, style, prefix, adaptor)

    def _sampled(self, value, first, last, style, prefix, adaptor) -> list[dict]:
        from OCP.GCPnts import GCPnts_AbscissaPoint

        length = GCPnts_AbscissaPoint.Length_s(adaptor)
        count = max(8, min(MAX_CURVE_SAMPLES, math.ceil(length / 0.05)))
        dense = [value(first + (last - first) * i / count) for i in range(count + 1)]
        kept = _simplify(dense, CURVE_TOLERANCE_MM)
        items = [item for item in (self.line(kept[i], kept[i + 1], style, prefix) for i in range(len(kept) - 1)) if item]
        if items:
            error = max(_polyline_distance(point, kept) for point in dense)
            self.approximations.append({"primitive_ids": [item["id"] for item in items], "max_error_mm": round(error, 6),
                                        "method": "polyline"})
        return items


class _TooComplex(Exception):
    def __init__(self, view_id):
        super().__init__(view_id)
        self.view_id = view_id


def _segment_distance(point, a, b) -> float:
    d = [b[0] - a[0], b[1] - a[1]]
    length = _dot(d, d)
    t = 0.0 if length <= 0 else max(0.0, min(1.0, ((point[0] - a[0]) * d[0] + (point[1] - a[1]) * d[1]) / length))
    return math.dist(point, [a[0] + t * d[0], a[1] + t * d[1]])


def _polyline_distance(point, polyline) -> float:
    return min(_segment_distance(point, polyline[i], polyline[i + 1]) for i in range(len(polyline) - 1))


def _simplify(points, tolerance):
    """Douglas-Peucker simplification. Keep the end points."""
    if len(points) <= 2:
        return points
    worst, index = 0.0, 0
    for i in range(1, len(points) - 1):
        distance = _segment_distance(points[i], points[0], points[-1])
        if distance > worst:
            worst, index = distance, i
    if worst <= tolerance:
        return [points[0], points[-1]]
    return _simplify(points[:index + 1], tolerance)[:-1] + _simplify(points[index:], tolerance)


def _primitive_distance(point, item) -> float:
    if item["type"] == "line":
        return _segment_distance(point, item["start"], item["end"])
    if item["type"] in {"circle", "arc"}:
        radial = abs(math.dist(point, item["center"]) - item["radius"])
        if item["type"] == "circle":
            return radial
        angle = _angle(item["center"], point)
        if (angle - item["start_angle"]) % 360 <= (item["end_angle"] - item["start_angle"]) % 360 + 1e-6:
            return radial
    return math.inf


def _sample(item) -> list[list[float]]:
    if item["type"] == "line":
        return [item["start"], [(item["start"][0] + item["end"][0]) / 2, (item["start"][1] + item["end"][1]) / 2], item["end"]]
    if item["type"] == "circle":
        return [[item["center"][0] + item["radius"] * math.cos(a), item["center"][1] + item["radius"] * math.sin(a)]
                for a in (0.3, 2.4, 4.5)]
    if item["type"] == "arc":
        sweep = (item["end_angle"] - item["start_angle"]) % 360 or 360
        return [[item["center"][0] + item["radius"] * math.cos(math.radians(item["start_angle"] + sweep * f)),
                 item["center"][1] + item["radius"] * math.sin(math.radians(item["start_angle"] + sweep * f))] for f in (0.0, 0.5, 1.0)]
    return []


def _hidden_line_edges(shape, projector: _Projector, converter: _Converter, hidden: bool, skip=()) -> None:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepLib import BRepLib
    from OCP.HLRAlgo import HLRAlgo_Projector
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    algorithm = HLRBRep_Algo()
    algorithm.Add(shape.wrapped)
    # X of the projector frame is the screen right direction, and Y = view x right is the screen up direction.
    frame = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*projector.view), gp_Dir(*projector.right))
    algorithm.Projector(HLRAlgo_Projector(frame))
    algorithm.Update()
    algorithm.Hide()
    shapes = HLRBRep_HLRToShape(algorithm)
    groups = [("visible", "v", (shapes.VCompound(), shapes.OutLineVCompound()))]
    if hidden:
        groups.append(("hidden", "h", (shapes.HCompound(), shapes.OutLineHCompound())))

    def to_2d(p):
        return [projector.factor * p[0], projector.factor * p[1]]

    for style, prefix, compounds in groups:
        for compound in compounds:
            if compound.IsNull():
                continue
            explorer = TopExp_Explorer(compound, TopAbs_EDGE)
            while explorer.More():
                edge = TopoDS.Edge(explorer.Current())
                BRepLib.BuildCurves3d_s(edge, 1e-6)
                before = len(converter.primitives)
                converter.edge(BRepAdaptor_Curve(edge), to_2d, projector.factor, style, prefix, planar_3d=False)
                if skip:
                    for item in converter.primitives[before:]:
                        points = _sample(item)
                        if points and all(min(_primitive_distance(p, other) for other in skip) <= COINCIDENCE_MM for p in points):
                            converter.primitives.remove(item)
                explorer.Next()


def _center_lines(shape, projector: _Projector, converter: _Converter) -> None:
    """Center lines of cylindrical faces whose axis is in the view plane, and center marks of axes along the view direction."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.TopAbs import TopAbs_FACE, TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    axes: dict[tuple, dict] = {}
    faces = TopExp_Explorer(shape.wrapped, TopAbs_FACE)
    while faces.More():
        face = TopoDS.Face(faces.Current())
        faces.Next()
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() != GeomAbs_Cylinder:
            continue
        cylinder = surface.Cylinder()
        axis = cylinder.Axis()
        direction = [axis.Direction().X(), axis.Direction().Y(), axis.Direction().Z()]
        if max(direction, key=abs) < 0:
            direction = [-c for c in direction]
        location = [axis.Location().X(), axis.Location().Y(), axis.Location().Z()]
        # A point of the axis that does not depend on the location along the axis.
        foot = [location[i] - _dot(location, direction) * direction[i] for i in range(3)]
        key = tuple(round(c, 5) for c in direction + foot)
        vertices = TopExp_Explorer(face, TopAbs_VERTEX)
        parameters = []
        while vertices.More():
            point = BRep_Tool.Pnt_s(TopoDS.Vertex(vertices.Current()))
            parameters.append(_dot([point.X() - foot[0], point.Y() - foot[1], point.Z() - foot[2]], direction))
            vertices.Next()
        if not parameters:
            continue
        entry = axes.setdefault(key, {"direction": direction, "foot": foot, "low": min(parameters), "high": max(parameters), "radius": 0.0})
        entry.update(low=min(entry["low"], *parameters), high=max(entry["high"], *parameters), radius=max(entry["radius"], cylinder.Radius()))
    marks: dict[tuple, float] = {}
    for entry in axes.values():
        along = abs(_dot(entry["direction"], projector.view))
        if along <= 1e-6:
            ends = [[entry["foot"][i] + t * entry["direction"][i] for i in range(3)]
                    for t in (entry["low"] - CENTER_EXTENSION_MM, entry["high"] + CENTER_EXTENSION_MM)]
            converter.line(projector.point(ends[0]), projector.point(ends[1]), "center", "c")
        elif along >= 1 - 1e-6:
            center = tuple(round(c, 6) for c in projector.point(entry["foot"]))
            marks[center] = max(marks.get(center, 0.0), entry["radius"])
    for center, radius in sorted(marks.items()):
        half = projector.factor * radius + CENTER_EXTENSION_MM
        converter.line([center[0] - half, center[1]], [center[0] + half, center[1]], "center", "c")
        converter.line([center[0], center[1] - half], [center[0], center[1] + half], "center", "c")


def _section(shape, view: dict, projector: _Projector, converter: _Converter) -> tuple[Any, list[dict]]:
    """Remove the material between the viewer and the cutting plane. Return the kept part and the hatching."""
    from build123d import Keep, Plane
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    plane = view["cutting_plane"]
    origin = [float(c) for c in plane["origin"]]
    kept = shape.split(Plane(origin=tuple(origin), z_dir=tuple(projector.view)), keep=Keep.BOTTOM)
    if kept is None or not kept.faces():
        raise ValueError(f"View {view['id']}: the cutting plane does not cut the part.")
    hatching = []
    for face in kept.faces():
        if face.geom_type.name != "PLANE":
            continue
        normal = face.normal_at()
        center = face.center()
        if abs(abs(_dot((normal.X, normal.Y, normal.Z), projector.view)) - 1) > 1e-9:
            continue
        if abs(_dot([center.X - origin[0], center.Y - origin[1], center.Z - origin[2]], projector.view)) > 1e-6:
            continue
        ids = []
        for edge in face.edges():
            ids += [item["id"] for item in converter.edge(BRepAdaptor_Curve(edge.wrapped), projector.point, projector.factor,
                                                         "section", "s", planar_3d=True)]
        if ids:
            hatching.append({"boundary_primitive_ids": ids, "pattern": "iso_lines", "angle": 45.0, "spacing": 3.0})
    if not hatching:
        raise ValueError(f"View {view['id']}: the cutting plane gives no cut surface.")
    return kept, hatching


def _cutting_line(shape, view: dict) -> list[list[float]]:
    """The trace of the cutting plane in its source view, past the part outline on both sides."""
    source = _Projector(view["source_projection"])
    plane = view["cutting_plane"]
    normal = source.point([float(c) for c in plane["normal"]])
    length = math.hypot(*normal)
    direction = [-normal[1] / length, normal[0] / length]
    base = source.point([float(c) for c in plane["origin"]])
    box = shape.bounding_box()
    corners = [(x, y, z) for x in (box.min.X, box.max.X) for y in (box.min.Y, box.max.Y) for z in (box.min.Z, box.max.Z)]
    offsets = [_dot([p[0] - base[0], p[1] - base[1]], direction) for p in (source.point(c) for c in corners)]
    low, high = min(offsets) - CUTTING_EXTENSION_MM, max(offsets) + CUTTING_EXTENSION_MM
    return [_round([base[0] + low * direction[0], base[1] + low * direction[1]]),
            _round([base[0] + high * direction[0], base[1] + high * direction[1]])]


def derive(step_path: Path, views: list[dict]) -> dict[str, Any]:
    """Derive each requested view. The requests come from derived_views.normalize_requests."""
    from build123d import import_step

    from .drawing_contract import _bounds

    shape = import_step(str(step_path))
    results = []
    try:
        for view in views:
            projector = _Projector(view["projection"])
            converter = _Converter(view["id"])
            hatching, cutting_plane, part = [], None, shape
            if view["kind"] == "section":
                part, hatching = _section(shape, view, projector, converter)
                cutting_plane = {key: view["cutting_plane"][key] for key in ("letter", "origin", "normal", "viewing_side", "source_view_id")}
                cutting_plane["line"] = _cutting_line(shape, view)
            boundary = [item for item in converter.primitives if item["style"] == "section"]
            _hidden_line_edges(part, projector, converter, view["hidden_lines"], skip=boundary)
            if view["kind"] != "isometric":
                _center_lines(part, projector, converter)
            boxes = [_bounds(item) for item in converter.primitives]
            results.append({"id": view["id"], "kind": view["kind"], "projection": view["projection"],
                            "geometry": converter.primitives, "hatching": hatching, "cutting_plane": cutting_plane,
                            "bounds": _round([min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)])
                            if boxes else None,
                            "approximations": converter.approximations,
                            "counts": {style: sum(1 for item in converter.primitives if item["style"] == style)
                                       for style in ("visible", "hidden", "center", "section")}})
    except _TooComplex as error:
        return {"status": "fail", "error": {"code": "VIEW_TOO_COMPLEX",
                                            "message": f"View {error.view_id} exceeds {MAX_PRIMITIVES_PER_VIEW} primitives."}}
    except ValueError as error:
        return {"status": "fail", "error": {"code": "INVALID_VIEW", "message": str(error)}}
    return {"status": "pass", "views": results}
