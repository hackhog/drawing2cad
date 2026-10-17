"""Drafted pockets and geometric edge selection use independent surface checks."""

import math
import json

import pytest

from drawing2cad_mcp.part_schema import parse_description, part_validate
from test_part_schema import sample_description


def pocket_description(taper=3):
    data = sample_description()
    data["schema_version"] = "1.1"
    data["features"][0].update(length=40, width=30, height=12)
    data["features"].append({"id": "cavity", "type": "pocket", "origin": [5, 25, 12],
        "axis": "-Z", "taper_angle": taper,
        "profile": {"shape": "box", "length": 30, "width": 20, "depth": 9},
        "evidence_ids": ["drawing"]})
    data["measurements"] = [{"id": "wall_draft", "kind": "draft_angle",
        "position": [5 + 4 * math.tan(math.radians(taper)), 15, 8], "axis": "Z",
        "expected": [abs(taper)], "tolerance": 0.001, "spatial_tolerance": 0.001,
        "basis": "printed_dimension", "evidence_ids": ["drawing"]}]
    return data


def add_floor_fillet(data, radius=1.5, count=4):
    data["features"].append({"id": "floor_blend", "type": "fillet", "size": radius,
        "selector": {"geometry": "any", "center_min": [0, 0, 0], "center_max": [40, 30, 12],
            "expected_count": count, "adjacent_plane": {"origin": [0, 0, 3], "normal": [0, 0, 1]}},
        "evidence_ids": ["drawing"]})


def kernel():
    pytest.importorskip("build123d")
    from drawing2cad_mcp.cad_kernel import build, build_shape
    from drawing2cad_mcp.cad_validation import validate_step
    return build, build_shape, validate_step


@pytest.mark.parametrize("taper", [3, -3])
def test_drafted_pocket_and_floor_blends_survive_step(tmp_path, taper):
    build, _, validate_step = kernel()
    data = pocket_description(taper)
    add_floor_fillet(data)
    # The center of the left fillet follows the intersection of the offset planes.
    angle = math.radians(taper)
    wall_at_floor = 5 + 9 * math.tan(angle)
    cx = wall_at_floor + 1.5 * (1 / math.cos(angle) - math.tan(angle))
    data["measurements"].append({"id": "floor_radius", "kind": "fillet_radius",
        "position": [cx - 1.5 / math.sqrt(2), 15, 4.5 - 1.5 / math.sqrt(2)],
        "axis": "Y", "expected": [1.5], "tolerance": 0.001, "spatial_tolerance": 0.001,
        "basis": "printed_dimension", "evidence_ids": ["drawing"]})
    result = build(data, tmp_path)
    assert result["status"] == "pass", result["checks"]
    assert validate_step(result["candidate_step"], data)["status"] == "pass"
    checks = {row["check"]: row for row in result["checks"]}
    assert checks["wall_draft"]["actual"] == pytest.approx([3])
    assert checks["floor_radius"]["actual"] == pytest.approx([1.5])


def test_wrong_draft_fails(tmp_path):
    build, _, _ = kernel()
    data = pocket_description()
    data["measurements"][0]["expected"] = [4]
    result = build(data, tmp_path)
    assert result["status"] == "fail"
    assert result["candidate_step"] is None
    assert next(row for row in result["checks"] if row["check"] == "wall_draft")["status"] == "fail"


@pytest.mark.parametrize("expected_radius", [3, 2.9])
def test_two_section_transitions_require_correct_radius(tmp_path, expected_radius):
    build, _, validate_step = kernel()
    data = sample_description()
    data["schema_version"] = "1.1"
    data["features"][0].update(width=12, height=12)
    data["features"].append({"id": "section_blends", "type": "fillet", "size": 3,
        "selector": {"geometry": "line", "center_min": [0, 6, 12], "center_max": [20, 6, 12],
            "expected_count": 2, "adjacent_plane": {"origin": [0, 0, 12], "normal": [0, 0, 2]}},
        "evidence_ids": ["drawing"]})
    data["measurements"] = [{"id": name, "kind": "fillet_radius", "position": position,
        "axis": "Y", "expected": [expected_radius], "tolerance": 0.001,
        "basis": "printed_dimension", "evidence_ids": ["drawing"]}
        for name, position in [("left_radius", [3 - 3 / math.sqrt(2), 6, 9 + 3 / math.sqrt(2)]),
                               ("right_radius", [17 + 3 / math.sqrt(2), 6, 9 + 3 / math.sqrt(2)])]]
    result = build(data, tmp_path)
    assert result["status"] == ("pass" if expected_radius == 3 else "fail")
    if expected_radius == 3:
        assert validate_step(result["candidate_step"], data)["status"] == "pass"
    else:
        assert result["candidate_step"] is None
        assert all(row["status"] == "fail" for row in result["checks"] if row.get("kind") == "fillet_radius")


@pytest.mark.parametrize("taper", [3, -3])
def test_cylinder_draft_preserves_axis_and_signed_volume(tmp_path, taper):
    build, _, validate_step = kernel()
    data = sample_description()
    data["schema_version"] = "1.1"
    data["features"] = [{"id": "boss", "type": "cylinder", "operation": "base", "diameter": 20,
        "height": 10, "origin": [4, 5, 6], "axis": "-X", "taper_angle": taper, "evidence_ids": ["drawing"]}]
    end_radius = 10 - 10 * math.tan(math.radians(taper))
    data["measurements"] = [
        {"id": "draft", "kind": "draft_angle", "position": [-1, 15 - 5 * math.tan(math.radians(taper)), 6],
         "axis": "-X", "expected": [3], "tolerance": 0.001, "basis": "printed_dimension", "evidence_ids": ["drawing"]},
        {"id": "signed_volume", "kind": "volume", "expected": [math.pi * 10 * (100 + 10 * end_radius + end_radius**2) / 3],
         "tolerance": 0.001, "basis": "independent_measurement", "evidence_ids": ["drawing"]}]
    result = build(data, tmp_path)
    assert result["status"] == "pass", result["checks"]
    assert validate_step(result["candidate_step"], data)["status"] == "pass"


@pytest.mark.parametrize("change", ["empty", "ambiguous"])
def test_floor_edge_selection_requires_exact_count(change):
    _, build_shape, _ = kernel()
    from drawing2cad_mcp.cad_kernel import CadBuildError
    data = pocket_description()
    add_floor_fillet(data)
    selector = data["features"][-1]["selector"]
    if change == "empty":
        selector["adjacent_plane"]["origin"][2] = 7
    else:
        selector["expected_count"] = 1
    with pytest.raises(CadBuildError) as exc:
        build_shape(data)
    assert exc.value.code == "EDGE_SELECTION"
    assert exc.value.feature_id == "floor_blend"
    payload = exc.value.as_dict()
    details = payload["details"]
    assert details["selected_count"] == (0 if change == "empty" else 4)
    assert len(details["selected_edges"]) == details["selected_count"]
    assert details["expected_count"] == selector["expected_count"]
    assert details["truncated"] is False
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload
    for edge in details["selected_edges"]:
        assert set(edge) == {"geometry", "center", "bbox_min", "bbox_max", "length_mm"}
        assert edge["geometry"] == "line"
        assert len(edge["center"]) == len(edge["bbox_min"]) == len(edge["bbox_max"]) == 3
        assert edge["length_mm"] > 0


@pytest.mark.parametrize("change", ["old_version", "zero_normal", "unknown_field", "angle", "wrong_unit"])
def test_closed_versioned_contract_rejects_invalid_draft(change):
    data = pocket_description()
    add_floor_fillet(data)
    if change == "old_version":
        data["schema_version"] = "1.0"
    elif change == "zero_normal":
        data["features"][-1]["selector"]["adjacent_plane"]["normal"] = [0, 0, 0]
    elif change == "unknown_field":
        data["features"][1]["profile"]["script"] = "invalid"
    elif change == "angle":
        data["features"][1]["taper_angle"] = 45
    else:
        data["features"][1]["taper_angle"] = {"parameter": "length"}
    assert part_validate(data)["status"] == "fail"


def test_line_arc_pocket_with_positive_taper(tmp_path):
    build, _, validate_step = kernel()
    data = pocket_description()
    data["features"][1].update(origin=[10, 15, 12], profile={"shape": "profile", "depth": 9, "segments": [
        {"kind": "line", "start": [0, -5], "end": [20, -5]},
        {"kind": "three_point_arc", "start": [20, -5], "mid": [25, 0], "end": [20, 5]},
        {"kind": "line", "start": [20, 5], "end": [0, 5]},
        {"kind": "three_point_arc", "start": [0, 5], "mid": [-5, 0], "end": [0, -5]}]})
    data["measurements"][0]["position"] = [20, 10 + 4 * math.tan(math.radians(3)), 8]
    result = build(data, tmp_path)
    assert result["status"] == "pass", result
    assert validate_step(result["candidate_step"], data)["status"] == "pass"
    data["features"][1]["profile"]["segments"][0]["end"] = [19, -5]
    assert "profile_gap" in {row["code"] for row in part_validate(data)["defects"]}


def test_cylindrical_taper_and_missing_surface_anchor(tmp_path):
    build, _, _ = kernel()
    data = pocket_description()
    data["features"][1].update(origin=[20, 15, 12], profile={"shape": "cylinder", "diameter": 20, "depth": 9})
    data["measurements"][0]["position"] = [30 - 4 * math.tan(math.radians(3)), 15, 8]
    assert build(data, tmp_path / "valid")["status"] == "pass"
    data["measurements"][0]["position"] = [100, 100, 100]
    result = build(data, tmp_path / "missing")
    assert result["status"] == "fail"
    assert next(row for row in result["checks"] if row["check"] == "wall_draft")["actual"] == []


def test_unsupported_surface_is_not_tested_and_blocks_export(tmp_path):
    pytest.importorskip("build123d")
    from build123d import Solid
    from drawing2cad_mcp.cad_kernel import export_shape
    data = pocket_description()
    data["measurements"][0]["position"] = [0, 0, 5]
    result = export_shape(Solid.make_sphere(5), data, tmp_path)
    assert result["status"] == "fail"
    assert result["candidate_step"] is None
    assert next(row for row in result["checks"] if row["check"] == "wall_draft")["status"] == "not_tested"


def test_legacy_description_remains_valid():
    assert parse_description(sample_description()).schema_version == "1.0"


@pytest.mark.parametrize("axis", ["Z", "-Z", "X", "-X", "Y", "-Y"])
@pytest.mark.parametrize("clockwise", [False, True])
def test_rounded_profile_taper_respects_winding_and_signed_axis(axis, clockwise):
    from test_profile_features import profile_description
    _, build_shape, _ = kernel()
    data = profile_description()
    data["features"][0].update(origin=[0, 0, 16], axis=axis, height=11.5, taper_angle=3)
    if clockwise:
        segments = data["features"][0]["segments"]
        data["features"][0]["segments"] = [{**segment, "start": segment["end"], "end": segment["start"]}
                                            for segment in reversed(segments)]
    shape, _ = build_shape(data)
    bounds = shape.bounding_box()
    index = "XYZ".index(axis[-1])
    origin = 16 if index == 2 else 0
    expected = [origin - 11.5, origin] if axis.startswith("-") else [origin, origin + 11.5]
    assert [tuple(bounds.min)[index], tuple(bounds.max)[index]] == pytest.approx(expected, abs=1e-6)


def test_profile_cut_schema_error_pointer_has_no_union_tag():
    data = pocket_description()
    data["features"][1]["profile"] = {"shape": "profile", "depth": "bad", "segments": [
        {"kind": "line", "start": [0, 0], "end": [1, 0]},
        {"kind": "line", "start": [1, 0], "end": [0, 0]}]}
    result = part_validate(data)
    assert result["status"] == "fail"
    assert {row["pointer"] for row in result["defects"]} == {"/features/1/profile/depth"}


@pytest.mark.parametrize("taper", [3, -3])
def test_fillet_radius_rejects_wrong_cylinder_axis(taper):
    _, build_shape, _ = kernel()
    from drawing2cad_mcp.cad_validation import measure_shape
    data = pocket_description(taper)
    add_floor_fillet(data)
    angle = math.radians(taper)
    cx = 5 + 9 * math.tan(angle) + 1.5 * (1 / math.cos(angle) - math.tan(angle))
    data["measurements"] = [{"id": "radius", "kind": "fillet_radius", "position": [
        cx - 1.5 / math.sqrt(2), 15, 4.5 - 1.5 / math.sqrt(2)], "axis": "X",
        "expected": [1.5], "basis": "printed_dimension", "evidence_ids": ["drawing"]}]
    result = measure_shape(build_shape(data)[0], parse_description(data))
    check = next(row for row in result["checks"] if row["check"] == "radius")
    assert check["status"] == "fail"
    assert check["actual"] == []


@pytest.mark.parametrize("axis,status", [("Z", "pass"), ("-Z", "pass"), ("X", "fail")])
def test_toroidal_radius_requires_its_axis(axis, status):
    pytest.importorskip("build123d")
    from build123d import Solid
    from drawing2cad_mcp.cad_validation import measure_shape
    data = sample_description()
    data["schema_version"] = "1.1"
    data["measurements"] = [{"id": "radius", "kind": "fillet_radius", "position": [12, 0, 0],
        "axis": axis, "expected": [2], "basis": "printed_dimension", "evidence_ids": ["drawing"]}]
    result = measure_shape(Solid.make_torus(10, 2), parse_description(data))
    assert result["status"] == status


@pytest.mark.parametrize("axis", ["X", "Y", "Z"])
def test_spherical_radius_is_direction_independent(axis):
    pytest.importorskip("build123d")
    from build123d import Solid
    from drawing2cad_mcp.cad_validation import measure_shape
    data = sample_description()
    data["schema_version"] = "1.1"
    data["measurements"] = [{"id": "radius", "kind": "fillet_radius", "position": [3, 0, 0],
        "axis": axis, "expected": [3], "basis": "printed_dimension", "evidence_ids": ["drawing"]}]
    assert measure_shape(Solid.make_sphere(3), parse_description(data))["status"] == "pass"


def test_edge_selection_diagnostics_are_bounded():
    pytest.importorskip("build123d")
    from build123d import Edge
    from drawing2cad_mcp.cad_kernel import _edge_selection_details
    edges = [Edge.make_line((i, 0, 0), (i, 1, 0)) for i in range(70)]
    details = _edge_selection_details(edges, 1)
    assert details["selected_count"] == 70
    assert len(details["selected_edges"]) == 64
    assert details["truncated"] is True
    assert json.loads(json.dumps(details, allow_nan=False)) == details


def test_worker_preserves_structured_edge_selection_diagnostics(monkeypatch, capsys):
    import io
    from types import SimpleNamespace
    from drawing2cad_mcp import cad_worker
    from drawing2cad_mcp.cad_kernel import CadBuildError
    details = {"expected_count": 1, "selected_count": 0, "selected_edges": [], "truncated": False}

    def fail(_request):
        raise CadBuildError("EDGE_SELECTION", "No edge matches.", "blend", details=details)

    monkeypatch.setattr(cad_worker, "execute", fail)
    monkeypatch.setattr(cad_worker.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"{}")))
    cad_worker.main()
    result = json.loads(capsys.readouterr().out.removeprefix(cad_worker.PREFIX))
    assert result["error"]["details"] == details
    assert result["error"]["feature_id"] == "blend"


@pytest.mark.parametrize("mode,status", [("valid", "pass"), ("wrong_radius", "fail"), ("wrong_section", "fail"), ("missing_section", "not_tested"), ("boundary", "not_tested")])
def test_bspline_fillet_measures_actual_local_curvature(mode, status):
    pytest.importorskip("build123d")
    from build123d import Solid
    from drawing2cad_mcp.cad_validation import measure_shape
    from OCP.BRepBuilderAPI import BRepBuilderAPI_NurbsConvert
    shape = Solid.cast(BRepBuilderAPI_NurbsConvert(Solid.make_torus(10, 1.5).wrapped, True).Shape())
    assert any(face.geom_type.name.lower() == "bspline" for face in shape.faces())
    u, v = 0.4, 0.6
    if mode == "boundary":
        u = 0.00001
    radial = 10 + 1.5 * math.cos(v)
    data = sample_description()
    data["schema_version"] = "1.1"
    measurement = {"id": "radius", "kind": "fillet_radius",
        "position": [radial * math.cos(u), radial * math.sin(u), 1.5 * math.sin(v)],
        "axis": "Z", "fillet_section_normal": [-math.sin(u), math.cos(u), 0], "expected": [1.5],
        "tolerance": 0.02, "basis": "printed_dimension", "evidence_ids": ["drawing"]}
    if mode == "wrong_radius":
        measurement["expected"] = [1.7]
    elif mode == "wrong_section":
        measurement["fillet_section_normal"] = [0, 0, 1]
    elif mode == "missing_section":
        del measurement["fillet_section_normal"]
    data["measurements"] = [measurement]
    result = measure_shape(shape, parse_description(data))
    row = next(row for row in result["checks"] if row["check"] == "radius")
    assert row["status"] == status, row
    if mode in {"valid", "wrong_radius"}:
        assert row["actual"] == pytest.approx([1.5] * 5, abs=0.02)
        assert row["surface_sampling"][0]["sample_count"] == 5
    assert result["status"] == ("pass" if status == "pass" else "fail")


def test_bspline_sphere_has_no_separated_fillet_curvature():
    pytest.importorskip("build123d")
    from build123d import Solid
    from drawing2cad_mcp.cad_validation import measure_shape
    data = sample_description()
    data["schema_version"] = "1.1"
    data["measurements"] = [{"id": "radius", "kind": "fillet_radius", "position": [2, 2, 1],
        "axis": "Z", "fillet_section_normal": [0, 1, 0], "expected": [3],
        "basis": "printed_dimension", "evidence_ids": ["drawing"]}]
    from OCP.BRepBuilderAPI import BRepBuilderAPI_NurbsConvert
    shape = Solid.cast(BRepBuilderAPI_NurbsConvert(Solid.make_sphere(3).wrapped, True).Shape())
    result = measure_shape(shape, parse_description(data))
    row = next(row for row in result["checks"] if row["check"] == "radius")
    assert row["status"] == "not_tested"


@pytest.mark.parametrize("normal", [[0, 0, 0], [float("nan"), 0, 1]])
def test_fillet_section_normal_must_be_finite_and_nonzero(normal):
    data = pocket_description()
    data["measurements"][0].update(kind="fillet_radius", fillet_section_normal=normal)
    assert part_validate(data)["status"] == "fail"


def test_failed_section_sample_cannot_be_hidden_by_another_surface(monkeypatch):
    pytest.importorskip("build123d")
    from build123d import Solid
    from drawing2cad_mcp import cad_validation
    data = pocket_description()
    data["measurements"][0].update(kind="fillet_radius", expected=[1.5])
    monkeypatch.setattr(cad_validation, "_draft_or_fillet_values", lambda *_: ([1.5], False, [{"status": "fail"}]))
    result = cad_validation.measure_shape(Solid.make_box(40, 30, 12), parse_description(data))
    assert result["status"] == "fail"


def test_curvature_calculation_error_is_not_tested(monkeypatch):
    pytest.importorskip("build123d")
    from build123d import Solid
    from OCP.BRepBuilderAPI import BRepBuilderAPI_NurbsConvert
    from drawing2cad_mcp import cad_validation
    shape = Solid.cast(BRepBuilderAPI_NurbsConvert(Solid.make_torus(10, 1.5).wrapped, True).Shape())
    data = pocket_description()
    data["measurements"][0].update(kind="fillet_radius", position=[11.5, 0, 0], expected=[1.5])

    def fail(*_args):
        raise RuntimeError("Synthetic numerical failure.")

    monkeypatch.setattr(cad_validation, "_sample_fillet_curvature", fail)
    result = cad_validation.measure_shape(shape, parse_description(data))
    row = next(row for row in result["checks"] if row["check"] == "wall_draft")
    assert row["status"] == "not_tested"
    assert result["status"] == "fail"


def test_nonconstant_section_radius_is_not_tested():
    pytest.importorskip("build123d")
    from build123d import Edge, Face, Solid, Wire
    from OCP.BRepBuilderAPI import BRepBuilderAPI_NurbsConvert
    from drawing2cad_mcp.cad_validation import measure_shape
    shape = Solid.extrude(Face(Wire(Edge.make_ellipse(10, 2))), (0, 0, 10))
    shape = Solid.cast(BRepBuilderAPI_NurbsConvert(shape.wrapped, True).Shape())
    u = 0.6
    radius = (100 * math.sin(u)**2 + 4 * math.cos(u)**2)**1.5 / 20
    data = pocket_description()
    data["measurements"][0].update(kind="fillet_radius", position=[10 * math.cos(u), 2 * math.sin(u), 5],
        axis="Z", fillet_section_normal=[0, 0, 1], expected=[radius])
    result = measure_shape(shape, parse_description(data))
    row = next(row for row in result["checks"] if row["check"] == "wall_draft")
    assert row["status"] == "not_tested", row
    assert row["surface_sampling"][0]["sample_count"] == 5
    assert row["surface_sampling"][0]["radius_spread_mm"] > data["measurements"][0]["tolerance"]


def test_section_normal_does_not_enable_conical_fillet_measurement():
    pytest.importorskip("build123d")
    from build123d import Solid
    from drawing2cad_mcp.cad_validation import measure_shape
    data = pocket_description()
    data["measurements"][0].update(kind="fillet_radius", position=[9.5, 0, 5], axis="Z",
        fillet_section_normal=[0, 0, 1], expected=[9.5])
    result = measure_shape(Solid.make_cone(10, 9, 10), parse_description(data))
    row = next(row for row in result["checks"] if row["check"] == "wall_draft")
    assert row["status"] == "not_tested"
