"""Synthetic drawing contracts and native DXF/PDF artifacts agree."""

import hashlib

import pytest

from drawing2cad_mcp.drawing_contract import description_digest, drawing_schema, drawing_validate
from drawing2cad_mcp.drafting import render_drawing
from test_part_schema import sample_description


def drawing_fixture():
    description = sample_description()
    description["parameters"][0]["value"] = 60
    description["features"][0].update(width=30, height=10)
    description["features"].append({"id": "hole", "type": "hole", "position": [30, 15, 10], "diameter": 8,
                                     "extent": "through", "axis": "-Z", "evidence_ids": ["drawing"]})
    description["measurements"][0]["expected"] = [60, 30, 10]
    length = {"parameter": "length"}

    def line(identifier, start, end):
        return {"id": identifier, "type": "line", "start": start, "end": end,
                "evidence_ids": ["drawing"], "feature_ids": ["base"]}

    def rectangle(prefix, height):
        return [line(prefix + "bottom", [0, 0], [length, 0]), line(prefix + "right", [length, 0], [length, height]),
                line(prefix + "top", [length, height], [0, height]), line(prefix + "left", [0, height], [0, 0])]

    spec = {"schema_version": "1.0", "part_revision": 1, "description_sha256": description_digest(description),
            "units": "mm", "title": "Synthetic plate", "required_view_ids": ["top", "front"],
            "views": [{"id": "top", "label": "Top", "kind": "orthographic", "orientation": "top",
                       "origin": [45, 120], "frame": [15, 85, 150, 190], "geometry": rectangle("t_", 30) + [
                           {"id": "hole_circle", "type": "circle", "center": [30, 15], "radius": 4,
                            "evidence_ids": ["drawing"], "feature_ids": ["hole"]}],
                       "dimensions": [{"id": "overall_length", "type": "linear", "p1": {"primitive": "t_bottom", "point": "start"},
                                       "p2": {"primitive": "t_bottom", "point": "end"}, "expected": length,
                                       "label_position": [{"parameter": "length", "factor": 0.5}, -12], "evidence_ids": ["drawing"]},
                                      {"id": "hole_diameter", "type": "diameter", "primitive": "hole_circle", "expected": 8,
                                       "label_position": [80, 15], "evidence_ids": ["drawing"]}]},
                      {"id": "front", "label": "Front", "kind": "orthographic", "orientation": "front",
                       "origin": [175, 120], "frame": [155, 85, 280, 190], "geometry": rectangle("f_", 10),
                       "dimensions": [{"id": "height", "type": "linear", "axis": "vertical",
                                       "p1": {"primitive": "f_right", "point": "start"}, "p2": {"primitive": "f_right", "point": "end"},
                                       "expected": 10, "label_position": [75, 5], "evidence_ids": ["drawing"]}]}],
            "notes": [{"text": "Synthetic test geometry", "position": [15, 40], "evidence_ids": ["drawing"]}]}
    return description, spec


def test_drawing_contract_binds_part_and_declares_limits():
    description, spec = drawing_fixture()
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "pass", result
    assert [m["actual"] for m in result["measurements"]] == [60, 8, 10]
    assert result["checks"]["cad_equivalence"] == "not_tested"
    schema = drawing_schema()
    assert schema["schema"]["additionalProperties"] is False
    assert "automatic CAD projection" in schema["unsupported"]


def test_schema_distinguishes_absolute_sheet_and_local_view_positions():
    result = drawing_schema()
    coordinates = result["coordinates"]
    assert coordinates["sheet_origin"] == "bottom_left"
    assert coordinates["positive_y"] == "up"
    assert coordinates["frame_order"] == ["xmin", "ymin", "xmax", "ymax"]
    assert "views[].frame" in coordinates["absolute_sheet_fields"]
    definitions = result["schema"]["$defs"]
    assert "Absolute sheet bounds" in definitions["View"]["properties"]["frame"]["description"]
    assert "Absolute sheet" in definitions["Note"]["properties"]["position"]["description"]
    assert "Local view" in definitions["Marker"]["properties"]["position"]["description"]
    assert "Local view" in definitions["LinearDimension"]["properties"]["label_position"]["description"]


def test_scaled_nonzero_origin_preserves_absolute_frame_notes_and_dimension_values(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    description, spec = drawing_fixture()
    spec["views"][0]["scale"] = 0.5
    spec["uncertainty_markers"] = [{"id": "scaled_marker", "view_id": "top", "primitive_id": "hole_circle",
                                    "position": [0, 50], "text": "Review hole", "evidence_ids": ["drawing"]}]
    validated = drawing_validate(spec, description, 1)
    assert validated["status"] == "pass", validated
    resolved = validated["resolved"]
    assert list(resolved["views"][0]["frame"]) == [15, 85, 150, 190]
    labels = {label["id"]: label for label in resolved["labels"]}
    assert labels["overall_length"]["position"] == [60, 114]
    assert labels["note_0"]["position"] == [15, 40]
    assert labels["top_label"]["position"] == [17, 186]
    assert resolved["uncertainty_markers"][0]["position"] == [45, 145]
    assert resolved["uncertainty_markers"][0]["target"] == [60, 127.5]
    result = render_drawing(spec, description, 1, tmp_path)
    assert result["status"] == "pass", result
    entities = ezdxf.readfile(tmp_path / "drawing.dxf").modelspace()
    circle = list(entities.query('CIRCLE[layer=="VISIBLE"]'))[0]
    assert tuple(circle.dxf.center) == pytest.approx([60, 127.5, 0])
    assert circle.dxf.radius == 2
    dimension = list(entities.query("DIMENSION"))[0]
    assert dimension.get_measurement() == 30
    assert dimension.override().get("dimlfac") == 2
    note = next(entity for entity in entities.query("TEXT") if entity.dxf.text == "Synthetic test geometry")
    assert tuple(note.dxf.insert) == pytest.approx([15, 40, 0])
    leader = list(entities.query('LINE[layer=="UNCERTAINTY"]'))[0]
    assert tuple(leader.dxf.start) == pytest.approx([45, 145, 0])
    assert tuple(leader.dxf.end) == pytest.approx([60, 127.5, 0])


@pytest.mark.parametrize("mutation,code", [
    (lambda s: s.update(part_revision=2), "stale_binding"),
    (lambda s: s.update(description_sha256="0" * 64), "stale_binding"),
    (lambda s: s["required_view_ids"].append("section"), "required_views"),
    (lambda s: s["views"][0]["dimensions"][0].update(expected=61), "dimension_geometry"),
    (lambda s: s["views"][0]["dimensions"][1].update(expected=4), "dimension_geometry"),
    (lambda s: s["views"][0]["geometry"][0].update(end=[500, 0]), "geometry_clipping"),
    (lambda s: s["views"][0]["dimensions"][0].update(label_position=[300, 0]), "label_clipping"),
    (lambda s: s["views"][0]["dimensions"][1].update(label_position=[30, -12]), "label_overlap"),
    (lambda s: s["views"][0]["geometry"][0].update(feature_ids=["missing"]), "unknown_feature"),
    (lambda s: s["views"][0]["geometry"][0].update(evidence_ids=["missing"]), "unknown_evidence"),
    (lambda s: s["views"][0].update(kind="section"), "section_definition"),
    (lambda s: s["views"][0]["geometry"][0].update(start=[{"parameter": "missing"}, 0]), "geometry"),
    (lambda s: s.update(title="%%d"), "text_control"),
    (lambda s: s["views"][0]["dimensions"][0].update(id="sheet_title"), "duplicate_label_id"),
    (lambda s: s["views"][1].update(frame=[15, 85, 150, 190]), "view_overlap"),
])
def test_rejects_bad_drawing_declarations(mutation, code):
    description, spec = drawing_fixture()
    mutation(spec)
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "fail"
    assert code in {defect["code"] for defect in result["defects"]}, result


def test_parameter_change_requires_rebind_and_changes_geometry_and_dimensions():
    description, spec = drawing_fixture()
    description["parameters"][0]["value"] = 70
    assert drawing_validate(spec, description, 2)["status"] == "fail"
    spec.update(part_revision=2, description_sha256=description_digest(description))
    result = drawing_validate(spec, description, 2)
    assert result["status"] == "pass", result
    assert result["measurements"][0]["actual"] == 70
    assert result["resolved"]["views"][0]["geometry"][0]["end"] == [70, 0]


def test_assumed_geometry_needs_visible_linked_marker():
    description, spec = drawing_fixture()
    description["evidence"][0].update(status="assumed", reason="Synthetic estimate from nearby edges.")
    spec["description_sha256"] = description_digest(description)
    assert "unmarked_uncertainty" in {d["code"] for d in drawing_validate(spec, description, 1)["defects"]}
    spec["uncertainty_markers"] = [{"id": "uncertain_hole", "view_id": "top", "primitive_id": "hole_circle",
                                    "position": [0, 50], "text": "Hole size", "evidence_ids": ["drawing"]}]
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "fail"
    assert any(d["code"] == "unmarked_feature_uncertainty" and d["id"] == "base" for d in result["defects"])
    spec["uncertainty_markers"].append({"id": "uncertain_base", "view_id": "front", "primitive_id": "f_bottom",
                                        "position": [0, 50], "text": "Base size", "evidence_ids": ["drawing"]})
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "pass", result
    assert result["resolved"]["uncertainty_markers"][0]["text"] == "[assumed] Hole size"


@pytest.mark.parametrize("target", ["base", "length", "drawing"])
def test_review_flag_marker_covers_affected_feature(target):
    description, spec = drawing_fixture()
    description["review_flags"] = [{"id": "size_review", "target_id": target, "status": "open",
                                      "reason": "Check the size at its feature.", "evidence_ids": ["drawing"]}]
    spec["description_sha256"] = description_digest(description)
    spec["uncertainty_markers"] = [{"id": "hole_mark", "view_id": "top", "primitive_id": "hole_circle",
                                    "position": [0, 50], "text": "Hole review", "evidence_ids": ["drawing"]}]
    result = drawing_validate(spec, description, 1)
    assert any(d["code"] == "unmarked_feature_uncertainty" and d["id"] == "base" for d in result["defects"])
    spec["uncertainty_markers"].append({"id": "base_mark", "view_id": "front", "primitive_id": "f_bottom",
                                        "position": [0, 50], "text": "Base review", "evidence_ids": ["drawing"]})
    assert drawing_validate(spec, description, 1)["status"] == "pass"


def test_uncertain_parameter_marks_each_dependent_feature():
    description, spec = drawing_fixture()
    description["evidence"].append({**description["evidence"][0], "id": "length_estimate", "status": "assumed",
                                     "reason": "Synthetic estimate of the length."})
    description["parameters"][0]["evidence_ids"] = ["length_estimate"]
    spec["description_sha256"] = description_digest(description)
    spec["uncertainty_markers"] = [{"id": "wrong_feature", "view_id": "top", "primitive_id": "hole_circle",
                                    "position": [0, 50], "text": "Estimated size", "evidence_ids": ["drawing", "length_estimate"]}]
    result = drawing_validate(spec, description, 1)
    assert any(d["code"] == "unmarked_feature_uncertainty" and d["id"] == "base" for d in result["defects"])
    spec["uncertainty_markers"] = [{"id": "length_mark", "view_id": "front", "primitive_id": "f_bottom",
                                    "position": [0, 50], "text": "Length estimate", "evidence_ids": ["drawing", "length_estimate"]}]
    assert drawing_validate(spec, description, 1)["status"] == "pass"


def test_native_dxf_dimensions_and_matching_pdf(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    fitz = pytest.importorskip("pymupdf")
    description, spec = drawing_fixture()
    result = render_drawing(spec, description, 1, tmp_path)
    assert result["status"] == "pass", result
    document = ezdxf.readfile(tmp_path / "drawing.dxf")
    dims = list(document.modelspace().query("DIMENSION"))
    assert len(dims) == result["native_dimension_count"] == 3
    assert sorted(d.get_measurement() for d in dims) == pytest.approx([8, 10, 60])
    assert all(d.dxf.text == "<>" and d.dxf.geometry and d.has_xdata("DRAWING2CAD") for d in dims)
    with fitz.open(tmp_path / "drawing.pdf") as pdf:
        assert len(pdf) == 1
        # The pinned ezdxf PDF backend quantizes page dimensions to whole points.
        assert pdf[0].rect.width == int(297 / 25.4 * 72)
        assert pdf[0].rect.height == int(210 / 25.4 * 72)
        assert len(pdf[0].get_drawings()) > 10
        assert pdf[0].get_pixmap().samples != b""
    for artifact in result["artifacts"]:
        assert hashlib.sha256((tmp_path / artifact["name"]).read_bytes()).hexdigest() == artifact["sha256"]


def test_radius_angular_and_scaled_linear_dimensions(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    description, spec = drawing_fixture()
    view = spec["views"][0]
    view["dimensions"][1].update(type="radius", expected=4)
    view["geometry"].extend([
        {"id": "angle_first", "type": "line", "start": [0, 40], "end": [20, 40], "evidence_ids": ["drawing"], "feature_ids": ["base"]},
        {"id": "angle_second", "type": "line", "start": [0, 40], "end": [0, 60], "evidence_ids": ["drawing"], "feature_ids": ["base"]},
    ])
    view["dimensions"].append({"id": "angle", "type": "angular", "first_line": "angle_first", "second_line": "angle_second",
                               "expected": 90, "label_position": [15, 55], "evidence_ids": ["drawing"]})
    view["scale"] = 0.75
    result = render_drawing(spec, description, 1, tmp_path)
    assert result["status"] == "pass", result
    dimensions = list(ezdxf.readfile(tmp_path / "drawing.dxf").modelspace().query("DIMENSION"))
    linear = dimensions[0]
    assert linear.get_measurement() == 45
    assert linear.override().get("dimlfac") == pytest.approx(1 / 0.75)
    assert dimensions[1].dimtype == 4
    assert dimensions[2].dimtype == 5
    assert dimensions[2].get_measurement() == pytest.approx(90)


def test_no_artifacts_for_invalid_drawing(tmp_path):
    description, spec = drawing_fixture()
    spec["views"][0]["dimensions"][0]["expected"] = 100
    assert render_drawing(spec, description, 1, tmp_path)["status"] == "fail"
    assert not list(tmp_path.iterdir())


def test_reject_existing_artifact_before_write(tmp_path):
    pytest.importorskip("ezdxf")
    description, spec = drawing_fixture()
    (tmp_path / "drawing.pdf").write_bytes(b"existing")
    with pytest.raises(ValueError, match="must be empty"):
        render_drawing(spec, description, 1, tmp_path)
    assert (tmp_path / "drawing.pdf").read_bytes() == b"existing"


def test_sections_are_explicit_supplied_geometry():
    description, spec = drawing_fixture()
    view = spec["views"][0]
    view.update(kind="section", section_note="Section A-A; supplied cut geometry")
    view["geometry"][0]["style"] = "section"
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "pass", result
    assert result["checks"]["projection_completeness"] == "not_tested"


def test_undimensioned_radius_requires_targeted_marker():
    description, spec = drawing_fixture()
    spec["views"][0]["dimensions"].pop()
    assert "unmarked_radius" in {d["code"] for d in drawing_validate(spec, description, 1)["defects"]}
    spec["uncertainty_markers"] = [{"id": "radius_unknown", "view_id": "top", "primitive_id": "hole_circle",
                                    "position": [0, 50], "text": "Radius without dimension", "evidence_ids": ["drawing"]}]
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "pass", result


def test_parameter_change_regenerates_native_dimensions(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    description, spec = drawing_fixture()
    description["parameters"][0]["value"] = 70
    spec.update(part_revision=2, description_sha256=description_digest(description))
    result = render_drawing(spec, description, 2, tmp_path)
    assert result["status"] == "pass", result
    document = ezdxf.readfile(tmp_path / "drawing.dxf")
    dimensions = list(document.modelspace().query("DIMENSION"))
    assert dimensions[0].get_measurement() == 70
    assert result["part_revision"] == 2
    assert result["description_sha256"] == description_digest(description)


def test_arc_radius_dimension_leader_matches_sweep(tmp_path):
    description, spec = drawing_fixture()
    primitive = spec["views"][0]["geometry"][-1]
    primitive.update(type="arc", start_angle=0, end_angle=90)
    dimension = spec["views"][0]["dimensions"][-1]
    dimension.update(type="radius", expected=4)
    result = render_drawing(spec, description, 1, tmp_path)
    assert result["status"] == "pass", result
    primitive.update(start_angle=90, end_angle=180)
    result = drawing_validate(spec, description, 1)
    assert "dimension_geometry" in {d["code"] for d in result["defects"]}
