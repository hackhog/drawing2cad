"""Feature coverage of a drawing: the feature inventory of the bound STEP and the rules FEAT-01 to FEAT-04."""

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
    return {"id": identifier, "kind": "plane_level", "normal": normal, "offset": offset, "boxes": [[low, high]]}


PLATE = {"features": [
    {"id": "round_1", "kind": "hole", "axis": (0.0, 0.0, 1.0), "foot": (10.0, 10.0, 0.0), "radius": 3.0, "extent": [0.0, 10.0]},
    level("plane_1", (1.0, 0.0, 0.0), 0.0, [0, 0, 0], [0, 20, 10]), level("plane_2", (1.0, 0.0, 0.0), 40.0, [40, 0, 0], [40, 20, 10]),
    level("plane_3", (0.0, 1.0, 0.0), 0.0, [0, 0, 0], [40, 0, 10]), level("plane_4", (0.0, 1.0, 0.0), 20.0, [0, 20, 0], [40, 20, 10]),
    level("plane_5", (0.0, 0.0, 1.0), 0.0, [0, 0, 0], [40, 20, 0]), level("plane_6", (0.0, 0.0, 1.0), 10.0, [0, 0, 10], [40, 20, 10])],
    "other_surfaces": {}}
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
    # The outlines are visible in a section.
    front = [item if not item["id"].startswith("h") else {**item, "style": "section"} for item in FRONT_MODEL]
    result, _ = coverage(dimensions, derived={"top": {"geometry": TOP_MODEL}, "front": {"geometry": front}})
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
    result, _ = coverage({"top": [], "front": COMPLETE["front"]}, derived={"front": {"geometry": front}})
    assert result["round_1"]["visible_in"] == ["front"]


def test_an_empty_inventory_is_not_applicable():
    report = Report()
    check(report, [view("top", TOP, [], TOP_MODEL)], {"top": {"geometry": TOP_MODEL}}, {"features": [], "other_surfaces": {"sphere": 1}}, set(), [])
    statuses = {item["rule_id"]: item["status"] for item in report.findings}
    assert statuses == {"FEAT-01": "not_applicable", "FEAT-02": "not_applicable", "FEAT-03": "not_applicable", "FEAT-04": "not_tested"}
    report = Report()
    check(report, [view("top", TOP, [], TOP_MODEL)], {"top": {"geometry": TOP_MODEL}}, {**PLATE, "features": PLATE["features"][1:]}, set(), [])
    assert [item["status"] for item in report.findings if item["rule_id"] == "FEAT-02"] == ["not_applicable"]


def test_other_surfaces_are_listed_as_not_tested():
    features = {**PLATE, "other_surfaces": {"cone": 2, "torus": 4}}
    _, findings = coverage(COMPLETE, features=features)
    assert findings[("FEAT-04", None)]["status"] == "not_tested" and "2 cone, 4 torus" in findings[("FEAT-04", None)]["message"]


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
    assert levels == [0.0, 12.0, 32.0] and found["other_surfaces"] == {}
    bore = next(item for item in found["features"] if item["kind"] == "hole" and item["radius"] == 15.0)
    assert bore["extent"] == [0.0, 32.0]
