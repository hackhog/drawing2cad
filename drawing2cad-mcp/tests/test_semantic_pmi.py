"""Actual XDE export and read-back tests for the supported nominal PMI profile."""
from copy import deepcopy
from pathlib import Path

import pytest
pytest.importorskip("build123d")
from build123d import Solid
from drawing2cad_mcp.adapters.semantic_pmi import export_ap242, read_ap242_pmi, validate_pmi, pmi_schema, verify_ap242_pmi
from test_part_schema import sample_description


def cylinder_case():
    description = sample_description()
    description["features"] = [{"id": "base", "type": "cylinder", "operation": "base", "diameter": 20, "height": 30, "evidence_ids": ["drawing"]}]
    description["measurements"] = []
    annotation = {"origin": [15, 0, 35], "normal": "Y", "x_axis": "X", "text_height": 2.5}
    spec = {"schema_version": "drawing2cad.pmi/1", "dimensions": [
        {"id": "diameter", "kind": "diameter", "feature_id": "base", "evidence_ids": ["drawing"], "value": 20,
         "targets": [{"surface": "cylinder", "axis": "Z", "origin": [0, 0, 0], "radius": 10}], "annotation": annotation},
        {"id": "height", "kind": "linear", "feature_id": "base", "evidence_ids": ["drawing"], "value": 30,
         "targets": [{"surface": "plane", "axis": "Z", "origin": [0, 0, 0]}, {"surface": "plane", "axis": "Z", "origin": [0, 0, 30]}],
         "annotation": {**annotation, "origin": [15, 0, 10]}}
    ]}
    return description, spec


def test_actual_semantic_and_graphical_roundtrip(tmp_path):
    part, spec = cylinder_case()
    path = tmp_path / "nominal.step"
    report = export_ap242(Solid.make_cylinder(10, 30), path, "PMI cylinder", spec, part)
    text = path.read_text()
    assert "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING" in text
    for entity in ["DIMENSIONAL_SIZE", "DIMENSIONAL_LOCATION", "GEOMETRIC_ITEM_SPECIFIC_USAGE", "DRAUGHTING_MODEL_ITEM_ASSOCIATION", "TESSELLATED_ANNOTATION_OCCURRENCE"]:
        assert entity in text
    read = read_ap242_pmi(path)
    assert {d["id"] for d in read} == {"diameter", "height"}, read
    assert sorted(d["value"] for d in read) == [20, 30]
    assert sorted(len(d["references"]) for d in read) == [1, 2]
    assert all(all(r["is_face"] for r in d["references"]) for d in read)
    assert all(d["has_plane"] and d["presentation_edges"] > 5 for d in read)
    assert report["target_cad_opening"] == "not_tested"
    assert verify_ap242_pmi(path, spec, part)["status"] == "pass"


@pytest.mark.parametrize("mutation,match", [
    (lambda s: s["dimensions"][0].update(value=21), "does not match"),
    (lambda s: s["dimensions"][0]["targets"][0].update(radius=11), "exactly one"),
    (lambda s: s["dimensions"][0].update(feature_id="missing"), "Unknown PMI feature"),
    (lambda s: s["dimensions"][0].update(evidence_ids=["missing"]), "evidence"),
])
def test_bad_association_rejected(tmp_path, mutation, match):
    part, spec = cylinder_case()
    mutation(spec)
    with pytest.raises(ValueError, match=match):
        export_ap242(Solid.make_cylinder(10, 30), tmp_path / "bad.step", "bad", spec, part)


def test_ambiguous_plane_rejected(tmp_path):
    from build123d import Location
    part, spec = cylinder_case()
    spec["dimensions"] = spec["dimensions"][1:]
    shape = Solid.make_cylinder(10, 30).fuse(Location((30, 0, 0)) * Solid.make_cylinder(10, 30))
    with pytest.raises(ValueError, match="exactly one"):
        export_ap242(shape, tmp_path / "bad.step", "bad", spec, part)


def test_uncertain_evidence_is_explicit():
    part, spec = cylinder_case()
    part["evidence"][0]["status"] = "assumed"
    with pytest.raises(ValueError, match="acknowledgement"):
        validate_pmi(spec, part)
    for dim in spec["dimensions"]:
        dim["uncertainty_acknowledged"] = True
    validate_pmi(spec, part)
    part["evidence"][0]["status"] = "unresolved"
    with pytest.raises(ValueError, match="[Uu]nresolved"):
        validate_pmi(spec, part)


def test_schema_is_closed():
    assert pmi_schema()["additionalProperties"] is False



def test_imported_missing_or_wrong_pmi_rejected(tmp_path):
    part, spec = cylinder_case()
    path = tmp_path / "wrong.step"
    export_ap242(Solid.make_cylinder(10, 30), path, "PMI cylinder")
    with pytest.raises(ValueError, match="count"):
        verify_ap242_pmi(path, spec, part)
    export_ap242(Solid.make_cylinder(10, 30), path, "PMI cylinder", spec, part)
    wrong = deepcopy(spec)
    wrong["dimensions"][0]["value"] = 22
    with pytest.raises(ValueError, match="value mismatch"):
        verify_ap242_pmi(path, wrong, part)
    wrong = deepcopy(spec)
    wrong["dimensions"][0]["targets"][0]["origin"][0] = 1
    with pytest.raises(ValueError, match="exactly one"):
        verify_ap242_pmi(path, wrong, part)


def test_assumptions_survive_as_standard_semantic_descriptions(tmp_path):
    part, spec = cylinder_case()
    part["evidence"][0]["status"] = "assumed"
    part["evidence"][0]["reason"] = "Missing diameter inferred from source geometry."
    for dim in spec["dimensions"]:
        dim["uncertainty_acknowledged"] = True
    path = tmp_path / "assumed.step"
    export_ap242(Solid.make_cylinder(10, 30), path, "PMI cylinder", spec, part)
    records = read_ap242_pmi(path)
    assert all(d["descriptions"]["drawing2cad evidence drawing"].startswith("assumed: Missing diameter") for d in records)
    report = verify_ap242_pmi(path, spec, part)
    assert all(d["evidence_statuses"] == {"drawing": "assumed"} for d in report["dimensions"])



@pytest.mark.parametrize("entity", ["DATUM", "GEOMETRIC_TOLERANCE", "ANGULAR_SIZE", "DIMENSIONAL_SIZE_WITH_PATH"])
def test_unsupported_semantic_entities_rejected(tmp_path, entity):
    part, spec = cylinder_case()
    path = tmp_path / "unsupported.step"
    export_ap242(Solid.make_cylinder(10, 30), path, "PMI cylinder", spec, part)
    text = path.read_text().replace("ENDSEC;\nEND-ISO-10303-21;", "#9999 = " + entity + "('unsupported');\nENDSEC;\nEND-ISO-10303-21;")
    path.write_text(text)
    with pytest.raises(ValueError, match="Unsupported semantic"):
        verify_ap242_pmi(path, spec, part)


def test_duplicate_detached_association_rejected(tmp_path):
    import re
    from drawing2cad_mcp.adapters.p21 import sth_p21_parse
    part, spec = cylinder_case()
    path = tmp_path / "detached.step"
    export_ap242(Solid.make_cylinder(10, 30), path, "PMI cylinder", spec, part)
    text = path.read_text()
    records = sth_p21_parse(text)
    usage_id, (_, args) = next((i, r) for i, r in records.items() if r[0] == "GEOMETRIC_ITEM_SPECIFIC_USAGE")
    face_id = int(args[4][0] if isinstance(args[4], list) else args[4])
    duplicate_id = max(records) + 1
    original_face = re.search(r"#" + str(face_id) + r"\s*=.*?;", text, re.S).group()
    duplicate = re.sub(r"^#\d+", "#" + str(duplicate_id), original_face)
    usage = re.search(r"#" + str(usage_id) + r"\s*=.*?;", text, re.S).group()
    changed_usage = usage.replace("#" + str(face_id) + ")", "#" + str(duplicate_id) + ")")
    assert usage != changed_usage
    text = text.replace(usage, changed_usage).replace("ENDSEC;\nEND-ISO-10303-21;", duplicate + "\nENDSEC;\nEND-ISO-10303-21;")
    path.write_text(text)
    with pytest.raises(ValueError, match="association|subshape|identifiers|count"):
        verify_ap242_pmi(path, spec, part)


def test_changed_annotation_geometry_rejected(tmp_path):
    part, spec = cylinder_case()
    path = tmp_path / "presentation.step"
    export_ap242(Solid.make_cylinder(10, 30), path, "PMI cylinder", spec, part)
    spec["dimensions"][0]["annotation"]["origin"][0] += 1
    with pytest.raises(ValueError, match="graphical strokes"):
        verify_ap242_pmi(path, spec, part)


def test_parameter_edit_rebinds_faces_and_pmi(tmp_path):
    part, spec = cylinder_case()
    part["parameters"].extend([{"name": "height", "value": 20, "unit": "mm", "evidence_ids": ["drawing"]},
                               {"name": "radius", "value": 10, "unit": "mm", "evidence_ids": ["drawing"]}])
    part["features"][0]["height"] = {"parameter": "height"}
    spec["dimensions"][1]["value"] = {"parameter": "height"}
    spec["dimensions"][1]["targets"][1]["origin"][2] = {"parameter": "height"}
    spec["dimensions"][0]["targets"][0]["radius"] = {"parameter": "radius"}
    path = tmp_path / "parameter.step"
    export_ap242(Solid.make_cylinder(10, 20), path, "PMI cylinder", spec, part)
    assert verify_ap242_pmi(path, spec, part)["status"] == "pass"
    next(p for p in part["parameters"] if p["name"] == "height")["value"] = 25
    export_ap242(Solid.make_cylinder(10, 25), path, "PMI cylinder", spec, part)
    assert next(d for d in verify_ap242_pmi(path, spec, part)["dimensions"] if d["id"] == "height")["value"] == 25


