"""Drawing contract 2.0: projection, sections, sheet data, GPS profile, and the render gate."""

import copy
import math

import pytest

from drawing2cad_mcp.drawing_contract import drawing_schema, drawing_validate, render_gate
from drawing2cad_mcp.drawing_contract_v2 import GPS_PROFILE_ID, Projection, expected_matrix
from drawing2cad_mcp.drafting import render_drawing
from test_drafting import drawing_fixture


def projection(direction, up=(0.0, 0.0, 1.0), convention="isometric_drawing"):
    draft = Projection(view_direction=direction, up=up, scale_convention=convention, matrix=((1, 0, 0), (0, 1, 0)))
    rows = expected_matrix(draft)
    return {"view_direction": list(direction), "up": list(up), "scale_convention": convention,
            "matrix": [list(rows[0]), list(rows[1])]}


def isometric_view(**changes):
    view = {"id": "iso", "label": "Isometric", "kind": "isometric", "orientation": "isometric",
            "origin": [340, 130], "frame": [300, 100, 385, 165], "projection": projection((1.0, -1.0, 1.0)),
            "geometry": [{"id": "iso_edge", "type": "line", "start": [0, 0], "end": [20, 10],
                          "evidence_ids": ["drawing"], "feature_ids": ["base"]},
                         {"id": "iso_hole", "type": "ellipse", "center": [10, 15], "major_axis": [4.0, 0.0], "ratio": 0.58, "approximation_error": 0.0,
                          "evidence_ids": ["drawing"], "feature_ids": ["hole"]}],
            "dimensions": []}
    view.update(changes)
    return view


def section_view():
    def line(identifier, start, end):
        return {"id": identifier, "type": "line", "start": start, "end": end, "style": "section",
                "evidence_ids": ["drawing"], "feature_ids": ["base"]}
    return {"id": "section_a", "label": "Section A-A", "kind": "section", "orientation": "front",
            "origin": [80, 30], "frame": [60, 15, 160, 75],
            "projection": {"view_direction": [0, 1, 0], "up": [0, 0, 1], "scale_convention": "true_size",
                           "matrix": [[-1, 0, 0], [0, 0, 1]]},
            "cutting_plane": {"letter": "A", "origin": [0, 15, 0], "normal": [0, 1, 0], "viewing_side": "positive_normal",
                              "source_view_id": "top", "line": [[-5, 15], [65, 15]], "evidence_ids": ["drawing"]},
            "hatching": [{"boundary_primitive_ids": ["s_bottom", "s_right", "s_top", "s_left"]}],
            "geometry": [line("s_bottom", [0, 0], [60, 0]), line("s_right", [60, 0], [60, 10]),
                         line("s_top", [60, 10], [0, 10]), line("s_left", [0, 10], [0, 0])],
            "dimensions": []}


def complete_spec():
    description, spec = drawing_fixture()
    spec["schema_version"] = "2.0"
    # A3 sheet: the title block needs the bottom-right corner.
    spec["sheet"] = {"width": 420.0, "height": 297.0}
    spec["notes"] = []
    spec["views"][0]["projection"] = {"view_direction": [0, 0, 1], "up": [0, 1, 0], "scale_convention": "true_size",
                                      "matrix": [[1, 0, 0], [0, 1, 0]]}
    spec["views"] += [isometric_view(), section_view()]
    spec["title_block"] = {"legal_owner": "Example GmbH", "identification_number": "D-001", "date_of_issue": "2026-10-19",
                           "document_type": "Detail drawing", "creator": "Test", "approval_person": "Reviewer",
                           "sheet_number": "1/1"}
    spec["border"] = {"zone_grid": True}
    spec["projection_symbol"] = "first_angle"
    spec["datums"] = [{"letter": "A", "feature_ids": ["base"], "view_id": "front", "primitive_id": "f_bottom",
                       "evidence_ids": ["drawing"]}]
    spec["tolerance_frames"] = [
        {"id": "flat", "characteristic": "flatness", "value": 0.05, "feature_ids": ["base"], "view_id": "front",
         "primitive_id": "f_top", "position": [30, 20], "evidence_ids": ["drawing"]},
        {"id": "hole_position", "characteristic": "position", "value": 0.1, "zone": "diameter", "modifiers": ["M"],
         "datums": [{"letter": "A"}], "feature_ids": ["hole"], "view_id": "top", "primitive_id": "hole_circle",
         "position": [50, 25], "evidence_ids": ["drawing"]}]
    return description, spec


def codes(result):
    return {d["code"] for d in result["defects"]}


def test_complete_v2_drawing_passes_with_profile_status():
    description, spec = complete_spec()
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "pass", result["defects"]
    assert result["schema_version"] == "2.0"
    assert result["findings"] == []
    assert result["checks"]["isometric_projection"] == "pass"
    assert result["checks"]["gps_profile"] == "pass"
    assert result["checks"]["sheet_items"] == "pass"
    assert result["gps"]["profile"] == GPS_PROFILE_ID
    assert [f["status"] for f in result["gps"]["frames"]] == ["pass", "pass"]
    assert result["render_support"]["renderable"] is True


def test_isometric_label_without_projection_is_rejected():
    description, spec = complete_spec()
    spec["views"][2].pop("projection")
    result = drawing_validate(spec, description, 1)
    assert "projection_missing" in codes(result)
    assert result["checks"]["isometric_projection"] == "fail"


@pytest.mark.parametrize("direction", [(1.0, -1.0, 2.0), (1.0, -2.0, 3.0)])
def test_dimetric_and_trimetric_directions_fail(direction):
    description, spec = complete_spec()
    spec["views"][2]["projection"] = projection(direction)
    result = drawing_validate(spec, description, 1)
    assert "projection" in codes(result)


def test_distorted_matrix_fails():
    description, spec = complete_spec()
    spec["views"][2]["projection"]["matrix"][0][0] *= 1.1
    result = drawing_validate(spec, description, 1)
    assert "projection" in codes(result)


def test_isometric_projection_convention_uses_unit_factor():
    description, spec = complete_spec()
    spec["views"][2]["projection"] = projection((1.0, -1.0, 1.0), convention="isometric_projection")
    assert drawing_validate(spec, description, 1)["status"] == "pass"
    rows = expected_matrix(Projection(**spec["views"][2]["projection"]))
    assert math.isclose(math.hypot(rows[0][0], rows[1][0]), math.sqrt(2 / 3), rel_tol=1e-9)


def test_section_needs_cutting_plane_label_and_known_boundaries():
    description, spec = complete_spec()
    section = spec["views"][3]
    section["label"] = "Section B-B"
    section["hatching"][0]["boundary_primitive_ids"].append("missing")
    section["cutting_plane"]["line"] = [[-50, 15], [65, 15]]
    result = drawing_validate(spec, description, 1)
    assert {"section_label", "hatching", "cutting_plane"} <= codes(result)
    without = copy.deepcopy(spec)
    without["views"][3].pop("cutting_plane")
    assert "section_definition" in codes(drawing_validate(without, description, 1))


def test_gps_profile_defects_and_review():
    description, spec = complete_spec()
    frames = spec["tolerance_frames"]
    frames[0]["datums"] = [{"letter": "A"}]
    frames.append({"id": "perp", "characteristic": "perpendicularity", "value": 0.1, "feature_ids": ["base"],
                   "view_id": "front", "primitive_id": "f_right", "position": [70, 5], "evidence_ids": ["drawing"]})
    frames.append({"id": "profile", "characteristic": "surface_profile", "value": 0.2, "datums": [{"letter": "Z"}],
                   "feature_ids": ["base"], "view_id": "front", "primitive_id": "f_left", "position": [-5, 5],
                   "evidence_ids": ["drawing"]})
    result = drawing_validate(spec, description, 1)
    status = {frame["id"]: frame["status"] for frame in result["gps"]["frames"]}
    assert status["flat"] == "fail" and status["perp"] == "fail" and status["profile"] == "fail"
    assert result["checks"]["gps_profile"] == "fail"


def test_unsupported_gps_and_missing_sheet_items_need_review():
    description, spec = complete_spec()
    spec["unsupported_gps"] = [{"id": "lit", "literal_text": "Free-form profile per customer note",
                                "evidence_ids": ["drawing"], "reason": "No supported characteristic."}]
    spec["tolerance_frames"][1]["modifiers"] = ["P"]
    spec["title_block"]["approval_person"] = None
    del spec["border"]
    spec["views"] = spec["views"][:2] + spec["views"][3:]
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "pass", result["defects"]
    found = {f["code"] for f in result["findings"]}
    assert {"gps_unsupported", "title_block_field", "sheet_border", "sheet_isometric_view"} <= found
    assert result["checks"]["gps_profile"] == "needs_review"
    assert result["checks"]["sheet_items"] == "needs_review"
    assert result["checks"]["isometric_projection"] == "not_tested"


def test_v1_spec_rejects_v2_content_and_keeps_v1_behavior():
    description, spec = drawing_fixture()
    plain = drawing_validate(spec, description, 1)
    assert plain["status"] == "pass"
    assert "gps" not in plain and "isometric_projection" not in plain["checks"]
    assert plain["render_support"]["renderable"] is True
    spec["views"].append(isometric_view())
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "fail"
    assert result["defects"][0]["code"] == "schema_version"
    assert "views[iso].projection" in result["defects"][0]["fields"]


def test_render_gate_passes_version_2_content(tmp_path):
    description, spec = complete_spec()
    report = render_gate(drawing_validate(spec, description, 1))
    assert report["status"] == "pass" and report["render_support"] == {"renderable": True, "unsupported": []}
    result = render_drawing(spec, description, 1, tmp_path)
    assert result["status"] == "pass", result["defects"]


def test_schema_versions():
    assert drawing_schema()["schema_version"] == "1.0"
    second = drawing_schema("2.0")
    assert second["version_2"]["gps_profile"]["id"] == GPS_PROFILE_ID
    assert "Projection" in second["schema"]["$defs"]
    with pytest.raises(ValueError):
        drawing_schema("3.0")


@pytest.mark.parametrize("change, message", [
    ({"datums": [{"letter": "A"}, {"letter": "A"}]}, "datum"),
    ({"modifiers": ["M", "L"]}, "exclude"),
    ({"datums": [{"letter": "B"}]}, "Unknown datum"),
])
def test_invalid_frames_have_actionable_messages(change, message):
    description, spec = complete_spec()
    spec["tolerance_frames"][1].update(change)
    result = drawing_validate(spec, description, 1)
    frame = next(d for d in result["defects"] if d["id"] == "hole_position")
    assert frame["code"] == "gps_frame" and message.lower() in frame["message"].lower()


def test_open_hatching_unknown_cutting_evidence_and_missing_section_projection():
    description, spec = complete_spec()
    section = spec["views"][3]
    section["hatching"][0]["boundary_primitive_ids"] = ["s_bottom", "s_right", "s_top"]
    section["cutting_plane"]["evidence_ids"] = ["missing"]
    result = drawing_validate(spec, description, 1)
    assert "hatching" in codes(result) and "unknown_evidence" in codes(result)
    section.pop("projection")
    assert "section_definition" in codes(drawing_validate(spec, description, 1))


def test_section_direction_must_follow_the_normal():
    description, spec = complete_spec()
    spec["views"][3]["cutting_plane"]["viewing_side"] = "negative_normal"
    assert "cutting_plane" in codes(drawing_validate(spec, description, 1))


def test_datum_modifier_needs_review_not_schema_failure():
    description, spec = complete_spec()
    spec["tolerance_frames"][1]["datums"] = [{"letter": "A", "modifiers": ["P"]}]
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "pass", result["defects"]
    assert result["checks"]["gps_profile"] == "needs_review"


def test_version_1_schema_has_no_version_2_content():
    schema = drawing_schema("1.0")["schema"]
    text = str(schema)
    assert "Ellipse" not in text and "Projection" not in text and "theoretically_exact" not in text
    assert schema["properties"]["schema_version"]["const"] == "1.0"
    assert "isometric" not in schema["$defs"]["View"]["properties"]["kind"]["enum"]
    assert "title_block" not in schema["properties"]


def test_failures_keep_the_result_fields(tmp_path):
    description, spec = drawing_fixture()
    spec["views"].append(isometric_view())
    early = drawing_validate(spec, description, 1)
    broken = drawing_validate({"schema_version": "2.0"}, description, 1)
    for result in (early, broken):
        assert {"schema_version", "findings", "render_support"} <= set(result)
    _, complete = complete_spec()
    gated = render_gate(drawing_validate(complete, description, 1))
    # The renderer draws all 2.0 content, so the gate does not add a defect.
    assert gated["total_defects"] == 0 and "render_support" not in gated["checks"]


def test_repeated_hatching_boundary_fails():
    description, spec = complete_spec()
    spec["views"][3]["hatching"][0]["boundary_primitive_ids"] = ["s_bottom", "s_bottom"]
    assert "hatching" in codes(drawing_validate(spec, description, 1))


def test_version_2_schema_accepts_only_version_2():
    assert drawing_schema("2.0")["schema"]["properties"]["schema_version"]["const"] == "2.0"


def test_cutting_line_must_follow_the_plane_trace():
    description, spec = complete_spec()
    spec["views"][3]["cutting_plane"]["line"] = [[-5, 0], [65, 30]]
    assert "cutting_plane" in codes(drawing_validate(spec, description, 1))
    spec["views"][3]["cutting_plane"]["line"] = [[-5, 15], [65, 15]]
    spec["views"][3]["cutting_plane"]["normal"] = [0, 0, 1]
    spec["views"][3]["projection"] = {"view_direction": [0, 0, 1], "up": [0, 1, 0], "scale_convention": "true_size",
                                      "matrix": [[1, 0, 0], [0, 1, 0]]}
    assert "cutting_plane" in codes(drawing_validate(spec, description, 1))
    del spec["views"][0]["projection"]
    spec["views"][3]["cutting_plane"]["normal"] = [0, 1, 0]
    spec["views"][3]["projection"] = section_view()["projection"]
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "pass", result["defects"]
    assert "section_trace" in {f["code"] for f in result["findings"]}


def test_zero_tolerance_needs_material_condition():
    description, spec = complete_spec()
    spec["tolerance_frames"][1]["value"] = 0.0
    assert drawing_validate(spec, description, 1)["status"] == "pass"
    spec["tolerance_frames"][1]["modifiers"] = []
    assert "gps_frame" in codes(drawing_validate(spec, description, 1))


def test_invalid_datum_evidence_fails_the_gps_check():
    description, spec = complete_spec()
    spec["datums"][0]["evidence_ids"] = ["missing"]
    result = drawing_validate(spec, description, 1)
    assert result["checks"]["gps_profile"] == "fail"
    assert {f["id"]: f["status"] for f in result["gps"]["frames"]}["hole_position"] == "fail"


def test_schema_failure_is_not_a_render_support_defect():
    description, _ = complete_spec()
    report = render_gate(drawing_validate({"schema_version": "2.0"}, description, 1))
    assert [d["code"] for d in report["defects"]] == ["schema"]
