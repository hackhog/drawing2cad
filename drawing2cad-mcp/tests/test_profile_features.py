"""Synthetic arc profiles, draft, drill tips, and independent BREP measurements."""

from copy import deepcopy
import math

import pytest

from drawing2cad_mcp.part_schema import part_validate
from test_part_schema import sample_description


def profile_description():
    description = sample_description()
    description["parameters"] = [{"name": "right", "value": 10, "unit": "mm", "evidence_ids": ["drawing"]}]
    right = {"parameter": "right"}
    description["features"] = [{
        "id": "outline", "type": "profile_extrusion", "operation": "base", "height": 4,
        "evidence_ids": ["drawing"], "segments": [
            {"kind": "line", "start": [0, -5], "end": [right, -5]},
            {"kind": "three_point_arc", "start": [right, -5], "mid": [15, 0], "end": [right, 5]},
            {"kind": "line", "start": [right, 5], "end": [0, 5]},
            {"kind": "three_point_arc", "start": [0, 5], "mid": [-5, 0], "end": [0, -5]},
        ],
    }]
    description["measurements"] = [
        {"id": "bbox", "kind": "bbox", "expected": [20, 10, 4], "basis": "independent_measurement", "evidence_ids": ["drawing"]},
        {"id": "radius", "kind": "arc_radius", "position": [0, 0, 0], "axis": "Z", "expected": [5], "basis": "printed_dimension", "evidence_ids": ["drawing"]},
    ]
    return description


def kernel():
    pytest.importorskip("build123d")
    from drawing2cad_mcp.cad_kernel import build
    from drawing2cad_mcp.cad_validation import validate_step
    return build, validate_step


def test_arc_profile_and_radius_survive_export_and_import(tmp_path):
    build, validate_step = kernel()
    description = profile_description()
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    assert result["measured"]["volume_mm3"] == pytest.approx((100 + math.pi * 25) * 4)
    imported = validate_step(result["candidate_step"], description)
    assert imported["status"] == "pass"
    arcs = imported["measured"]["circular_edges"]
    assert len(arcs) == 4
    assert all(item["radius"] == pytest.approx(5) for item in arcs)
    assert all(item["sweep_degrees"] == pytest.approx(180) for item in arcs)


@pytest.mark.parametrize("mutation,code", [
    (lambda d: d["features"][0]["segments"][0].update(end=[9, -5]), "profile_gap"),
    (lambda d: d["features"][0]["segments"][1].update(mid=[10, 0]), "invalid_arc"),
    (lambda d: d["features"][0]["segments"][1].update(mid=[10, -5]), "invalid_arc"),
    (lambda d: d["features"][0]["segments"][0].update(end=[0, -5]), "invalid_profile"),
    (lambda d: d["features"][0].update(taper_angle=45), "invalid_taper"),
    (lambda d: d["parameters"][0].update(unit="deg"), "parameter_unit"),
])
def test_malformed_profiles_fail_before_kernel_execution(mutation, code):
    description = profile_description()
    mutation(description)
    result = part_validate(description)
    assert result["status"] == "fail"
    assert code in {item["code"] for item in result["defects"]}


@pytest.mark.parametrize("taper,clockwise", [(3, False), (3, True), (-3, False)])
def test_polygon_taper_has_expected_volume_for_both_windings(tmp_path, taper, clockwise):
    build, validate_step = kernel()
    description = sample_description()
    points = [[0, 0], [20, 0], [20, 10], [0, 10]]
    description["parameters"].append({"name": "draft", "value": taper, "unit": "deg", "evidence_ids": ["drawing"]})
    description["features"] = [{"id": "base", "type": "extrusion", "operation": "base",
                                 "points": points[::-1] if clockwise else points,
                                 "height": 5, "taper_angle": {"parameter": "draft"}, "evidence_ids": ["drawing"]}]
    tangent = math.tan(math.radians(taper))
    volume = 1000 - tangent * 30 * 25 + 4 * tangent**2 * 125 / 3
    description["measurements"] = [{"id": "volume", "kind": "volume", "expected": [volume],
                                     "basis": "independent_measurement", "evidence_ids": ["drawing"]}]
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    assert result["measured"]["volume_mm3"] == pytest.approx(volume)
    assert validate_step(result["candidate_step"], description)["status"] == "pass"


def test_profile_taper_and_rotated_extrusion_axis(tmp_path):
    build, validate_step = kernel()
    description = profile_description()
    description["features"][0].update(axis="X", origin=[2, 3, 4], taper_angle=3)
    description["measurements"] = []
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    assert result["measured"]["bbox_size"] == pytest.approx([4, 20, 10])
    assert validate_step(result["candidate_step"], description)["status"] == "pass"


def test_arc_radius_check_fails_when_expected_radius_is_wrong(tmp_path):
    build, _ = kernel()
    description = profile_description()
    description["measurements"][1]["expected"] = [5.2]
    result = build(description, tmp_path)
    assert result["status"] == "fail"
    assert result["candidate_step"] is None


def test_outer_diameter_uses_convex_faces(tmp_path):
    build, validate_step = kernel()
    description = sample_description()
    description["features"] = [{"id": "base", "type": "cylinder", "operation": "base", "diameter": 20,
                                 "height": 5, "evidence_ids": ["drawing"]}]
    description["measurements"] = [{"id": "outer", "kind": "outer_diameter", "position": [0, 0, 0],
                                     "axis": "Z", "axial_length": 5, "expected": [20],
                                     "basis": "printed_dimension", "evidence_ids": ["drawing"]}]
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    assert result["measured"]["holes"] == []
    assert validate_step(result["candidate_step"], description)["status"] == "pass"


def test_outer_diameter_uses_requested_station_after_step_import(tmp_path):
    build, validate_step = kernel()
    description = sample_description()
    description["features"] = [
        {"id": "shaft", "type": "cylinder", "operation": "base", "diameter": 10,
         "height": 10, "evidence_ids": ["drawing"]},
        {"id": "shoulder", "type": "cylinder", "operation": "add", "diameter": 20,
         "height": 5, "origin": [0, 0, 5], "evidence_ids": ["drawing"]},
    ]
    description["measurements"] = []
    result = build(description, tmp_path)
    assert result["status"] == "pass"

    def at(station, diameter, axis="Z"):
        measured_part = deepcopy(description)
        measured_part["measurements"] = [
            {"id": "outside", "kind": "outer_diameter", "position": [0, 0, station],
             "axis": axis, "expected": [diameter], "basis": "printed_dimension",
             "evidence_ids": ["drawing"]},
        ]
        return next(item for item in validate_step(result["candidate_step"], measured_part)["checks"]
                    if item["check"] == "outside")

    lower = at(2, 10)
    assert lower["status"] == "pass" and lower["actual"] == pytest.approx([10])
    upper = at(7, 20)
    assert upper["status"] == "pass" and upper["actual"] == pytest.approx([20])
    assert upper["station"] == 7
    assert upper["actual_station_intervals"][0]["start"] == pytest.approx(5)
    assert upper["actual_station_intervals"][0]["end"] == pytest.approx(10)
    wrong = at(7, 10)
    assert wrong["status"] == "fail" and wrong["actual"] == pytest.approx([20])
    absent = at(11, 20)
    assert absent["status"] == "fail" and absent["actual"] == []
    assert "No coaxial outer cylinder" in absent["reason"]
    assert at(0, 10)["status"] == "pass"
    assert at(10, 20)["status"] == "pass"
    shared = at(5, 20)
    assert shared["status"] == "fail"
    assert sorted(shared["actual"]) == pytest.approx([10, 20])
    assert "Different outer diameters" in shared["reason"]
    reversed_axis = at(7, 20, "-Z")
    assert reversed_axis["status"] == "pass" and reversed_axis["station"] == -7
    assert reversed_axis["actual_station_intervals"][0]["start"] == pytest.approx(-10)


def test_outer_diameter_station_on_translated_x_axis(tmp_path):
    build, validate_step = kernel()
    description = sample_description()
    description["features"] = [
        {"id": "shaft", "type": "cylinder", "operation": "base", "diameter": 10,
         "height": 10, "origin": [2, 3, 4], "axis": "X", "evidence_ids": ["drawing"]},
        {"id": "shoulder", "type": "cylinder", "operation": "add", "diameter": 20,
         "height": 5, "origin": [7, 3, 4], "axis": "X", "evidence_ids": ["drawing"]},
    ]
    description["measurements"] = [{"id": "diameter", "kind": "outer_diameter",
                                    "position": [9, 3, 4], "axis": "X", "expected": [20],
                                    "basis": "printed_dimension", "evidence_ids": ["drawing"]}]
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    check = next(item for item in validate_step(result["candidate_step"], description)["checks"]
                 if item["check"] == "diameter")
    assert check["status"] == "pass" and check["actual"] == pytest.approx([20])
    assert check["actual_station_intervals"][0]["start"] == pytest.approx(7)
    assert check["actual_station_intervals"][0]["end"] == pytest.approx(12)


@pytest.mark.parametrize("component,expected", [("distance", math.sqrt(116)), ("X", 10), ("Y", 4)])
def test_axis_spacing_is_measured_from_imported_holes(tmp_path, component, expected):
    build, validate_step = kernel()
    description = sample_description()
    for identifier, point in [("first", [5, 3, 5]), ("second", [15, 7, 5])]:
        description["features"].append({"id": identifier, "type": "hole", "position": point,
                                        "diameter": 2, "evidence_ids": ["drawing"]})
    description["measurements"] = [{"id": "spacing", "kind": "axis_distance", "position": [5, 3, 5],
                                     "second_position": [15, 7, 5], "axis": "Z", "component": component,
                                     "expected": [expected], "basis": "printed_dimension", "evidence_ids": ["drawing"]}]
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    assert validate_step(result["candidate_step"], description)["status"] == "pass"


def test_plane_spacing_requires_actual_bounded_faces(tmp_path):
    build, validate_step = kernel()
    description = sample_description()
    description["measurements"] = [{"id": "width", "kind": "plane_distance", "position": [0, 5, 2],
                                     "second_position": [20, 5, 2], "axis": "X", "expected": [20],
                                     "basis": "printed_dimension", "evidence_ids": ["drawing"]}]
    result = build(description, tmp_path / "valid")
    assert result["status"] == "pass"
    assert validate_step(result["candidate_step"], description)["status"] == "pass"
    description["measurements"][0]["position"] = [0, 50, 20]
    assert build(description, tmp_path / "outside")["status"] == "fail"


def test_blind_drill_tip_volume_and_cylindrical_length(tmp_path):
    build, validate_step = kernel()
    description = sample_description()
    description["features"].append({"id": "drill", "type": "hole", "position": [5, 5, 5],
                                    "diameter": 3, "extent": "blind", "depth": 3, "drill_angle": 118,
                                    "evidence_ids": ["drawing"]})
    tip_depth = 1.5 / math.tan(math.radians(59))
    description["measurements"] = [
        {"id": "hole", "kind": "hole", "position": [5, 5, 5], "axis": "Z", "axial_length": 3,
         "expected": [3], "basis": "printed_dimension", "evidence_ids": ["drawing"]},
        {"id": "volume", "kind": "volume", "expected": [1000 - math.pi * 1.5**2 * (3 + tip_depth / 3)],
         "basis": "independent_measurement", "evidence_ids": ["drawing"]},
    ]
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    assert validate_step(result["candidate_step"], description)["status"] == "pass"


def test_blind_drill_tip_cannot_break_through(tmp_path):
    build, _ = kernel()
    from drawing2cad_mcp.cad_kernel import CadBuildError

    description = sample_description()
    description["features"].append({"id": "drill", "type": "hole", "position": [5, 5, 5],
                                    "diameter": 3, "extent": "blind", "depth": 4.5, "drill_angle": 118,
                                    "evidence_ids": ["drawing"]})
    with pytest.raises(CadBuildError) as error:
        build(description, tmp_path)
    assert error.value.code == "BLIND_HOLE_BREAKTHROUGH"


def test_drill_angle_requires_blind_extent_and_valid_angle():
    description = sample_description()
    feature = {"id": "drill", "type": "hole", "position": [5, 5, 5], "diameter": 3,
               "drill_angle": 118, "evidence_ids": ["drawing"]}
    description["features"].append(deepcopy(feature))
    assert part_validate(description)["status"] == "fail"
    description["features"][-1].update(extent="blind", depth=3, drill_angle=180)
    assert part_validate(description)["status"] == "fail"


def test_radius_selector_and_chamfer_width_angle_are_independent(tmp_path):
    build, validate_step = kernel()
    description = sample_description()
    description["features"] = [
        {"id": "base", "type": "cylinder", "operation": "base", "diameter": 20, "height": 5, "evidence_ids": ["drawing"]},
        {"id": "bore", "type": "hole", "position": [0, 0, 5], "diameter": 10, "evidence_ids": ["drawing"]},
        {"id": "finish", "type": "chamfer", "size": 1, "evidence_ids": ["drawing"],
         "selector": {"geometry": "circle", "center_min": [0, 0, 5], "center_max": [0, 0, 5], "radius": 5, "expected_count": 1}},
    ]
    description["measurements"] = [
        {"id": "angle", "kind": "cone_angle", "position": [0, 0, 5], "axis": "Z", "expected": [45], "basis": "printed_dimension", "evidence_ids": ["drawing"]},
        {"id": "width", "kind": "cone_width", "position": [0, 0, 5], "axis": "Z", "expected": [1], "basis": "printed_dimension", "evidence_ids": ["drawing"]},
        {"id": "outer", "kind": "outer_diameter", "position": [0, 0, 0], "axis": "Z", "expected": [20], "axial_length": 5, "basis": "printed_dimension", "evidence_ids": ["drawing"]},
    ]
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    assert validate_step(result["candidate_step"], description)["status"] == "pass"
    changed = deepcopy(description)
    changed["measurements"][0]["position"][2] = 0
    assert validate_step(result["candidate_step"], changed)["status"] == "fail"


def test_oblique_face_width_and_edge_angle(tmp_path):
    build, validate_step = kernel()
    description = sample_description()
    c, s = math.cos(math.radians(40)), math.sin(math.radians(40))
    points = [[0, 0], [20*c, 20*s], [20*c-10*s, 20*s+10*c], [-10*s, 10*c]]
    description["features"] = [{"id": "base", "type": "extrusion", "operation": "base", "height": 5,
                                 "points": points, "evidence_ids": ["drawing"]}]
    description["measurements"] = [
        {"id": "width", "kind": "plane_distance", "position": [10*c, 10*s, 2],
         "second_position": [10*c-10*s, 10*s+10*c, 2], "direction": [-s, c, 0], "expected": [10],
         "basis": "printed_dimension", "evidence_ids": ["drawing"]},
        {"id": "angle", "kind": "line_angle", "position": [10*c, 10*s, 0], "axis": "Y", "expected": [50],
         "basis": "printed_dimension", "evidence_ids": ["drawing"]},
    ]
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    assert validate_step(result["candidate_step"], description)["status"] == "pass"


def test_draft_angle_is_measured_from_wall_face(tmp_path):
    build, validate_step = kernel()
    description = sample_description()
    description["features"] = [{"id": "base", "type": "extrusion", "operation": "base", "height": 5,
                                 "points": [[0, 0], [20, 0], [20, 10], [0, 10]], "taper_angle": 3,
                                 "evidence_ids": ["drawing"]}]
    description["measurements"] = [{"id": "draft", "kind": "plane_angle", "position": [2.5*math.tan(math.radians(3)), 5, 2.5],
                                     "axis": "X", "expected": [3], "basis": "printed_dimension", "evidence_ids": ["drawing"]}]
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    assert validate_step(result["candidate_step"], description)["status"] == "pass"


@pytest.mark.parametrize("direction", [[0, 0, 0], [float("nan"), 1, 0]])
def test_measurement_direction_must_be_finite_and_nonzero(direction):
    description = sample_description()
    description["measurements"] = [{"id": "angle", "kind": "line_angle", "position": [0, 0, 0],
                                     "direction": direction, "expected": [50], "basis": "printed_dimension", "evidence_ids": ["drawing"]}]
    assert part_validate(description)["status"] == "fail"


def test_section_distance_measures_drafted_faces_at_selected_height(tmp_path):
    build, validate_step = kernel()
    description = sample_description()
    description["features"] = [{"id": "base", "type": "extrusion", "operation": "base", "height": 5,
                                 "points": [[0, 0], [20, 0], [20, 10], [0, 10]], "taper_angle": 3,
                                 "evidence_ids": ["drawing"]}]
    offset = 2.5 * math.tan(math.radians(3))
    description["measurements"] = [{"id": "width", "kind": "section_distance",
                                     "position": [offset, 5, 2.5], "second_position": [20-offset, 5, 2.5],
                                     "axis": "X", "expected": [20-2*offset], "basis": "printed_dimension",
                                     "evidence_ids": ["drawing"]}]
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    assert validate_step(result["candidate_step"], description)["status"] == "pass"
    changed = deepcopy(description)
    changed["measurements"][0]["expected"] = [20]
    assert validate_step(result["candidate_step"], changed)["status"] == "fail"
    changed = deepcopy(description)
    for key in ("position", "second_position"):
        changed["measurements"][0][key][1] = 100
    assert validate_step(result["candidate_step"], changed)["status"] == "fail"
    changed["measurements"][0]["second_position"][2] = 3
    assert part_validate(changed)["status"] == "fail"


def test_surface_radius_requires_trimmed_face_and_axis(tmp_path):
    build, validate_step = kernel()
    description = profile_description()
    description["measurements"] = [{"id": "radius", "kind": "surface_radius", "position": [15, 0, 2],
                                     "axis": "Z", "expected": [5], "basis": "printed_dimension",
                                     "evidence_ids": ["drawing"]}]
    result = build(description, tmp_path)
    assert result["status"] == "pass"
    assert validate_step(result["candidate_step"], description)["status"] == "pass"
    for mutation in ({"expected": [6]}, {"position": [10, 0, 2]}, {"axis": "X"}):
        changed = deepcopy(description)
        changed["measurements"][0].update(mutation)
        assert validate_step(result["candidate_step"], changed)["status"] == "fail"
