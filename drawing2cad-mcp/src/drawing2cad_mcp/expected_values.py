"""Independent expected volume and bounds for supported constant-section features.

This module does not import a CAD kernel. Exact results use planar boundary
integration in slabs perpendicular to the common feature axis.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .part_schema import FEATURE_COORDINATE_FRAMES, PartDescription, resolve


TAU = 2 * math.pi
EPS = 1e-9
MAX_EDGES = 4096
MAX_PAIRS = 100000
MAX_TOTAL_WORK = 1000000


class _Unavailable(ValueError):
    pass


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass(frozen=True)
class _Edge:
    kind: str
    start: tuple[float, float]
    end: tuple[float, float]
    center: tuple[float, float] | None = None
    radius: float = 0.0
    angle: float = 0.0
    sweep: float = 0.0

    def point(self, t):
        if self.kind == "line":
            return (self.start[0] + (self.end[0] - self.start[0]) * t,
                    self.start[1] + (self.end[1] - self.start[1]) * t)
        a = self.angle + self.sweep * t
        return self.center[0] + self.radius * math.cos(a), self.center[1] + self.radius * math.sin(a)

    def tangent(self, t):
        if self.kind == "line":
            return _sub(self.end, self.start)
        a = self.angle + self.sweep * t
        return (-self.radius * self.sweep * math.sin(a),
                self.radius * self.sweep * math.cos(a))

    def parameter(self, point):
        if self.kind == "line":
            d = _sub(self.end, self.start)
            return _dot(_sub(point, self.start), d) / _dot(d, d)
        a = math.atan2(point[1] - self.center[1], point[0] - self.center[0])
        delta = ((a - self.angle) % TAU) if self.sweep > 0 else -((self.angle - a) % TAU)
        return delta / self.sweep

    def integral(self, lo, hi):
        if self.kind == "line":
            return _cross(self.point(lo), self.point(hi))
        a, b = self.angle + self.sweep * lo, self.angle + self.sweep * hi
        cx, cy = self.center
        r = self.radius
        return r * (cx * (math.sin(b) - math.sin(a))
                    - cy * (math.cos(b) - math.cos(a)) + r * (b - a))


def _arc(start, middle, end):
    u, v = _sub(middle, start), _sub(end, start)
    determinant = 2 * _cross(u, v)
    scale = max(_dist(start, middle), _dist(middle, end), _dist(start, end))
    if scale <= EPS or abs(determinant) <= EPS * scale * scale:
        raise _Unavailable("The three-point arc is degenerate.")
    uu, vv = _dot(u, u), _dot(v, v)
    center = (start[0] + (uu * v[1] - vv * u[1]) / determinant,
              start[1] + (vv * u[0] - uu * v[0]) / determinant)
    radius = _dist(start, center)
    a = math.atan2(start[1] - center[1], start[0] - center[0])
    m = math.atan2(middle[1] - center[1], middle[0] - center[0])
    z = math.atan2(end[1] - center[1], end[0] - center[0])
    ccw = (z - a) % TAU
    sweep = ccw if (m - a) % TAU < ccw else ccw - TAU
    if abs(sweep) < EPS or abs(abs(sweep) - TAU) < EPS:
        raise _Unavailable("The three-point arc has an ambiguous sweep.")
    return _Edge("arc", start, end, center, radius, a, sweep)


def _circle(center, radius):
    return tuple(_Edge("arc",
                       (center[0] + radius * math.cos(i * math.pi / 2),
                        center[1] + radius * math.sin(i * math.pi / 2)),
                       (center[0] + radius * math.cos((i + 1) * math.pi / 2),
                        center[1] + radius * math.sin((i + 1) * math.pi / 2)),
                       center, radius, i * math.pi / 2, math.pi / 2)
                 for i in range(4))


def _polygon(points, budget):
    if len(points) < 3 or any(_dist(points[i], points[(i + 1) % len(points)]) <= EPS
                               for i in range(len(points))):
        raise _Unavailable("The profile contains a zero-length edge.")
    edges = tuple(_Edge("line", points[i], points[(i + 1) % len(points)])
                  for i in range(len(points)))
    _validate_contour(edges, budget)
    if abs(sum(edge.integral(0, 1) for edge in edges)) <= EPS:
        raise _Unavailable("The profile area is ambiguous.")
    return edges


def _profile(segments, point, budget):
    edges = []
    for segment in segments:
        start, end = point(segment.start), point(segment.end)
        if segment.kind == "line":
            if _dist(start, end) <= EPS:
                raise _Unavailable("The profile contains a zero-length edge.")
            edges.append(_Edge("line", start, end))
        else:
            edges.append(_arc(start, point(segment.mid), end))
    if any(_dist(edges[i].end, edges[(i + 1) % len(edges)].start) > EPS
           for i in range(len(edges))):
        raise _Unavailable("The profile is not closed.")
    _validate_contour(edges, budget)
    if abs(sum(edge.integral(0, 1) for edge in edges)) <= EPS:
        raise _Unavailable("The profile area is ambiguous.")
    return tuple(edges)


@dataclass(frozen=True)
class _Prism:
    add: bool
    low: float
    high: float
    edges: tuple[_Edge, ...]


def _make_prisms(feature, part, axis_index, current_bounds, budget):
    kind = feature.type
    if kind in {"chamfer", "fillet"}:
        raise _Unavailable(f"{kind} has no independent expected geometry rule.")
    if kind == "hole":
        if feature.style == "countersink" or feature.drill_angle is not None:
            raise _Unavailable("Conical countersinks and drill tips are unsupported.")
        origin = feature.position
        direction = feature.axis
        profiles = [("cylinder", feature.diameter, None)]
        if feature.style == "counterbore":
            profiles.append(("cylinder", feature.counter_diameter, feature.counter_depth))
        if feature.extent == "through":
            if current_bounds is None:
                raise _Unavailable("A through hole needs prior body bounds.")
            entry = resolve(origin[axis_index], part)
            endpoint = current_bounds[1][axis_index] if direction[0] != "-" else current_bounds[0][axis_index]
            depth = abs(endpoint - entry) + 1e-5
        else:
            depth = resolve(feature.depth, part)
        depths = [depth] + ([resolve(feature.counter_depth, part)] if len(profiles) > 1 else [])
        add = False
    elif kind == "box":
        origin = [resolve(value, part) for value in feature.origin]
        lengths = [resolve(feature.length, part), resolve(feature.width, part),
                   resolve(feature.height, part)]
        if any(length <= EPS for length in lengths):
            raise _Unavailable("The box dimensions are invalid.")
        transverse = [i for i in range(3) if i != axis_index]
        rectangle = [(origin[transverse[0]], origin[transverse[1]]),
                     (origin[transverse[0]] + lengths[transverse[0]], origin[transverse[1]]),
                     (origin[transverse[0]] + lengths[transverse[0]],
                      origin[transverse[1]] + lengths[transverse[1]]),
                     (origin[transverse[0]], origin[transverse[1]] + lengths[transverse[1]])]
        return [_Prism(True, origin[axis_index], origin[axis_index] + lengths[axis_index],
                       _polygon(rectangle, budget))]
    else:
        origin = feature.origin
        direction = getattr(feature, "axis", "Z")
        add = kind in {"box", "cylinder", "extrusion", "profile_extrusion"}
        profile = feature if add else feature.profile
        shape = kind if add else profile.shape
        if shape == "box":
            profiles = [("box", profile, None)]
        elif shape == "cylinder":
            profiles = [("cylinder", profile.diameter, None)]
        else:
            profiles = [(shape, profile, None)]
        depths = [resolve(feature.height if add else profile.depth, part)]
        if resolve(getattr(feature, "taper_angle", 0.0), part) != 0.0:
            raise _Unavailable("Tapered features are unsupported.")
    if direction[-1] != "XYZ"[axis_index]:
        raise _Unavailable("Non-parallel feature axes need a conservative bound.")
    frame = FEATURE_COORDINATE_FRAMES[direction]
    transverse = [i for i in range(3) if i != axis_index]
    o = [resolve(value, part) for value in origin]

    def point(local):
        return tuple(o[i] + local[0] * frame["local_x"][i]
                     + local[1] * frame["local_y"][i] for i in transverse)

    result = []
    for (shape, datum, _), depth in zip(profiles, depths):
        if depth <= EPS or not math.isfinite(depth):
            raise _Unavailable("The feature depth is invalid.")
        if shape == "box":
            length, width = resolve(datum.length, part), resolve(datum.width, part)
            edges = _polygon([point(p) for p in ((0, 0), (length, 0),
                                                  (length, width), (0, width))], budget)
        elif shape == "cylinder":
            radius = resolve(datum, part) / 2
            if radius <= EPS:
                raise _Unavailable("The circle radius is invalid.")
            edges = _circle(point((0, 0)), radius)
        elif shape in {"extrusion", "polygon"}:
            edges = _polygon([point(tuple(resolve(x, part) for x in p)) for p in datum.points], budget)
        elif shape in {"profile_extrusion", "profile"}:
            edges = _profile(datum.segments, lambda p: point(tuple(resolve(x, part) for x in p)), budget)
        else:
            raise _Unavailable(f"Unsupported profile: {shape}.")
        start = o[axis_index]
        end = start + frame["local_z"][axis_index] * depth
        result.append(_Prism(add, min(start, end), max(start, end), edges))
    return result


def _intersections(a, b):
    if a.kind == b.kind == "line":
        u, v = _sub(a.end, a.start), _sub(b.end, b.start)
        d = _cross(u, v)
        if abs(d) <= EPS * math.hypot(*u) * math.hypot(*v):
            if abs(_cross(_sub(b.start, a.start), u)) <= EPS * math.hypot(*u):
                return [p for p in (a.start, a.end, b.start, b.end)
                        if -EPS <= a.parameter(p) <= 1 + EPS
                        and -EPS <= b.parameter(p) <= 1 + EPS]
            return []
        t = _cross(_sub(b.start, a.start), v) / d
        s = _cross(_sub(b.start, a.start), u) / d
        return [a.point(t)] if -EPS <= t <= 1 + EPS and -EPS <= s <= 1 + EPS else []
    if a.kind == "arc" and b.kind == "line":
        a, b = b, a
    if a.kind == "line":
        d = _sub(a.end, a.start)
        f = _sub(a.start, b.center)
        aa, bb, cc = _dot(d, d), 2 * _dot(f, d), _dot(f, f) - b.radius**2
        discriminant = bb * bb - 4 * aa * cc
        if discriminant < -EPS * aa:
            return []
        return [a.point(t) for t in ((-bb - math.sqrt(max(0, discriminant))) / (2 * aa),
                                      (-bb + math.sqrt(max(0, discriminant))) / (2 * aa))
                if -EPS <= t <= 1 + EPS and -EPS <= b.parameter(a.point(t)) <= 1 + EPS]
    d = _dist(a.center, b.center)
    if d <= EPS and abs(a.radius - b.radius) <= EPS:
        return [p for p in (a.start, a.end, b.start, b.end)
                if -EPS <= a.parameter(p) <= 1 + EPS and -EPS <= b.parameter(p) <= 1 + EPS]
    if d <= EPS or d > a.radius + b.radius + EPS or d < abs(a.radius - b.radius) - EPS:
        return []
    along = (a.radius**2 - b.radius**2 + d**2) / (2 * d)
    h2 = a.radius**2 - along**2
    if h2 < -EPS:
        return []
    h = math.sqrt(max(0, h2))
    ux, uy = ((b.center[0] - a.center[0]) / d, (b.center[1] - a.center[1]) / d)
    base = a.center[0] + along * ux, a.center[1] + along * uy
    return [p for p in ((base[0] - h * uy, base[1] + h * ux),
                        (base[0] + h * uy, base[1] - h * ux))
            if -EPS <= a.parameter(p) <= 1 + EPS and -EPS <= b.parameter(p) <= 1 + EPS]


def _validate_contour(edges, budget):
    """Reject contour crossings before signed area can be used as solid area."""
    count = len(edges)
    pairs = count * (count - 1) // 2
    budget[0] += pairs
    if budget[0] > MAX_TOTAL_WORK:
        raise _Unavailable("The cumulative contour validation limit was exceeded.")
    for i, first in enumerate(edges):
        for j in range(i + 1, count):
            second = edges[j]
            adjacent = j == i + 1 or (i == 0 and j == count - 1)
            shared = ([first.end] if j == i + 1 else [])
            if i == 0 and j == count - 1:
                shared.append(second.end)
            for point in _intersections(first, second):
                if not adjacent or all(_dist(point, node) > 1e-7 for node in shared):
                    raise _Unavailable("The profile contour intersects itself.")


def _contains(edges, p):
    # Cast a horizontal ray. A half-open crossing rule avoids vertex counts.
    x, y = p
    count = 0
    for edge in edges:
        if edge.kind == "line":
            a, b = edge.start, edge.end
            if (a[1] <= y < b[1]) or (b[1] <= y < a[1]):
                hit = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                count += hit > x
        else:
            dy = y - edge.center[1]
            if abs(dy) >= edge.radius:
                continue
            dx = math.sqrt(max(0, edge.radius**2 - dy**2))
            for hit in (edge.center[0] - dx, edge.center[0] + dx):
                if hit <= x:
                    continue
                t = edge.parameter((hit, y))
                if 0 <= t < 1:
                    tangent = edge.tangent(t)
                    if abs(tangent[1]) > EPS:
                        count += 1
    return bool(count % 2)


def _occupies(active, point):
    inside = False
    for prism in active:
        if _contains(prism.edges, point):
            inside = prism.add if prism.add else False
    return inside


def _section(active):
    edges = [edge for prism in active for edge in prism.edges]
    if len(edges) > MAX_EDGES or len(edges) * (len(edges) - 1) // 2 > MAX_PAIRS:
        raise _Unavailable("The planar Boolean complexity limit was exceeded.")
    splits = [[0.0, 1.0] for _ in edges]
    for i, a in enumerate(edges):
        for j in range(i + 1, len(edges)):
            b = edges[j]
            if a.kind == b.kind == "line":
                u, v = _sub(a.end, a.start), _sub(b.end, b.start)
                if abs(_cross(u, v)) <= 1e-7 * math.hypot(*u) * math.hypot(*v):
                    distance = abs(_cross(_sub(b.start, a.start), u)) / math.hypot(*u)
                    if EPS < distance < 1e-6:
                        projections = sorted((0.0, 1.0))
                        other = sorted((a.parameter(b.start), a.parameter(b.end)))
                        if other[1] > projections[0] and other[0] < projections[1]:
                            raise _Unavailable("Near-coincident line boundaries are numerically ambiguous.")
            elif a.kind == b.kind == "arc":
                if _dist(a.center, b.center) <= EPS and EPS < abs(a.radius - b.radius) < 1e-6:
                    raise _Unavailable("Near-coincident arc boundaries are numerically ambiguous.")
            for point in _intersections(a, b):
                ta, tb = a.parameter(point), b.parameter(point)
                if EPS < ta < 1 - EPS:
                    splits[i].append(ta)
                if EPS < tb < 1 - EPS:
                    splits[j].append(tb)
    area2 = 0.0
    bounds = [[math.inf, math.inf], [-math.inf, -math.inf]]
    exposed = 0
    seen = set()
    for edge, params in zip(edges, splits):
        params.sort()
        for lo, hi in zip(params, params[1:]):
            if hi - lo <= EPS:
                continue
            mid = (lo + hi) / 2
            p = edge.point(mid)
            tangent = edge.tangent(mid)
            length = math.hypot(*tangent)
            offset = min(1e-6, max(1e-8, length * (hi - lo) * 1e-5))
            normal = (-tangent[1] / length, tangent[0] / length)
            left = _occupies(active, (p[0] + offset * normal[0], p[1] + offset * normal[1]))
            right = _occupies(active, (p[0] - offset * normal[0], p[1] - offset * normal[1]))
            wider = min(1e-5, offset * 4)
            if (left != _occupies(active, (p[0] + wider * normal[0], p[1] + wider * normal[1]))
                    or right != _occupies(active, (p[0] - wider * normal[0], p[1] - wider * normal[1]))):
                raise _Unavailable("Nearby boundaries make the planar Boolean ambiguous.")
            if left == right:
                continue
            ends = sorted((tuple(round(v, 8) for v in edge.point(lo)),
                           tuple(round(v, 8) for v in edge.point(hi))))
            key = (tuple(ends), tuple(round(v, 8) for v in p))
            if key in seen:
                continue
            seen.add(key)
            exposed += 1
            area2 += edge.integral(lo, hi) * (1 if left else -1)
            candidates = [lo, hi]
            if edge.kind == "arc":
                first_angle = edge.angle + edge.sweep * lo
                last_angle = edge.angle + edge.sweep * hi
                first_cardinal = math.ceil(min(first_angle, last_angle) / (math.pi / 2))
                last_cardinal = math.floor(max(first_angle, last_angle) / (math.pi / 2))
                for cardinal in range(first_cardinal, last_cardinal + 1):
                    t = (cardinal * math.pi / 2 - edge.angle) / edge.sweep
                    if lo < t < hi:
                        candidates.append(t)
            for t in candidates:
                q = edge.point(t)
                for k in range(2):
                    bounds[0][k] = min(bounds[0][k], q[k])
                    bounds[1][k] = max(bounds[1][k], q[k])
    area = area2 / 2
    if exposed and (area <= EPS or not math.isfinite(area)):
        raise _Unavailable("The planar Boolean has ambiguous area.")
    return max(0.0, area), bounds if exposed else None


def _exact(prisms, axis_index):
    stations = sorted({value for prism in prisms for value in (prism.low, prism.high)})
    volume = 0.0
    xyz_min, xyz_max = [math.inf] * 3, [-math.inf] * 3
    transverse = [i for i in range(3) if i != axis_index]
    occupied = False
    for low, high in zip(stations, stations[1:]):
        if high - low <= EPS:
            continue
        middle = (low + high) / 2
        active = [p for p in prisms if p.low < middle < p.high]
        area, bounds = _section(active)
        if area <= EPS:
            continue
        occupied = True
        volume += area * (high - low)
        xyz_min[axis_index] = min(xyz_min[axis_index], low)
        xyz_max[axis_index] = max(xyz_max[axis_index], high)
        for k, index in enumerate(transverse):
            xyz_min[index] = min(xyz_min[index], bounds[0][k])
            xyz_max[index] = max(xyz_max[index], bounds[1][k])
    if not occupied:
        raise _Unavailable("The ordered features leave no material.")
    return volume, (xyz_min, xyz_max)


def _bbox(bounds):
    low, high = bounds
    return {"kind": "exact", "min": low, "max": high,
            "size": [high[i] - low[i] for i in range(3)]}


def _bound_bbox(bounds, reason):
    low, high = bounds
    return {"kind": "bound", "lower": [0.0, 0.0, 0.0],
            "upper": [high[i] - low[i] for i in range(3)],
            "min": low, "max": high, "reason": reason}


def _envelope(a, b):
    return ([min(a[0][i], b[0][i]) for i in range(3)],
            [max(a[1][i], b[1][i]) for i in range(3)])


def _tool_measure(feature, part, current_bounds, budget):
    direction = feature.axis if hasattr(feature, "axis") else "Z"
    index = "XYZ".index(direction[-1])
    tools = _make_prisms(feature, part, index, current_bounds, budget)
    positive = [_Prism(True, p.low, p.high, p.edges) for p in tools]
    if len(positive) == 1:
        prism = positive[0]
        area = abs(sum(edge.integral(0, 1) for edge in prism.edges)) / 2
        if area <= EPS:
            raise _Unavailable("The tool profile area is ambiguous.")
        transverse = [i for i in range(3) if i != index]
        low, high = [math.inf] * 3, [-math.inf] * 3
        low[index], high[index] = prism.low, prism.high
        for edge in prism.edges:
            candidates = [0.0, 1.0]
            if edge.kind == "arc":
                first = math.ceil(min(edge.angle, edge.angle + edge.sweep) / (math.pi / 2))
                last = math.floor(max(edge.angle, edge.angle + edge.sweep) / (math.pi / 2))
                candidates.extend((i * math.pi / 2 - edge.angle) / edge.sweep
                                  for i in range(first, last + 1))
            for t in candidates:
                if -EPS <= t <= 1 + EPS:
                    point = edge.point(min(1.0, max(0.0, t)))
                    for k, coordinate in enumerate(transverse):
                        low[coordinate] = min(low[coordinate], point[k])
                        high[coordinate] = max(high[coordinate], point[k])
        return area * (prism.high - prism.low), (low, high)
    return _exact(positive, index)


def _bound_step(feature, part, volume_interval, bounds, reason, budget):
    tool_volume, tool_bounds = _tool_measure(feature, part, bounds, budget)
    lower, upper = volume_interval
    if feature.type in {"box", "cylinder", "extrusion", "profile_extrusion"}:
        lower = max(lower, tool_volume)
        upper += tool_volume
        bounds = _envelope(bounds, tool_bounds)
    else:
        lower = max(0.0, lower - tool_volume)
    return (lower, upper), bounds, {
        "volume": {"kind": "bound", "lower": lower, "upper": upper, "reason": reason},
        "bbox": _bound_bbox(bounds, reason),
    }


def compute_expected(part: PartDescription) -> dict:
    """Compute cumulative expected values for an already validated description.

    Exact values require supported constant-section features with parallel axes.
    Once an unsupported operation appears, subsequent values remain unavailable.
    """
    if not isinstance(part, PartDescription):
        raise TypeError("compute_expected requires a validated PartDescription.")
    rows = []
    prisms = []
    first_axial = next((feature.axis for feature in part.features
                        if feature.type not in {"box", "chamfer", "fillet"}
                        and hasattr(feature, "axis")), "Z")
    axis_index = "XYZ".index(first_axial[-1])
    prior_bounds = None
    unavailable = None
    bound_reason = None
    volume_interval = None
    total_work = 0
    contour_budget = [0]
    for feature in part.features:
        if unavailable is None:
            try:
                feature_axis = feature.axis if hasattr(feature, "axis") else "Z"
                if feature.type == "box":
                    feature_axis = "Z"
                if feature.type in {"chamfer", "fillet"}:
                    raise _Unavailable(f"{feature.type} has no independent expected geometry rule.")
                current_index = "XYZ".index(feature_axis[-1])
                if bound_reason is None and feature.type != "box" and current_index != axis_index:
                    bound_reason = (f"{feature.id}: Non-parallel feature axes prevent "
                                    "exact Boolean volume.")
                    volume_interval = (rows[-1]["volume"]["value"],
                                       rows[-1]["volume"]["value"])
                if bound_reason is not None:
                    volume_interval, prior_bounds, values = _bound_step(
                        feature, part, volume_interval, prior_bounds, bound_reason,
                        contour_budget)
                else:
                    additions = _make_prisms(feature, part, axis_index, prior_bounds,
                                             contour_budget)
                    candidate = prisms + additions
                    edge_count = sum(len(p.edges) for p in candidate)
                    station_count = len({v for p in candidate for v in (p.low, p.high)})
                    total_work += edge_count**3 * max(1, station_count - 1)
                    if total_work > MAX_TOTAL_WORK:
                        if not rows:
                            raise _Unavailable("The cumulative planar Boolean work limit was exceeded.")
                        bound_reason = (f"{feature.id}: The cumulative planar Boolean "
                                        "work limit was exceeded.")
                        volume_interval = (rows[-1]["volume"]["value"],
                                           rows[-1]["volume"]["value"])
                        volume_interval, prior_bounds, values = _bound_step(
                            feature, part, volume_interval, prior_bounds, bound_reason,
                            contour_budget)
                    else:
                        volume, bounds = _exact(candidate, axis_index)
                        prisms = candidate
                        prior_bounds = bounds
                        values = {"volume": {"kind": "exact", "value": volume},
                                  "bbox": _bbox(bounds)}
            except (ValueError, ArithmeticError, OverflowError) as error:
                unavailable = f"{feature.id}: {str(error) or 'The geometry could not be evaluated safely.'}"
        if unavailable is not None:
            values = {"volume": {"reason": unavailable}, "bbox": {"reason": unavailable}}
        rows.append({"feature_id": feature.id, **values})
    return {"features": rows, "final": rows[-1].copy()}
