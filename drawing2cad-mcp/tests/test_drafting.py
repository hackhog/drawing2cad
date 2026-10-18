"""Synthetic drawing contracts and native DXF/PDF artifacts agree."""

import hashlib
import json
import math

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


def test_draft_and_fillet_notes_survive_dxf_and_pdf_render(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    pymupdf = pytest.importorskip("pymupdf")
    description, spec = drawing_fixture()
    texts = ["Inner walls: draft 3 deg toward floor.",
             "Inside floor joins: R1.5 mm, except marked transitions.",
             "Section A-A transitions: R3 mm at marked edges."]
    spec["notes"] = [{"text": text, "position": [15, 35 + 10 * index], "evidence_ids": ["drawing"]}
                     for index, text in enumerate(texts)]
    validated = drawing_validate(spec, description, 1)
    assert validated["status"] == "pass", validated
    assert [note["evidence_ids"] for note in validated["resolved"]["notes"]] == [["drawing"]] * 3
    assert validated["checks"]["source_accuracy"] == "not_tested"
    assert validated["checks"]["cad_equivalence"] == "not_tested"
    result = render_drawing(spec, description, 1, tmp_path)
    assert result["status"] == "pass", result
    entities = ezdxf.readfile(tmp_path / "drawing.dxf").modelspace()
    actual = {entity.dxf.text for entity in entities.query("TEXT")}
    assert set(texts) <= actual
    with pymupdf.open(tmp_path / "drawing.pdf") as document:
        page = document[0]
        for index in range(3):
            y = 35 + 10 * index
            clip = pymupdf.Rect(14 * page.rect.width / 297, (210 - y - 5) * page.rect.height / 210,
                                150 * page.rect.width / 297, (210 - y + 1) * page.rect.height / 210)
            raster = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=clip, colorspace=pymupdf.csGRAY)
            assert sum(value < 230 for value in raster.samples) > 20


def test_manufacturing_note_requires_known_source_evidence():
    description, spec = drawing_fixture()
    spec["notes"][0].update(text="Inner walls: draft 3 deg toward floor.", evidence_ids=["missing"])
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "fail"
    assert any(item["code"] == "unknown_evidence" and item["id"] == "note_0" for item in result["defects"])


def test_general_fillet_note_does_not_replace_native_round_dimension():
    description, spec = drawing_fixture()
    spec["views"][0]["dimensions"] = [spec["views"][0]["dimensions"][0]]
    spec["notes"][0]["text"] = "All round edges: R4 mm."
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "fail"
    assert any(item["code"] == "unmarked_radius" and item["id"] == "hole_circle" for item in result["defects"])


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


def test_missing_marker_names_status_and_link():
    description, spec = drawing_fixture()
    description["evidence"].append({**description["evidence"][0], "id": "length_estimate", "status": "assumed",
                                     "reason": "Synthetic estimate of the length."})
    description["parameters"][0]["evidence_ids"] = ["length_estimate"]
    spec["description_sha256"] = description_digest(description)
    defects = drawing_validate(spec, description, 1)["defects"]
    summary = next(d for d in defects if d["code"] == "unmarked_uncertainty")
    assert summary["evidence_ids"] == ["length_estimate"]
    assert "length_estimate (assumed)" in summary["message"]
    feature = next(d for d in defects if d["code"] == "unmarked_feature_uncertainty" and d["id"] == "base")
    assert feature["evidence_id"] == "length_estimate"
    assert "assumed evidence length_estimate" in feature["message"]
    assert "parameter length" in feature["message"]
    assert "Explicit evidence without a review flag needs no marker." in feature["message"]


def test_line_center_anchor_is_midpoint():
    description, spec = drawing_fixture()
    dimension = spec["views"][0]["dimensions"][0]
    dimension["p1"]["point"] = "center"
    dimension["expected"] = 30
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "pass", result
    assert result["measurements"][0]["actual"] == 30
    point = drawing_schema()["schema"]["$defs"]["Anchor"]["properties"]["point"]
    assert "Line: start, end, or center" in point["description"]


def test_layout_defects_give_sheet_bounds_and_view_transform():
    description, spec = drawing_fixture()
    spec["views"][0]["geometry"][0].update(end=[500, 0])
    clipping = next(d for d in drawing_validate(spec, description, 1)["defects"] if d["code"] == "geometry_clipping")
    assert clipping["local_bounds"] == [0, 0, 500, 0]
    assert clipping["sheet_bounds"] == [45, 120, 545, 120]
    assert clipping["frame"] == [15, 85, 150, 190]
    assert clipping["view_transform"]["origin"] == [45, 120]
    assert clipping["view_transform"]["scale"] == 1

    description, spec = drawing_fixture()
    spec["views"][0]["dimensions"][0].update(label_position=[300, 0])
    label = next(d for d in drawing_validate(spec, description, 1)["defects"] if d["code"] == "label_clipping")
    assert label["allowed_bounds"] == [15, 85, 150, 190]
    assert label["label_bounds"][0] > 150
    assert label["view_transform"]["view_id"] == "top"

    description, spec = drawing_fixture()
    spec["views"][0]["dimensions"][1].update(label_position=[30, -12])
    overlap = next(d for d in drawing_validate(spec, description, 1)["defects"] if d["code"] == "label_overlap")
    assert overlap["other_id"] == "hole_diameter"
    assert len(overlap["label_bounds"]) == len(overlap["other_bounds"]) == 4

    description, spec = drawing_fixture()
    spec["views"][1].update(frame=[15, 85, 150, 190])
    views = next(d for d in drawing_validate(spec, description, 1)["defects"] if d["code"] == "view_overlap")
    assert views["other_frame"] == [15, 85, 150, 190]


def test_marker_leader_through_label_is_layout_defect():
    description, spec = drawing_fixture()
    spec["uncertainty_markers"] = [{"id": "hole_mark", "view_id": "top", "primitive_id": "hole_circle",
                                    "position": [30, -25], "text": "Hole", "evidence_ids": ["drawing"]}]
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "fail"
    leader = next(d for d in result["defects"] if d["code"] == "leader_overlap")
    assert leader["id"] == "hole_mark"
    assert leader["other_id"] == "overall_length"
    assert leader["leader"] == [[75, 95], [75, 135]]
    spec["uncertainty_markers"][0]["position"] = [0, 50]
    assert drawing_validate(spec, description, 1)["status"] == "pass"


def test_leader_that_ends_below_a_label_is_not_a_crossing():
    description, spec = drawing_fixture()
    spec["views"][0]["dimensions"][1].update(label_position=[30, 15])
    spec["uncertainty_markers"] = [{"id": "hole_mark", "view_id": "top", "primitive_id": "hole_circle",
                                    "position": [0, 50], "text": "Hole", "evidence_ids": ["drawing"]}]
    result = drawing_validate(spec, description, 1)
    assert "leader_overlap" not in {d["code"] for d in result["defects"]}, result


def test_review_flag_on_explicit_evidence_does_not_contradict_message():
    description, spec = drawing_fixture()
    description["review_flags"] = [{"id": "size_review", "target_id": "base", "status": "open",
                                      "reason": "Check the size at its feature.", "evidence_ids": ["drawing"]}]
    spec["description_sha256"] = description_digest(description)
    defect = next(d for d in drawing_validate(spec, description, 1)["defects"] if d["code"] == "unmarked_feature_uncertainty")
    assert "flagged evidence drawing" in defect["message"]
    assert "review flag size_review" in defect["message"]
    assert "explicit evidence drawing" not in defect["message"]


def test_small_clipping_distance_stays_visible_in_defect():
    description, spec = drawing_fixture()
    spec["views"][0]["geometry"][0].update(end=[105.0004, 0])
    clipping = next(d for d in drawing_validate(spec, description, 1)["defects"] if d["code"] == "geometry_clipping")
    assert clipping["sheet_bounds"][2] > clipping["frame"][2]


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


def test_native_text_collision_has_source_ids_bounds_and_failed_preview(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pytest.importorskip("ezdxf")
    description, spec = drawing_fixture()
    # The native vertical text extends below its conservative declaration box.
    spec["notes"].append({"text": "A", "position": [250, 121], "evidence_ids": ["drawing"]})
    assert drawing_validate(spec, description, 1)["status"] == "pass"
    result = render_drawing(spec, description, 1, tmp_path)
    assert result["status"] == "fail"
    assert result["diagnostic_only"] is True
    assert result["drawing_sha256"] == description_digest(spec)
    diagnostic = result["diagnostics"]
    pair = next(pair for pair in diagnostic["collision_pairs"]
                if {pair["first_source_id"], pair["second_source_id"]} == {"height", "note_1"})
    assert all(len(pair[side + "_bounds_mm"]) == 4 for side in ("first", "second"))
    assert next(label for label in diagnostic["labels"] if label["source_id"] == "height")["view_id"] == "front"
    assert diagnostic["total_collision_pairs"] >= 1
    assert diagnostic["coordinate_system"] == {"units": "mm", "origin": "bottom_left", "positive_y": "up"}
    assert not (tmp_path / "drawing.dxf").exists()
    assert not (tmp_path / "drawing.pdf").exists()
    assert {artifact["role"] for artifact in result["artifacts"]} == {"drawing_diagnostic_preview", "drawing_diagnostic_report"}
    for artifact in result["artifacts"]:
        assert hashlib.sha256((tmp_path / artifact["name"]).read_bytes()).hexdigest() == artifact["sha256"]
    saved = json.loads((tmp_path / "drawing-diagnostic.json").read_text(encoding="utf-8"))
    assert saved["status"] == "fail" and saved["diagnostics"] == diagnostic
    with pymupdf.open(tmp_path / "drawing-diagnostic.pdf") as pdf:
        assert len(pdf) >= 2
        assert all("NOT FOR RELEASE" in page.get_text() for page in pdf)
        assert "height" in pdf[1].get_text() and "note_1" in pdf[1].get_text()
        assert any(path["color"] == (1, 0, 0) for path in pdf[0].get_drawings())
    # A layout-only repair creates ordinary deliverables without a diagnostic mark.
    fixed = tmp_path / "fixed"
    fixed.mkdir()
    spec["notes"][-1]["position"][1] = 116
    assert render_drawing(spec, description, 1, fixed)["status"] == "pass"
    assert (fixed / "drawing.dxf").exists()


def test_estimated_overlap_has_preview_without_bypassing_other_failures(tmp_path):
    pytest.importorskip("ezdxf")
    description, spec = drawing_fixture()
    spec["views"][0]["dimensions"][1]["label_position"] = [30, -12]
    result = render_drawing(spec, description, 1, tmp_path)
    assert result["status"] == "fail" and result["diagnostic_only"] is True
    assert any(item["code"] == "label_overlap" for item in result["defects"])
    assert (tmp_path / "drawing-diagnostic.pdf").exists()
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    spec["views"][0]["dimensions"][0]["expected"] = 100
    result = render_drawing(spec, description, 1, invalid)
    assert result["status"] == "fail" and not result.get("diagnostic_only", False)
    assert not list(invalid.iterdir())


def test_collision_report_bounds_pair_payload_and_work():
    from drawing2cad_mcp.drafting import _layout_diagnostics

    labels = [{"id": f"text_{index}", "source_id": f"source_{index}", "bounds_mm": [0, 0, 10, 10]}
              for index in range(800)]
    report = _layout_diagnostics(labels)
    assert len(report["collision_pairs"]) == 100
    assert len(report["labels"]) <= 100
    assert report["scanned_pair_count"] == 250000
    assert report["detected_collision_pairs"] == 250000
    assert report["total_collision_pairs"] is None
    assert report["scan_complete"] is False and report["truncated"] is True


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


@pytest.mark.parametrize("kind", ["radius", "diameter"])
@pytest.mark.parametrize("position", [[80, 15], [-10, 15], [30, 50], [30, -25]])
def test_moved_round_dimension_keeps_native_leader_to_text(tmp_path, kind, position):
    ezdxf = pytest.importorskip("ezdxf")
    pymupdf = pytest.importorskip("pymupdf")
    description, spec = drawing_fixture()
    dim = spec["views"][0]["dimensions"][1]
    dim.update(type=kind, expected=4 if kind == "radius" else 8, label_position=position)
    result = render_drawing(spec, description, 1, tmp_path)
    assert result["status"] == "pass", result
    document = ezdxf.readfile(tmp_path / "drawing.dxf")
    dimension = list(document.modelspace().query("DIMENSION"))[1]
    assert dimension.dimtype == (4 if kind == "radius" else 3)
    assert dimension.get_measurement() == dim["expected"]
    assert dimension.has_xdata("DRAWING2CAD")
    label = [45 + position[0], 120 + position[1]]
    center = [75, 135]
    distance = math.dist(center, label)
    direction = [(label[i] - center[i]) / distance for i in range(2)]
    # A rendered line must connect the circle boundary to the moved label area.
    # An intact diameter across the circle cannot satisfy this condition.
    def along(point):
        return sum((point[i] - center[i]) * direction[i] for i in range(2))
    leaders = [entity for entity in dimension.virtual_entities() if entity.dxftype() == "LINE"
               and min(along(entity.dxf.start), along(entity.dxf.end)) <= 6
               and max(along(entity.dxf.start), along(entity.dxf.end)) >= distance - 8]
    assert leaders, "Moved dimension text has no line to its dimensioned circle."
    # Verify that the PDF contains that same leader, not only the DXF block.
    scale = result["pdf_page"]["width_points"] / 297
    def pdf_point(point):
        return (point[0] * scale, (210 - point[1]) * scale)
    expected_lines = [(pdf_point(line.dxf.start), pdf_point(line.dxf.end)) for line in leaders]
    with pymupdf.open(tmp_path / "drawing.pdf") as pdf:
        strokes = [item for path in pdf[0].get_drawings() for item in path["items"] if item[0] == "l"]
    assert any(math.dist(start, tuple(item[1])) < 0.02 and math.dist(end, tuple(item[2])) < 0.02
               for start, end in expected_lines for item in strokes), "The PDF omitted the native dimension leader."


def test_hidden_and_center_lines_have_readable_metric_gaps_in_dxf_pdf_and_preview(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    pymupdf = pytest.importorskip("pymupdf")
    description, spec = drawing_fixture()
    for index, (style, length) in enumerate((("hidden", 10), ("hidden", 60), ("center", 10), ("center", 60))):
        y = 35 + index * 5
        spec["views"][0]["geometry"].append({"id": f"dash_example_{index}", "type": "line", "style": style,
            "start": [0, y], "end": [length, y], "evidence_ids": ["drawing"], "feature_ids": ["base"]})
    result = render_drawing(spec, description, 1, tmp_path)
    assert result["status"] == "pass", result
    document = ezdxf.readfile(tmp_path / "drawing.dxf")
    for name in ("HIDDEN", "CENTER"):
        layer = document.layers.get(name)
        pattern = [tag.value for tag in document.linetypes.get(layer.dxf.linetype).pattern_tags.tags if tag.code == 49]
        assert min(-value for value in pattern if value < 0) >= 1.0
        lengths = {value for value in pattern if value > 0}
        assert len(lengths) == (1 if name == "HIDDEN" else 2)
    with pymupdf.open(tmp_path / "drawing.pdf") as pdf:
        paths = [path for path in pdf[0].get_drawings() if path.get("layer") in {"hidden", "center"}]
        assert len(paths) == 4
        raster = pdf[0].get_pixmap(matrix=pymupdf.Matrix(150 / 72, 150 / 72), colorspace=pymupdf.csGRAY)
        mm_to_points = result["pdf_page"]["width_points"] / 297
        for path in paths:
            segments = sorted((min(item[1].x, item[2].x), max(item[1].x, item[2].x))
                              for item in path["items"] if item[0] == "l")
            assert len(segments) >= 2
            gaps = [(first[1], second[0]) for first, second in zip(segments, segments[1:])]
            assert min(end - start for start, end in gaps) / mm_to_points >= 0.99
            y = round(path["rect"].y0 * 150 / 72)
            for start, end in gaps:
                x = round((start + end) / 2 * 150 / 72)
                assert min(raster.pixel(x + dx, y + dy)[0] for dx in (-1, 0, 1) for dy in (-1, 0, 1)) >= 245
            ink_x = round(sum(segments[0]) / 2 * 150 / 72)
            assert min(raster.pixel(ink_x, y + dy)[0] for dy in (-1, 0, 1)) < 160
