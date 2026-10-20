"""View derivation from real build123d geometry, without the sandbox."""

import math
from copy import deepcopy

import pytest

pytest.importorskip("build123d")

from drawing2cad_mcp.cad_kernel import build  # noqa: E402
from drawing2cad_mcp.derived_views import normalize_requests  # noqa: E402
from drawing2cad_mcp.drawing_contract_v2 import Projection, projection_defects  # noqa: E402
from drawing2cad_mcp.view_derivation import derive  # noqa: E402
from test_part_schema import sample_description  # noqa: E402

ISO = {"id": "iso", "kind": "isometric", "view_direction": [1, -1, 1], "up": [0, 0, 1]}
FRONT = {"id": "front", "kind": "orthographic", "view_direction": [0, -1, 0], "up": [0, 0, 1]}
TOP = {"id": "top", "kind": "orthographic", "view_direction": [0, 0, 1], "up": [0, 1, 0]}
RIGHT = {"id": "right", "kind": "orthographic", "view_direction": [1, 0, 0], "up": [0, 0, 1]}


def asymmetric_block():
    """Box 40 x 25 x 10 with an off-center through hole. No two edge lengths agree."""
    description = sample_description()
    description["parameters"][0]["value"] = 40
    description["features"][0].update(width=25, height=10)
    description["features"].append({"id": "hole", "type": "hole", "position": [12, 8, 10], "diameter": 6,
                                     "extent": "through", "axis": "-Z", "evidence_ids": ["drawing"]})
    description["measurements"][0]["expected"] = [40, 25, 10]
    return description


def flange():
    """Disc 100 x 12 with a hub 50 x 20, a bore 30, and four bolt holes 10 on a 76 mm circle."""
    description = sample_description()
    description["name"] = "Synthetic flange"
    description["parameters"] = [{"name": "disc", "value": 100, "unit": "mm", "evidence_ids": ["drawing"]}]
    holes = [{"id": f"bolt{i}", "type": "hole", "position": [38 * math.cos(math.radians(45 + 90 * i)), 38 * math.sin(math.radians(45 + 90 * i)), 12],
              "diameter": 10, "extent": "through", "axis": "-Z", "evidence_ids": ["drawing"]} for i in range(4)]
    description["features"] = [
        {"id": "disc", "type": "cylinder", "operation": "base", "diameter": {"parameter": "disc"}, "height": 12, "evidence_ids": ["drawing"]},
        {"id": "hub", "type": "cylinder", "operation": "add", "diameter": 50, "height": 20, "origin": [0, 0, 12], "evidence_ids": ["drawing"]},
        {"id": "bore", "type": "hole", "position": [0, 0, 32], "diameter": 30, "extent": "through", "axis": "-Z", "evidence_ids": ["drawing"]},
        *holes]
    description["measurements"] = [{"id": "overall", "kind": "bbox", "basis": "printed_dimension", "expected": [100, 100, 32],
                                    "evidence_ids": ["drawing"]}]
    return description


def candidate(description, directory):
    directory.mkdir()
    assert build(description, directory)["status"] == "pass"
    return directory / "candidate.step"


def lines(view, style="visible"):
    return [item for item in view["geometry"] if item["type"] == "line" and item["style"] == style]


def test_isometric_view_has_equal_axis_scales_and_120_degree_axes(tmp_path):
    view = derive(candidate(asymmetric_block(), tmp_path / "model"), normalize_requests([ISO]))["views"][0]
    assert projection_defects("isometric", Projection(**view["projection"])) == []
    # The box edges from one corner: direction vector in the view, divided by the model length, has the same length for each axis.
    scales, directions = {}, {}
    for item in lines(view):
        d = [item["end"][0] - item["start"][0], item["end"][1] - item["start"][1]]
        length = math.hypot(*d)
        for axis, model_length in (("x", 40), ("y", 25), ("z", 10)):
            row = [view["projection"]["matrix"][0]["xyz".index(axis)], view["projection"]["matrix"][1]["xyz".index(axis)]]
            unit = math.hypot(*row)
            if abs(abs(d[0] * row[0] + d[1] * row[1]) / (length * unit) - 1) < 1e-6 and abs(length - unit * model_length) < 1e-4:
                scales[axis] = length / model_length
                directions[axis] = [row[0] / unit, row[1] / unit]
    assert set(scales) == {"x", "y", "z"}
    assert max(scales.values()) - min(scales.values()) < 1e-6
    assert scales["x"] == pytest.approx(1.0, abs=1e-6)  # isometric_drawing: full-length axes.
    signs = {"x": 1, "y": -1, "z": 1}
    for a, b in (("x", "y"), ("y", "z"), ("x", "z")):
        cosine = sum(signs[a] * p * signs[b] * q for p, q in zip(directions[a], directions[b]))
        assert math.degrees(math.acos(cosine)) == pytest.approx(120, abs=1e-4)
    ellipses = [item for item in view["geometry"] if item["type"] == "ellipse"]
    assert ellipses and all(item["approximation_error"] == 0.0 for item in ellipses)
    assert not [item for item in view["geometry"] if item["style"] == "hidden"]


@pytest.mark.parametrize("change, message", [
    ({"view_direction": [1, -1, 2]}, "dimetric or trimetric"),
    ({"projection_type": "perspective"}, "perspective"),
    ({"kind": "orthographic", "view_direction": [1, -1, 0]}, "model axis"),
    ({"matrix": [[1, 0, 0], [0, 1, 0]]}, "schema"),
])
def test_non_isometric_requests_are_detected(change, message):
    with pytest.raises(ValueError) as error:
        normalize_requests([{**ISO, **change}])
    assert message in str(error.value)


def test_local_coordinates_are_the_matrix_times_the_model_point(tmp_path):
    view = derive(candidate(asymmetric_block(), tmp_path / "model"), normalize_requests([FRONT]))["views"][0]
    assert view["projection"]["matrix"] == [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
    assert view["bounds"][0] == pytest.approx(0, abs=1e-6) and view["bounds"][2] == pytest.approx(40, abs=1e-6)
    hidden = lines(view, "hidden")
    assert {round(item["start"][0], 3) for item in hidden} >= {9.0, 15.0}  # The hole edges at x = 12 -/+ 3.
    centers = lines(view, "center")
    assert any(abs(item["start"][0] - 12) < 1e-6 and abs(item["end"][0] - 12) < 1e-6 for item in centers)


def test_flange_gives_orthographic_isometric_and_complete_sections(tmp_path):
    section = {"id": "section_a", "kind": "section", "up": [0, 0, 1],
               "cutting_plane": {"letter": "A", "origin": [0, 0, 0], "normal": [0, -1, 0], "viewing_side": "negative_normal",
                                 "source_view_id": "top"}}
    result = derive(candidate(flange(), tmp_path / "model"), normalize_requests([TOP, FRONT, ISO, section]))
    assert result["status"] == "pass", result
    top, front, iso, cut = result["views"]
    circles = [item for item in top["geometry"] if item["type"] == "circle" and item["style"] == "visible"]
    assert sorted({round(item["radius"], 6) for item in circles}) == [5.0, 15.0, 25.0, 50.0]
    assert len([item for item in circles if item["radius"] == 5.0]) == 4
    assert front["counts"]["hidden"] > 0 and front["counts"]["center"] > 0
    assert iso["counts"]["visible"] > 0 and any(item["type"] == "ellipse" for item in iso["geometry"])
    # The section: two cut surfaces (left and right of the bore), each with a closed hatching boundary.
    assert len(cut["hatching"]) == 2
    section_items = {item["id"]: item for item in cut["geometry"] if item["style"] == "section"}
    for hatch in cut["hatching"]:
        assert set(hatch["boundary_primitive_ids"]) <= set(section_items)
    xs = sorted({round(c, 6) for item in section_items.values() for c in (item["start"][0], item["end"][0])})
    assert xs[0] == pytest.approx(-50) and xs[-1] == pytest.approx(50) and -15.0 in xs and 15.0 in xs
    assert cut["counts"]["hidden"] == 0
    assert cut["cutting_plane"]["line"][0][1] == pytest.approx(0) and cut["cutting_plane"]["line"][1][1] == pytest.approx(0)
    assert cut["cutting_plane"]["line"][0][0] == pytest.approx(-55) and cut["cutting_plane"]["line"][1][0] == pytest.approx(55)


def test_derived_views_change_after_a_model_change(tmp_path):
    first = derive(candidate(asymmetric_block(), tmp_path / "first"), normalize_requests([TOP]))["views"][0]
    changed = deepcopy(asymmetric_block())
    next(feature for feature in changed["features"] if feature["id"] == "hole")["position"][0] += 5
    second = derive(candidate(changed, tmp_path / "second"), normalize_requests([TOP]))["views"][0]
    assert first["geometry"] != second["geometry"]
    hole = [item for item in second["geometry"] if item["type"] == "circle"][0]
    assert hole["center"] == [17.0, 8.0]


def test_section_needs_a_source_view_that_shows_the_plane_as_a_line():
    section = {"id": "s", "kind": "section", "up": [0, 0, 1],
               "cutting_plane": {"letter": "A", "origin": [0, 0, 0], "normal": [0, 0, 1], "viewing_side": "positive_normal",
                                 "source_view_id": "top"}}
    with pytest.raises(ValueError) as error:
        normalize_requests([TOP, {**section, "up": [0, 1, 0]}])
    assert "as a line" in str(error.value)


def test_derived_flange_views_validate_as_drawing_spec_2(tmp_path):
    import hashlib

    from drawing2cad_mcp.derived_views import expand
    from drawing2cad_mcp.drawing_contract import description_digest, drawing_validate

    description = flange()
    step = candidate(description, tmp_path / "model")
    section = {"id": "section_a", "kind": "section", "up": [0, 0, 1],
               "cutting_plane": {"letter": "A", "origin": [0, 0, 0], "normal": [0, -1, 0], "viewing_side": "negative_normal",
                                 "source_view_id": "top"}}
    result = derive(step, normalize_requests([TOP, FRONT, ISO, section]))
    digest = description_digest(description)
    state = {"revision": 1, "description_sha256": digest,
             "build": {"status": "pass", "description_revision": 1, "description_sha256": digest,
                       "candidate_sha256": hashlib.sha256(step.read_bytes()).hexdigest()}}
    record = {"binding": {"part_revision": 1, "description_sha256": digest, "candidate_sha256": state["build"]["candidate_sha256"]},
              "views": result["views"], "derivation_sha256": "d" * 64}

    def view(identifier, label, kind, origin, frame):
        return {"id": identifier, "label": label, "kind": kind, "orientation": "isometric" if kind == "isometric" else "custom",
                "origin": origin, "frame": frame, "scale": 0.5, "geometry": [], "dimensions": [],
                "derivation": {"derivation_sha256": "d" * 64, "view_id": identifier, "feature_ids": ["disc"], "evidence_ids": ["drawing"]}}

    spec = {"schema_version": "2.0", "part_revision": 1, "description_sha256": digest, "units": "mm", "title": "Synthetic flange",
            "sheet": {"width": 420.0, "height": 297.0}, "required_view_ids": ["top", "front", "iso", "section_a"],
            "views": [view("top", "Top", "orthographic", [70, 210], [35, 175, 105, 245]),
                      view("front", "Front", "orthographic", [70, 110], [35, 100, 105, 135]),
                      view("iso", "Isometric", "isometric", [300, 150], [240, 100, 360, 210]),
                      view("section_a", "Section A-A", "section", [170, 110], [135, 100, 205, 135])]}
    expanded, failure = expand(spec, record, state)
    assert failure is None
    report = drawing_validate(expanded, description, 1)
    # The agent adds the dimensions. The derived geometry, projections, section, and layout have no defect.
    assert {d["code"] for d in report["defects"]} == {"missing_dimensions", "unmarked_radius"}, report["defects"][:5]
    assert report["checks"]["isometric_projection"] == "pass"
    assert "section_trace" not in {item["code"] for item in report["findings"]}
    stale = {**state, "build": {**state["build"], "candidate_sha256": "e" * 64}}
    assert expand(spec, record, stale)[1]["defects"][0]["code"] == "derivation_stale"


def test_derivation_runs_in_the_verified_sandbox(tmp_path):
    import os

    from drawing2cad_mcp.worker_runner import WorkerRunner

    runner = WorkerRunner(tmp_path / "workers")
    capability = runner.capabilities()
    if os.environ.get("DRAWING2CAD_REQUIRE_SANDBOX") == "1":
        assert capability["available"], capability
    if not capability["available"]:
        pytest.skip("The verified Linux sandbox is unavailable.")
    step = candidate(asymmetric_block(), tmp_path / "model")
    result = runner.run("derive_views", input_step=step, views=normalize_requests([TOP, ISO]))
    assert result["status"] == "pass", result
    assert result["sandbox"]
    assert [view["id"] for view in result["views"]] == ["top", "iso"]


def test_curve_polylines_stay_within_their_tolerance(tmp_path):
    description = flange()
    # A radial hole through the hub. Its edges on the hub cylinder are not lines, circles, or ellipses.
    description["features"].append({"id": "radial", "type": "hole", "position": [25, 0, 22], "diameter": 8, "extent": "through",
                                     "axis": "-X", "evidence_ids": ["drawing"]})
    view = derive(candidate(description, tmp_path / "model"), normalize_requests([FRONT]))["views"][0]
    assert view["approximations"]
    assert all(item["max_error_mm"] <= item["tolerance_mm"] + 1e-6 for item in view["approximations"])
    ids = {item["id"] for item in view["geometry"]}
    assert all(set(item["primitive_ids"]) <= ids for item in view["approximations"])


def test_section_with_two_kept_pieces(tmp_path):
    """A U-shaped part cut above its bridge leaves two legs."""
    description = sample_description()
    description["parameters"][0]["value"] = 40
    description["features"][0].update(width=10, height=20)
    description["features"].append({"id": "slot", "type": "pocket", "profile": {"shape": "box", "length": 20, "width": 12, "depth": 15},
                                     "origin": [10, 11, 20], "axis": "-Z", "evidence_ids": ["drawing"]})
    description["measurements"][0]["expected"] = [40, 10, 20]
    section = {"id": "cut", "kind": "section", "up": [0, 1, 0],
               "cutting_plane": {"letter": "B", "origin": [0, 0, 12], "normal": [0, 0, -1], "viewing_side": "positive_normal",
                                 "source_view_id": "front"}}
    result = derive(candidate(description, tmp_path / "model"), normalize_requests([FRONT, section]))
    assert result["status"] == "pass", result
    assert len(result["views"][1]["hatching"]) == 2


def test_hatching_limits_of_the_contract(tmp_path, monkeypatch):
    from drawing2cad_mcp import view_derivation

    monkeypatch.setattr(view_derivation, "MAX_HATCH_BOUNDARY", 2)
    section = {"id": "section_a", "kind": "section", "up": [0, 0, 1],
               "cutting_plane": {"letter": "A", "origin": [0, 0, 0], "normal": [0, -1, 0], "viewing_side": "negative_normal",
                                 "source_view_id": "top"}}
    result = derive(candidate(flange(), tmp_path / "model"), normalize_requests([TOP, section]))
    assert result["status"] == "fail" and result["error"]["code"] == "VIEW_TOO_COMPLEX"


def test_oblique_section_keeps_exact_ellipses(tmp_path):
    """A section at 45 degrees through a cylinder cuts an ellipse."""
    description = sample_description()
    description["features"] = [{"id": "rod", "type": "cylinder", "operation": "base", "diameter": 20, "height": 40, "evidence_ids": ["drawing"]}]
    description["measurements"] = [{"id": "overall", "kind": "bbox", "basis": "printed_dimension", "expected": [20, 20, 40], "evidence_ids": ["drawing"]}]
    section = {"id": "cut", "kind": "section", "up": [0, 1, 0],
               "cutting_plane": {"letter": "C", "origin": [0, 0, 20], "normal": [1, 0, 1], "viewing_side": "positive_normal",
                                 "source_view_id": "front"}}
    result = derive(candidate(description, tmp_path / "model"), normalize_requests([FRONT, section]))
    assert result["status"] == "pass", result
    boundary = [item for item in result["views"][1]["geometry"] if item["style"] == "section"]
    assert [item["type"] for item in boundary] == ["ellipse"]
    ellipse = boundary[0]
    assert math.hypot(*ellipse["major_axis"]) == pytest.approx(10 * math.sqrt(2), abs=1e-6)
    assert ellipse["ratio"] == pytest.approx(1 / math.sqrt(2), abs=1e-6)


def test_existing_face_on_the_plane_is_not_a_cut_surface(tmp_path):
    section = {"id": "cut", "kind": "section", "up": [0, 1, 0],
               "cutting_plane": {"letter": "D", "origin": [0, 0, 10], "normal": [0, 0, 1], "viewing_side": "positive_normal",
                                 "source_view_id": "front"}}
    result = derive(candidate(asymmetric_block(), tmp_path / "model"), normalize_requests([FRONT, section]))
    assert result["status"] == "fail" and "cut surface" in result["error"]["message"]
