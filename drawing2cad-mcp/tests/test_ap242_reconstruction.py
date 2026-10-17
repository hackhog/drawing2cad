"""Synthetic AP242 construction tests; native target CAD remains untested."""

from pathlib import Path

import pytest

pytest.importorskip("build123d")

from drawing2cad_mcp.adapters.ap242 import reconstruct_step
from drawing2cad_mcp.adapters.construction import embed_construction, read_construction
from drawing2cad_mcp.adapters.p21 import sth_p21_parse, sth_p21_record
from drawing2cad_mcp.cad_kernel import build
from drawing2cad_mcp.cad_validation import validate_step
from test_part_schema import sample_description


def test_ap242_rebuild_edit_and_repeat_from_step_only(tmp_path):
    description = sample_description()
    description["measurements"] = []
    first = build(description, tmp_path / "first", export_profile="ap242")
    assert first["status"] == "pass", first
    assert first["step"]["schemas"][0].startswith("AP242_MANAGED_MODEL_BASED_3D_ENGINEERING")
    edited = reconstruct_step(first["candidate_step"], tmp_path / "edited", {"length": 30})
    assert edited["status"] == "pass", edited
    assert edited["construction"]["original_agreement"] == "pass"
    assert edited["measured"]["bbox_size"] == pytest.approx([30, 10, 5])
    repeated = reconstruct_step(edited["candidate_step"], tmp_path / "repeated")
    assert repeated["status"] == "pass", repeated
    assert repeated["description"]["parameters"][0]["value"] == 30
    assert repeated["measured"]["volume_mm3"] == pytest.approx(1500)
    assert validate_step(repeated["candidate_step"], repeated["description"])["status"] == "pass"


def test_thread_length_survives_ap242_replay_without_changing_legacy_payload(tmp_path):
    description = sample_description()
    description["schema_version"] = "1.2"
    description["features"][0]["height"] = 20
    description["measurements"] = []
    description["features"].append({"id": "tap", "type": "hole", "position": [5, 5, 20],
                                    "diameter": 5, "extent": "blind", "depth": 14,
                                    "thread": {"designation": "M6", "pitch": 1, "length": 9},
                                    "evidence_ids": ["drawing"]})
    built = build(description, tmp_path / "first", export_profile="ap242")
    assert built["status"] == "pass"
    recipe = read_construction(Path(built["candidate_step"]).read_text())["description"]
    assert recipe["features"][1]["thread"]["length"] == 9
    replayed = reconstruct_step(built["candidate_step"], tmp_path / "replayed")
    assert replayed["status"] == "pass"
    assert replayed["description"]["features"][1]["thread"]["length"] == 9

    legacy = sample_description()
    legacy["features"].append({"id": "tap", "type": "hole", "position": [5, 5, 5],
                               "diameter": 3.3, "extent": "blind", "depth": 3,
                               "thread": {"designation": "M4", "pitch": 0.7},
                               "evidence_ids": ["drawing"]})
    legacy["measurements"] = []
    legacy_step = build(legacy, tmp_path / "legacy", export_profile="ap242")
    assert legacy_step["status"] == "pass"
    legacy_recipe = read_construction(Path(legacy_step["candidate_step"]).read_text())["description"]
    assert "length" not in legacy_recipe["features"][1]["thread"]


def test_parameter_edit_rejects_stale_source_expectations(tmp_path):
    original = build(sample_description(), tmp_path / "first", export_profile="ap242")
    result = reconstruct_step(original["candidate_step"], tmp_path / "edited", {"length": 30})
    assert result["status"] == "fail"
    assert result["candidate_step"] is None
    assert any(row["check"] == "overall" and row["status"] == "fail" for row in result["checks"])


def test_ordered_hole_pocket_and_fillet_features_survive_step_only_replay(tmp_path):
    description = sample_description()
    description["features"].extend([
        {"id": "bore", "type": "hole", "position": [5, 5, 5], "diameter": 3, "evidence_ids": ["drawing"]},
        {"id": "recess", "type": "pocket", "profile": {"shape": "box", "length": 3, "width": 3, "depth": 2}, "origin": [12, 2, 3], "evidence_ids": ["drawing"]},
        {"id": "round", "type": "fillet", "size": 0.5, "selector": {"geometry": "line", "center_min": [20, 5, 5], "center_max": [20, 5, 5], "expected_count": 1}, "evidence_ids": ["drawing"]},
    ])
    built = build(description, tmp_path / "first", export_profile="ap242")
    assert built["status"] == "pass", built
    repeated = reconstruct_step(built["candidate_step"], tmp_path / "repeated")
    assert repeated["status"] == "pass", repeated
    assert [item["id"] for item in repeated["description"]["features"]] == ["base", "bore", "recess", "round"]
    assert [item["feature_id"] for item in repeated["feature_results"]] == ["base", "bore", "recess", "round"]
    assert repeated["construction"]["original_feature_count"] == 4


def test_different_hole_position_with_equal_volume_and_bbox_is_rejected(tmp_path):
    description = sample_description()
    description["features"].append({"id": "bore", "type": "hole", "position": [5, 5, 5], "diameter": 3, "evidence_ids": ["drawing"]})
    built = build(description, tmp_path / "first", export_profile="ap242")
    raw = Path(built["candidate_step"]).read_text()
    records = sth_p21_parse(raw)
    # Remove only the application property, then bind a different valid recipe.
    # A valid payload hash alone must not establish correspondence with the BREP.
    property_id = next(i for i, (kind, args) in records.items() if kind == "PROPERTY_DEFINITION" and args[0] == "drawing2cad.construction.v1")
    original = raw[:raw.index("DATA;") + 5] + "\n" + "\n".join(sth_p21_record(i, *value) for i, value in records.items() if i < property_id) + "\nENDSEC;\nEND-ISO-10303-21;\n"
    description["features"][-1]["position"] = [15, 5, 5]
    forged, _ = embed_construction(original, description)
    path = tmp_path / "mismatch.step"
    path.write_text(forged)
    assert read_construction(forged)["description"]["features"][-1]["position"] == [15, 5, 5]
    result = reconstruct_step(path, tmp_path / "rejected")
    assert result["status"] == "fail"
    assert result["construction"]["original_agreement"] == "fail"
    assert result["checks"][0]["original_only_volume_mm3"] > 1
    assert not (tmp_path / "rejected" / "candidate.step").exists()


def test_existing_pmi_cannot_be_silently_dropped_by_null_recipe_spec(tmp_path):
    from build123d import Solid
    from drawing2cad_mcp.adapters.semantic_pmi import export_ap242
    from test_semantic_pmi import cylinder_case
    description, pmi = cylinder_case()
    source = tmp_path / "pmi.step"
    export_ap242(Solid.make_cylinder(10, 30), source, description["name"], pmi, description)
    combined, _ = embed_construction(source.read_text(), description, pmi=None)
    source.write_text(combined)
    with pytest.raises(ValueError, match="count"):
        reconstruct_step(source, tmp_path / "rejected")
    assert not (tmp_path / "rejected" / "candidate.step").exists()


def test_product_name_cannot_silently_change_on_reconstruction(tmp_path):
    result = build(sample_description(), tmp_path / "first", export_profile="ap242")
    path = Path(result["candidate_step"])
    original = path.read_text()
    modified = original.replace("'Synthetic plate'", "'Other product'")
    assert modified != original
    path.write_text(modified)
    with pytest.raises(ValueError, match="linked product name"):
        reconstruct_step(path, tmp_path / "rejected")
