"""Feature coverage of a drawing: the feature inventory of the bound STEP and the rules FEAT-01 to FEAT-03."""

import math

import pytest

from drawing2cad_mcp.feature_coverage import check, inventory
from drawing2cad_mcp.pdf_verifier import Report

TOP = {"scale_convention": "true_size", "matrix": [[1, 0, 0], [0, 1, 0]]}
FRONT = {"scale_convention": "true_size", "matrix": [[1, 0, 0], [0, 0, 1]]}


def line(identifier, start, end, style="visible"):
    return {"id": identifier, "type": "line", "style": style, "start": start, "end": end}


def circle(identifier, center, radius, style="visible"):
    return {"id": identifier, "type": "circle", "style": style, "center": center, "radius": radius}


def linear(identifier, p1, p2, axis):
    return {"id": identifier, "type": "linear", "axis": axis, "p1": p1, "p2": p2}


def view(identifier, projection, dimensions, geometry=()):
    return {"id": identifier, "kind": "orthographic", "projection": projection, "geometry": list(geometry), "dimensions": dimensions}


# A plate 40 x 20 x 10 with a hole of 6 mm at (10, 10). The bottom view sees the plate face-on; the front view sees it edge-on.
def level(identifier, normal, offset, low, high):
    # One rectangular face: its corners are its boundary points.
    corners = [[x, y, z] for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
    return {"id": identifier, "kind": "plane_level", "normal": normal, "offset": offset, "inclined": False, "faces": [corners]}


PLATE = {"features": [
    {"id": "round_1", "kind": "hole", "axis": (0.0, 0.0, 1.0), "foot": (10.0, 10.0, 0.0), "radius": 3.0, "extent": [0.0, 10.0]},
    level("plane_1", (1.0, 0.0, 0.0), 0.0, [0, 0, 0], [0, 20, 10]), level("plane_2", (1.0, 0.0, 0.0), 40.0, [40, 0, 0], [40, 20, 10]),
    level("plane_3", (0.0, 1.0, 0.0), 0.0, [0, 0, 0], [40, 0, 10]), level("plane_4", (0.0, 1.0, 0.0), 20.0, [0, 20, 0], [40, 20, 10]),
    level("plane_5", (0.0, 0.0, 1.0), 0.0, [0, 0, 0], [40, 20, 0]), level("plane_6", (0.0, 0.0, 1.0), 10.0, [0, 0, 10], [40, 20, 10])]}
TOP_MODEL = [line("t1", [0, 0], [40, 0]), line("t2", [40, 0], [40, 20]), line("t3", [40, 20], [0, 20]), line("t4", [0, 20], [0, 0]),
             circle("hole", [10, 10], 3)]
# The front view: the plate outline and the hole as hidden lines at x = 7 and x = 13.
FRONT_MODEL = [line("f1", [0, 0], [40, 0]), line("f2", [40, 0], [40, 10]), line("f3", [40, 10], [0, 10]), line("f4", [0, 10], [0, 0]),
               line("h1", [7, 0], [7, 10], "hidden"), line("h2", [13, 0], [13, 10], "hidden")]
COMPLETE = {"top": [linear("w", [0, 10], [40, 10], "horizontal"), linear("d", [20, 0], [20, 20], "vertical"),
                    linear("hx", [0, 5], [10, 10], "horizontal"), linear("hy", [5, 0], [10, 10], "vertical"),
                    {"id": "hd", "type": "diameter", "center": [10, 10], "radius": 3}],
            "front": [linear("t", [30, 0], [30, 10], "vertical")]}


def coverage(dimensions, *, passed=None, markers=(), derived=None, features=PLATE):
    views = [view("top", TOP, dimensions["top"], TOP_MODEL), view("front", FRONT, dimensions["front"], FRONT_MODEL)]
    derived = derived or {"top": {"geometry": TOP_MODEL}, "front": {"geometry": FRONT_MODEL}}
    identifiers = {item["id"] for items in dimensions.values() for item in items}
    report = Report()
    result = check(report, views, derived, features, identifiers if passed is None else passed, list(markers))
    findings = {(item["rule_id"], item["feature"]): item for item in report.findings}
    return {item["id"]: item for item in result}, findings


def test_a_completely_dimensioned_plate_passes_each_feature():
    result, findings = coverage(COMPLETE)
    assert all(item["status"] == "pass" for item in result.values()), [(key, item["message"]) for key, item in findings.items()
                                                                     if item["status"] != "pass"]
    assert result["round_1"]["visible_in"] == ["top"] and result["round_1"]["size_dimensions"] == ["hd"]
    assert result["round_1"]["positions"] == {"[1, 0, 0]": True, "[0, 1, 0]": True}
    assert result["plane_6"]["visible_in"] == ["front"] and result["plane_6"]["size_dimensions"] is None


def test_missing_size_position_and_thickness_fail():
    dimensions = {"top": [item for item in COMPLETE["top"] if item["id"] not in {"hd", "hx"}], "front": []}
    result, findings = coverage(dimensions)
    assert findings[("FEAT-02", "round_1")]["status"] == "fail"
    # Without hx, the hole position along X has no dimension chain to the plate faces.
    assert findings[("FEAT-03", "round_1")]["status"] == "fail" and "[1, 0, 0]" in findings[("FEAT-03", "round_1")]["message"]
    assert result["round_1"]["positions"]["[0, 1, 0]"] is True
    # Without t, one of the two plate faces along Z is not connected. The lower one is the reference of equal groups.
    assert findings[("FEAT-03", "plane_6")]["status"] == "fail" and findings[("FEAT-03", "plane_5")]["status"] == "pass"


def test_a_dimension_that_failed_its_value_check_does_not_count():
    passed = {item["id"] for items in COMPLETE.values() for item in items} - {"t", "hd"}
    _, findings = coverage(COMPLETE, passed=passed)
    assert findings[("FEAT-02", "round_1")]["status"] == "fail" and findings[("FEAT-03", "plane_6")]["status"] == "fail"


def test_a_linear_dimension_across_the_outlines_gives_the_size():
    dimensions = {"top": [item for item in COMPLETE["top"] if item["id"] != "hd"],
                  "front": COMPLETE["front"] + [linear("hd_front", [7, 4], [13, 4], "horizontal")]}
    # The outlines are visible in a section through the hole axis.
    front = [item if not item["id"].startswith("h") else {**item, "style": "section"} for item in FRONT_MODEL]
    cut = {"origin": [0, 10, 0], "normal": [0, 1, 0]}
    result, _ = coverage(dimensions, derived={"top": {"geometry": TOP_MODEL}, "front": {"geometry": front, "cutting_plane": cut}})
    assert result["round_1"]["size_dimensions"] == ["hd_front"]


def test_a_feature_that_only_hidden_lines_show_fails_and_a_marker_makes_it_a_review_item():
    # Without the top view, only the hidden lines of the front view show the hole.
    dimensions = {"top": [], "front": COMPLETE["front"]}
    derived = {"front": {"geometry": FRONT_MODEL}}
    _, findings = coverage(dimensions, derived=derived)
    assert findings[("FEAT-01", "round_1")]["status"] == "fail" and "Only hidden lines" in findings[("FEAT-01", "round_1")]["message"]
    _, findings = coverage(dimensions, derived=derived, markers=[{"id": "m1", "view_id": "front", "primitive_id": "h1"}])
    assert findings[("FEAT-01", "round_1")]["status"] == "needs_review" and "m1" in findings[("FEAT-01", "round_1")]["message"]


def test_an_edge_outside_the_extent_of_a_feature_does_not_count():
    # A visible line at the hole outline, but above the plate (z = 20..30), is the edge of another feature.
    front = FRONT_MODEL + [line("other", [7, 20], [7, 30])]
    _, findings = coverage({"top": [], "front": COMPLETE["front"]}, derived={"front": {"geometry": front}})
    assert findings[("FEAT-01", "round_1")]["status"] == "fail"
    # A line at the height of the plate face, but beside the plate, does not show the face. A dimension to it does not locate the face.
    front = [item for item in FRONT_MODEL if item["id"] != "f3"] + [line("rib", [50, 10], [60, 10])]
    dimensions = {"top": COMPLETE["top"], "front": [linear("t", [55, 0], [55, 10], "vertical")]}
    _, findings = coverage(dimensions, derived={"top": {"geometry": TOP_MODEL}, "front": {"geometry": front}})
    assert findings[("FEAT-01", "plane_6")]["status"] == "fail" and findings[("FEAT-03", "plane_6")]["status"] == "fail"


def test_a_section_off_the_axis_shows_the_hole():
    # The cutting plane is 1 mm from the hole axis: the cut walls are at 2.83 mm from the axis, not at the radius.
    walls = [line("s1", [10 - 2.828427, 0], [10 - 2.828427, 10], "section"), line("s2", [10 + 2.828427, 0], [10 + 2.828427, 10], "section")]
    front = [item for item in FRONT_MODEL if not item["id"].startswith("h")] + walls
    cut = {"origin": [0, 9, 0], "normal": [0, 1, 0]}
    result, _ = coverage({"top": [], "front": COMPLETE["front"]}, derived={"front": {"geometry": front, "cutting_plane": cut}})
    assert result["round_1"]["visible_in"] == ["front"]
    # A cutting plane that does not cut the hole: a section edge at the hole position belongs to another feature.
    other = [item for item in FRONT_MODEL if not item["id"].startswith("h")] + [line("wall", [10, 0], [10, 10], "section")]
    cut = {"origin": [0, 0, 0], "normal": [0, 1, 0]}
    result, _ = coverage({"top": [], "front": COMPLETE["front"]}, derived={"front": {"geometry": other, "cutting_plane": cut}})
    assert result["round_1"]["visible_in"] == []


def test_an_edge_that_fits_two_round_features_shows_neither():
    # A boss above the bore on one axis with one radius: the top view circle does not show which one is visible,
    # and the diameter at it does not show which one it sizes.
    boss = {"id": "round_2", "kind": "boss", "axis": (0.0, 0.0, 1.0), "foot": (10.0, 10.0, 0.0), "radius": 3.0, "extent": [10.0, 20.0]}
    result, findings = coverage(COMPLETE, features={**PLATE, "features": PLATE["features"] + [boss]})
    assert result["round_1"]["visible_in"] == [] and findings[("FEAT-02", "round_1")]["status"] == "fail"
    assert findings[("FEAT-02", "round_2")]["status"] == "fail"
    # The position from the common center stays valid: both features have this axis.
    assert result["round_1"]["positions"] == {"[1, 0, 0]": True, "[0, 1, 0]": True}
    # A second hole behind the first one in the front view: their outlines coincide there. The top view still shows each hole.
    behind = {**PLATE["features"][0], "id": "round_3", "foot": (10.0, 30.0, 0.0)}
    front = [item if not item["id"].startswith("h") else {**item, "style": "visible"} for item in FRONT_MODEL]
    top = TOP_MODEL + [circle("hole_2", [10, 30], 3)]
    result, _ = coverage(COMPLETE, features={**PLATE, "features": PLATE["features"] + [behind]},
                         derived={"top": {"geometry": top}, "front": {"geometry": front}})
    assert result["round_1"]["visible_in"] == ["top"] and result["round_3"]["visible_in"] == ["top"]


def test_an_empty_inventory_is_not_applicable():
    report = Report()
    check(report, [view("top", TOP, [], TOP_MODEL)], {"top": {"geometry": TOP_MODEL}}, {"features": []}, set(), [])
    statuses = {item["rule_id"]: item["status"] for item in report.findings}
    assert statuses == {"FEAT-01": "not_applicable", "FEAT-02": "not_applicable", "FEAT-03": "not_applicable"}
    report = Report()
    check(report, [view("top", TOP, [], TOP_MODEL)], {"top": {"geometry": TOP_MODEL}}, {**PLATE, "features": PLATE["features"][1:]}, set(), [])
    assert [item["status"] for item in report.findings if item["rule_id"] == "FEAT-02"] == ["not_applicable"]


def single(feature, front_model, dimensions, markers=()):
    """FEAT findings of one feature in the front view (local x = model x, local y = model z)."""
    report = Report()
    result = check(report, [view("front", FRONT, dimensions, front_model)], {"front": {"geometry": front_model}}, {"features": [feature]},
                   {item["id"] for item in dimensions}, list(markers))
    return result[0], {item["rule_id"]: item for item in report.findings}


def angular(identifier, center, p1, p2):
    return {"id": identifier, "type": "angular", "center": center, "p1": p1, "p2": p2}


def test_a_chamfer_of_a_straight_edge_needs_two_sizes():
    # A 2 x 2 mm chamfer between the top face (z = 10) and the right face (x = 40) of the plate, edge-on in the front view.
    s = 0.5 ** 0.5
    chamfer = {"id": "plane_1", "kind": "plane_level", "normal": (s, 0.0, s), "offset": 48 * s, "inclined": True,
               "faces": [[[38, 0, 10], [40, 0, 8], [40, 20, 8], [38, 20, 10]]]}
    model = [line("ch", [38, 10], [40, 8])]
    width, height = linear("cw", [38, 10], [40, 8], "horizontal"), linear("chh", [40, 8], [38, 10], "vertical")
    angle = angular("ca", [40, 8], [40, 0], [38, 10])
    result, findings = single(chamfer, model, [width, height])
    assert result["visible_in"] == ["front"] and findings["FEAT-02"]["status"] == "pass"
    assert single(chamfer, model, [width, angle])[1]["FEAT-02"]["status"] == "pass"
    assert single(chamfer, model, [width])[1]["FEAT-02"]["status"] == "fail"


def test_a_chamfer_of_a_hole_needs_two_sizes():
    # A 45 degree chamfer from radius 3 to radius 4 at the top of the hole (z = 9..10). The front view shows its outlines.
    cone = {"id": "cone_1", "kind": "cone", "side": "hole", "axis": (0.0, 0.0, 1.0), "foot": (10.0, 10.0, 0.0), "extent": [9.0, 10.0],
            "radii": [3.0, 4.0], "half_angle": 45.0}
    model = [line("o1", [7, 9], [6, 10]), line("o2", [13, 9], [14, 10])]
    across = linear("cd", [6, 10], [14, 10], "horizontal")
    angle = angular("ca", [6, 10], [7, 9], [0, 10])
    result, findings = single(cone, model, [across, angle])
    assert result["visible_in"] == ["front"] and findings["FEAT-02"]["status"] == "pass"
    assert single(cone, model, [angle])[1]["FEAT-02"]["status"] == "fail"
    # A line beside the cone does not show it.
    assert single(cone, [line("other", [7, 0], [7, 9])], [across, angle])[0]["visible_in"] == []


def test_a_fillet_of_a_round_edge_needs_its_radius():
    # A fillet of radius 1 around the axis (10, 10): the profile circles are at 5 mm from the axis, at z = 5.
    torus = {"id": "torus_1", "kind": "torus", "axis": (0.0, 0.0, 1.0), "foot": (10.0, 10.0, 0.0), "station": 5.0, "major": 5.0, "minor": 1.0}
    profile = {"id": "p", "type": "arc", "style": "visible", "center": [15, 5], "radius": 1, "start_angle": 90, "end_angle": 180}
    radius = {"id": "fr", "type": "radius", "center": [15, 5], "radius": 1}
    result, findings = single(torus, [profile], [radius])
    assert result["visible_in"] == ["front"] and findings["FEAT-02"]["status"] == "pass"
    # The derivation can give the profile as a polyline.
    points = [[15 + math.cos(math.radians(a)), 5 + math.sin(math.radians(a))] for a in (90, 135, 180)]
    polyline = [line("q1", points[0], points[1]), line("q2", points[1], points[2])]
    assert single(torus, polyline, [radius])[0]["visible_in"] == ["front"]
    assert single(torus, [profile], [])[1]["FEAT-02"]["status"] == "fail"


def test_a_free_form_surface_needs_a_marker_and_a_review():
    surface = {"id": "surface_1", "kind": "surface", "surface_type": "bspline",
               "edges": [[[0, 0, 0], [10, 0, 0]], [[10, 0, 0], [12, 0, 5], [10, 0, 10]]]}
    model = [line("s1", [0, 0], [10, 0]), line("s2", [10, 0], [12, 5])]
    result, findings = single(surface, model, [])
    assert result["visible_in"] == ["front"] and findings["FEAT-02"]["status"] == "fail" and "FEAT-03" not in findings
    result, findings = single(surface, model, [], markers=[{"id": "m1", "view_id": "front", "primitive_id": "s1"}])
    assert findings["FEAT-02"]["status"] == "needs_review" and result["status"] == "needs_review"
    assert "edges" not in result


def test_isometric_views_do_not_count():
    iso = {"scale_convention": "isometric_drawing", "matrix": [[0.7, -0.7, 0], [-0.4, -0.4, 0.8]]}
    report = Report()
    views = [{**view("iso", iso, []), "kind": "isometric"}]
    result = check(report, views, {"iso": {"geometry": TOP_MODEL}}, PLATE, set(), [])
    assert all(item["visible_in"] == [] for item in result)


def test_the_flange_inventory_has_its_round_features_and_plane_levels(tmp_path):
    pytest.importorskip("build123d")
    from test_view_derivation import candidate, flange

    found = inventory(candidate(flange(), tmp_path / "model"))
    rounds = [(item["kind"], item["radius"]) for item in found["features"] if item["kind"] != "plane_level"]
    assert rounds == [("boss", 50.0), ("boss", 25.0), ("hole", 15.0)] + [("hole", 5.0)] * 4
    levels = [item["offset"] for item in found["features"] if item["kind"] == "plane_level"]
    assert levels == [0.0, 12.0, 32.0] and not [item for item in found["features"] if item["kind"] in {"cone", "torus", "surface"}]
    bore = next(item for item in found["features"] if item["kind"] == "hole" and item["radius"] == 15.0)
    assert bore["extent"] == [0.0, 32.0]


def test_the_inventory_has_chamfers_fillets_and_free_form_surfaces(tmp_path):
    build123d = pytest.importorskip("build123d")
    from build123d import Axis, Box, Cylinder, GeomType, Pos, Sphere, chamfer, export_step, fillet

    # A plate 40 x 20 x 10 (centered) with a chamfer of a straight edge, a hole with a chamfer, a boss with a fillet at its base,
    # and a spherical dome.
    part = Box(40, 20, 10)
    part = chamfer(part.edges().filter_by(Axis.Y).group_by(Axis.Z)[-1].sort_by(Axis.X)[-1], 1)
    part -= Pos(-10, 0, 0) * Cylinder(3, 10)
    part = chamfer(part.edges().filter_by(GeomType.CIRCLE).group_by(Axis.Z)[-1].sort_by(Axis.X)[0], 0.5)
    part += Pos(5, 0, 7.5) * Cylinder(3, 5)
    base = [edge for edge in part.edges().filter_by(GeomType.CIRCLE)
            if abs(edge.arc_center.Z - 5) < 1e-6 and abs(edge.arc_center.X - 5) < 1e-6 and abs(edge.radius - 3) < 1e-6]
    part = fillet(base, 1)
    part += Pos(12, 0, 5) * Sphere(2)
    path = tmp_path / "part.step"
    export_step(part, str(path))
    found = inventory(path)["features"]
    kinds = {item["kind"] for item in found}
    assert {"hole", "boss", "cone", "torus", "surface", "plane_level"} <= kinds, kinds
    cone = next(item for item in found if item["kind"] == "cone")
    assert cone["side"] == "hole" and sorted(cone["radii"]) == pytest.approx([3.0, 3.5], abs=1e-4)
    torus = next(item for item in found if item["kind"] == "torus")
    assert torus["minor"] == pytest.approx(1.0, abs=1e-4) and torus["major"] == pytest.approx(4.0, abs=1e-4)
    assert [item for item in found if item["kind"] == "plane_level" and item["inclined"]], "the chamfer of the straight edge"
    assert {item["surface_type"] for item in found if item["kind"] == "surface"} == {"sphere"}
