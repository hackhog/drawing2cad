"""Synthetic STEP adapter tests. No CAD kernel or customer model is used."""

import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator

from drawing2cad_mcp.adapters import identity
from drawing2cad_mcp.adapters.p21 import (P21Enum, P21Ref, P21Typed, sth_p21_dump, sth_p21_parse,
                                         sth_p21_record, sth_p21_validate_refs)
from drawing2cad_mcp.step import StepError, StepService
from drawing2cad_mcp.step_tools import REVIEW_SCHEMAS, STEP_SCHEMAS


BASE = """ISO-10303-21;
HEADER;
FILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF'));
ENDSEC;
DATA;
#1=(GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNIT_ASSIGNED_CONTEXT((#2)) REPRESENTATION_CONTEXT('',''));
#2=(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.));
#10=CARTESIAN_POINT('',(0.,0.,0.));
#11=CARTESIAN_POINT('',(4.,0.,0.));
#12=CARTESIAN_POINT('',(4.,3.,0.));
#13=CARTESIAN_POINT('',(0.,3.,0.));
#14=DIRECTION('',(0.,0.,1.));
#15=DIRECTION('',(1.,0.,0.));
#16=AXIS2_PLACEMENT_3D('',#10,#14,#15);
#17=PLANE('',#16);
#18=POLY_LOOP('',(#10,#11,#12,#13));
#19=FACE_OUTER_BOUND('',#18,.T.);
#20=FACE_SURFACE('profile',(#19),#17,.T.);
#30=EXTRUDED_FACE_SOLID('Block',#20,#14,2.);
#40=MANIFOLD_SOLID_BREP('syntactic reference only',#41);
#41=CLOSED_SHELL('',());
#50=ADVANCED_BREP_SHAPE_REPRESENTATION('Result',(#40),#1);
#60=PROCEDURAL_SHAPE_REPRESENTATION_SEQUENCE('Sequence',(#30),(),'');
#61=PROCEDURAL_SHAPE_REPRESENTATION('Construction',(#60),#1);
#62=EXPLICIT_PROCEDURAL_SHAPE_REPRESENTATION_RELATIONSHIP('','',#61,#50);
#63=PRODUCT_DEFINITION_SHAPE('','',#64);
#64=PRODUCT_DEFINITION('','',#65,#66);
#65=PRODUCT_DEFINITION_FORMATION('','',#67);
#66=PRODUCT_DEFINITION_CONTEXT('',#68,'');
#67=PRODUCT('p','','',());
#68=APPLICATION_CONTEXT('');
#69=SHAPE_DEFINITION_REPRESENTATION(#63,#50);
ENDSEC;
END-ISO-10303-21;
"""

PMI = """#100=SHAPE_ASPECT('D1 width','',#63,.T.);
#101=GEOMETRIC_ITEM_SPECIFIC_USAGE('','',#100,#50,#40);
#102=DIMENSIONAL_SIZE(#100,'width');
#103=DESCRIPTIVE_REPRESENTATION_ITEM('source_id','D1');
#104=(LENGTH_MEASURE_WITH_UNIT() MEASURE_REPRESENTATION_ITEM() MEASURE_WITH_UNIT(LENGTH_MEASURE(4.),#2) REPRESENTATION_ITEM(''));
#105=SHAPE_DIMENSION_REPRESENTATION('',(#103,#104),#1);
#106=DIMENSIONAL_CHARACTERISTIC_REPRESENTATION(#102,#105);
#110=COORDINATES_LIST('',2,((0.,0.,0.),(4.,0.,0.)));
#111=TESSELLATED_CURVE_SET('',#110,((1,2)));
#112=TESSELLATED_GEOMETRIC_SET('',(#111));
#113=TESSELLATED_ANNOTATION_OCCURRENCE('','',#112);
#114=DRAUGHTING_CALLOUT('D1_Front',(#113));
#115=DRAUGHTING_MODEL('',(#114),#1);
#116=ANNOTATION_PLANE('','',#17,(#114));
#117=DRAUGHTING_MODEL_ITEM_ASSOCIATION('','',#102,#115,#114);
"""
KEY = "drawing2cad.review_annotations.v1"
PAYLOAD = {KEY: {"schema": REVIEW_SCHEMAS[KEY], "markers": [], "literal": "semi; quote ' and Unicode \u00b5"}}


def add(text, entities):
    at = text.rfind("ENDSEC;")
    return text[:at] + entities + text[at:]


def write_source(tmp_path, text=BASE, raw=None):
    path = tmp_path / "source.step"
    path.write_bytes(text.encode("utf-8") if raw is None else raw)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def invoke(tmp_path, name, text=BASE, **args):
    source, sha = write_source(tmp_path, text)
    service = StepService([tmp_path], tmp_path / "out")
    return service.call(name, {"path": str(source), "expected_sha256": sha, **args})


def test_inspect_and_exact_hash_with_crlf_and_bom(tmp_path):
    raw = b"\xef\xbb\xbf" + BASE.replace("\n", "\r\n").encode()
    source, sha = write_source(tmp_path, raw=raw)
    result = StepService([tmp_path], tmp_path / "out").call("step_inspect", {"path": str(source), "expected_sha256": sha.upper()})
    assert result["source"] == {"path": str(source.resolve()), "sha256": sha, "size_bytes": len(raw)}
    assert result["inspection"]["all_references_resolve"]
    assert result["inspection"]["procedural_representations"] == 1
    assert not result["inspection"]["express_validated"]
    assert result["adapter"]["source_sha256"] == identity()["source_sha256"]
    assert not result["adapter"]["cad_kernel_used"]


def test_box_procedural_graph(tmp_path):
    result = invoke(tmp_path, "step_read_procedural")["procedural"]
    assert result == {"operations": [{"id": "Block", "source_entity": 30, "type": "box", "origin": [0., 0., 0.], "length": 4., "width": 3., "height": 2.}],
                      "root": "Block", "units": "mm", "main_representation": 50}


@pytest.mark.parametrize("operation", ["UNION", "DIFFERENCE", "INTERSECTION"])
def test_boolean_dependencies(tmp_path, operation):
    text = add(BASE, "#31=EXTRUDED_FACE_SOLID('Other',#20,#14,1.);\n#32=BOOLEAN_RESULT('Result',." + operation + ".,#30,#31);\n#33=CSG_SOLID('Result',#32);\n")
    text = text.replace("'Sequence',(#30)", "'Sequence',(#30,#31,#33)")
    operations = invoke(tmp_path, "step_read_procedural", text)["procedural"]["operations"]
    assert operations[-1] == {"id": "Result", "source_entity": 33, "type": operation.lower(), "base": "Block", "tool": "Other", "refine": True}


@pytest.mark.parametrize("axis,u", [("(0.,0.,1.)", "(1.,0.,0.)"), ("(1.,0.,0.)", "(0.,1.,0.)")])
def test_circular_extrusion(tmp_path, axis, u):
    text = BASE.replace("#14=DIRECTION('',(0.,0.,1.))", "#14=DIRECTION(''," + axis + ")")
    text = text.replace("#15=DIRECTION('',(1.,0.,0.))", "#15=DIRECTION(''," + u + ")")
    text = add(text, "#70=CIRCLE('',#16,2.);\n#71=CARTESIAN_POINT(''," + ("(2.,0.,0.)" if u == "(1.,0.,0.)" else "(0.,2.,0.)") + ");\n#72=VERTEX_POINT('',#71);\n#73=EDGE_CURVE('',#72,#72,#70,.T.);\n#74=ORIENTED_EDGE('',*,*,#73,.T.);\n#75=EDGE_LOOP('',(#74));\n")
    text = text.replace("#19=FACE_OUTER_BOUND('',#18", "#19=FACE_OUTER_BOUND('',#75")
    op = invoke(tmp_path, "step_read_procedural", text)["procedural"]["operations"][0]
    assert op["type"] == "cylinder" and op["radius"] == 2 and op["depth"] == 2


@pytest.mark.parametrize("old,new,match", [
    (".MILLI.", ".CENTI.", "millimetres"),
    ("#14=DIRECTION('',(0.,0.,1.))", "#14=DIRECTION('',(0.,1.,0.))", "rectangular"),
    ("#14,2.)", "#14,-2.)", "negative"),
    ("'Sequence',(#30)", "'Sequence',(#30,#30)", "duplicate"),
    ("'Sequence',(#30)", "'Sequence',(#30,#31)", "Disconnected"),
])
def test_unsupported_procedural_profiles(tmp_path, old, new, match):
    text = BASE.replace(old, new)
    if "#31" in new:
        text = add(text, "#31=EXTRUDED_FACE_SOLID('Disconnected',#20,#14,1.);\n")
    with pytest.raises(StepError, match=match) as error:
        invoke(tmp_path, "step_read_procedural", text)
    assert error.value.code == "STEP_PROFILE_UNSUPPORTED"
    assert error.value.next_action


def test_nominal_pmi_values_and_associations(tmp_path):
    result = invoke(tmp_path, "step_read_pmi", add(BASE, PMI), expected_count=1)["pmi"]
    item = result["annotations"][0]
    assert (item["id"], item["value"], item["unit"], item["type"]) == ("D1", 4., "mm", "DIMENSIONAL_SIZE")
    assert item["geometric_item_entities"] == [40]
    assert item["polylines"] == [[[0., 0., 0.], [4., 0., 0.]]]
    assert item["plane"]["name"] == "Front"
    assert result["metadata_properties"] == []


@pytest.mark.parametrize("change,match", [
    (lambda t: add(t, "#200=DATUM('','',#63,.T.);\n"), "tolerance/datum"),
    (lambda t: t.replace("LENGTH_MEASURE(4.)", "LENGTH_MEASURE(5.)"), None),
    (lambda t: t.replace("#117=DRAUGHTING_MODEL_ITEM_ASSOCIATION('','',#102,#115,#114);", ""), "graphical association"),
    (lambda t: t.replace("(1,2)", "(1,3)"), "polyline"),
])
def test_pmi_fail_closed_and_real_value_changes(tmp_path, change, match):
    text = change(add(BASE, PMI))
    if match:
        with pytest.raises(StepError, match=match):
            invoke(tmp_path, "step_read_pmi", text)
    else:
        assert invoke(tmp_path, "step_read_pmi", text)["pmi"]["annotations"][0]["value"] == 5.


def test_pmi_expected_count(tmp_path):
    with pytest.raises(StepError, match="PMI count"):
        invoke(tmp_path, "step_read_pmi", add(BASE, PMI), expected_count=2)


def test_review_roundtrip_preserves_exact_source_regions_and_pmi(tmp_path):
    original = b"\xef\xbb\xbf" + add(BASE, PMI).replace("\n", "\r\n").encode()
    source, sha = write_source(tmp_path, raw=original)
    service = StepService([tmp_path], tmp_path / "out")
    before = service.call("step_read_pmi", {"path": str(source), "expected_sha256": sha})["pmi"]
    result = service.call("step_append_review_properties", {"path": str(source), "expected_sha256": sha, "output_name": "candidate.step", "properties": PAYLOAD})
    candidate = Path(result["artifact"]["path"])
    raw = candidate.read_bytes()
    at = original.rfind(b"ENDSEC;")
    assert raw.startswith(original[:at]) and raw.endswith(original[at:])
    assert source.read_bytes() == original
    assert hashlib.sha256(raw).hexdigest() == result["artifact"]["sha256"]
    assert result["metadata_only"] and result["preservation"]["exact_metadata_roundtrip"]
    read = service.call("step_read_review_properties", {"path": str(candidate), "expected_sha256": result["artifact"]["sha256"], "expected_schemas": {KEY: REVIEW_SCHEMAS[KEY]}})
    assert read["properties"] == PAYLOAD
    after = service.call("step_read_pmi", {"path": str(candidate), "expected_sha256": result["artifact"]["sha256"]})["pmi"]
    assert before == after
    with pytest.raises(StepError, match="already exists"):
        service.call("step_append_review_properties", {"path": str(source), "expected_sha256": sha, "output_name": "candidate.step", "properties": PAYLOAD})
    assert raw == candidate.read_bytes()
    assert not list((tmp_path / "out").glob(".step-candidate-*"))


def test_review_chunking_and_duplicate_property_refusal(tmp_path):
    source, sha = write_source(tmp_path)
    service = StepService([tmp_path], tmp_path / "out")
    payload = {KEY: {"schema": REVIEW_SCHEMAS[KEY], "text": "x" * 9000}}
    result = service.call("step_append_review_properties", {"path": str(source), "expected_sha256": sha, "output_name": "large.step", "properties": payload})
    raw = Path(result["artifact"]["path"]).read_text()
    assert "application/json;chunk=000001/000003" in raw
    assert "application/json;chunk=000003/000003" in raw
    with pytest.raises(StepError, match="property already exists"):
        service.call("step_append_review_properties", {"path": result["artifact"]["path"], "expected_sha256": result["artifact"]["sha256"], "output_name": "twice.step", "properties": payload})
    assert not (tmp_path / "out/twice.step").exists()


def test_bad_review_metadata_is_rejected_before_output(tmp_path):
    with pytest.raises(StepError):
        invoke(tmp_path, "step_append_review_properties", properties={KEY: {"schema": REVIEW_SCHEMAS[KEY], "x": float("nan")}}, output_name="bad.step")
    assert not (tmp_path / "out/bad.step").exists()


@pytest.mark.parametrize("mutator,match", [
    (lambda s:s.replace('"markers":[]', '"markers":[],"markers":[]'), "Duplicate JSON"),
    (lambda s:s.replace('"markers":[]', '"markers":NaN'), "Nonfinite JSON"),
    (lambda s:s.replace("application/json", "application/unknown"), "JSON chunks"),
    (lambda s:s.replace("'Adapter metadata; not original drawing PMI',#63", "'Adapter metadata; not original drawing PMI',#64"), "different product"),
])
def test_review_corruption(tmp_path, mutator, match):
    result = invoke(tmp_path, "step_append_review_properties", properties=PAYLOAD, output_name="valid.step")
    source = Path(result["artifact"]["path"]).read_text()
    changed = mutator(source)
    assert changed != source
    with pytest.raises(StepError, match=match):
        invoke(tmp_path, "step_read_review_properties", changed, expected_schemas={KEY: REVIEW_SCHEMAS[KEY]})


@pytest.mark.parametrize("text,match", [
    (add(BASE, "#10=CARTESIAN_POINT('',(1.,2.,3.));\n"), "duplicate entity"),
    (BASE.replace("#10,#11,#12,#13", "#10,#11,#12,#999"), "dangling"),
    (BASE.replace("END-ISO-10303-21;", "DATA; ENDSEC; END-ISO-10303-21;"), "multiple DATA"),
    (BASE.replace("#14,2.)", "#14,1.E999)"), "non-finite"),
    (BASE[:-20], "incomplete"),
])
def test_malformed_step_is_rejected(tmp_path, text, match):
    with pytest.raises(StepError, match=match):
        invoke(tmp_path, "step_inspect", text)


def test_bounds_hash_and_root_enforcement(tmp_path):
    source, sha = write_source(tmp_path)
    service = StepService([tmp_path], tmp_path / "out", max_step_bytes=100)
    with pytest.raises(StepError) as error:
        service.call("step_inspect", {"path": str(source), "expected_sha256": sha})
    assert error.value.code == "STEP_SIZE_LIMIT"
    service = StepService([tmp_path / "other"], tmp_path / "out")
    with pytest.raises(StepError) as error:
        service.call("step_inspect", {"path": str(source), "expected_sha256": sha})
    assert error.value.code == "STEP_PATH_NOT_ALLOWED"
    service = StepService([tmp_path], tmp_path / "out")
    with pytest.raises(StepError) as error:
        service.call("step_inspect", {"path": str(source), "expected_sha256": "0" * 64})
    assert error.value.code == "SOURCE_HASH_MISMATCH"
    assert error.value.as_dict()["target"] == "expected_sha256"


@pytest.mark.parametrize("name,args", [
    ("step_inspect", {}), ("step_inspect", {"arbitrary": True}),
    ("step_read_pmi", {"expected_count": True}),
    ("step_read_review_properties", {"expected_schemas": {"other": "schema"}}),
    ("step_append_review_properties", {"properties": PAYLOAD, "output_name": "../escape.step"}),
    ("step_append_review_properties", {"properties": PAYLOAD, "output_name": "CON.step"}),
])
def test_strict_argument_contract(tmp_path, name, args):
    source, sha = write_source(tmp_path)
    data = {"path": str(source), "expected_sha256": sha, **args}
    if name == "step_inspect" and args == {}:
        del data["expected_sha256"]
    with pytest.raises(StepError):
        StepService([tmp_path], tmp_path / "out").call(name, data)
    assert not (tmp_path / "escape.step").exists()


def test_schemas_are_valid_and_match_expected_inputs():
    for schema in STEP_SCHEMAS.values():
        Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(STEP_SCHEMAS["step_append_review_properties"])
    validator.validate({"path": "/source.step", "expected_sha256": "a" * 64, "output_name": "candidate.step", "properties": PAYLOAD})
    assert list(validator.iter_errors({"path": "/source.step", "expected_sha256": "a" * 64, "output_name": "../a.step", "properties": PAYLOAD}))


def test_p21_parser_and_serializer_bounds():
    source = "DATA;#1=THING('quote '' semi;',.T.,#1,*,3.);ENDSEC;"
    records = sth_p21_parse(source)
    assert sth_p21_validate_refs(records)
    assert sth_p21_parse("DATA;" + sth_p21_record(1, *records[1]) + "ENDSEC;")[1][0] == "THING"
    with pytest.raises(ValueError, match="size bound"):
        sth_p21_parse("DATA;#1=THING('\u00b5');ENDSEC;", max_bytes=len("DATA;#1=THING('\u00b5');ENDSEC;"))
    with pytest.raises(ValueError, match="nesting"):
        sth_p21_parse("DATA;#1=THING((((((1))))));ENDSEC;", max_depth=3)
    with pytest.raises(ValueError, match="record count"):
        sth_p21_parse("DATA;#1=THING();#2=THING();ENDSEC;", max_records=1)
    with pytest.raises(ValueError, match="string exceeds"):
        sth_p21_parse("DATA;#1=THING('abc');ENDSEC;", max_string=2)
    with pytest.raises(ValueError):
        sth_p21_parse(source, max_records=True)


def test_no_kernel_or_gui_import_is_required(tmp_path):
    source, sha = write_source(tmp_path)
    script = """import importlib.abc,sys
class DenyCAD(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'FreeCAD','FreeCADGui','Part','OCC','PySide','PySide2','PySide6'}:raise AssertionError(fullname)
sys.meta_path.insert(0,DenyCAD())
from drawing2cad_mcp.step import StepService
service=StepService([sys.argv[1]],sys.argv[1]+'/out')
service.call('step_inspect',{'path':sys.argv[2],'expected_sha256':sys.argv[3]})
service.call('step_read_procedural',{'path':sys.argv[2],'expected_sha256':sys.argv[3]})
service.call('step_read_pmi',{'path':sys.argv[2],'expected_sha256':sys.argv[3]})
print('NO_CAD_IMPORTS')
"""
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(source), sha], capture_output=True, text=True, timeout=15, env=environment)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "NO_CAD_IMPORTS"


def fillet_source():
    edges = """#70=CIRCLE('',#16,2.);
#71=CARTESIAN_POINT('',(2.,0.,0.));
#72=VERTEX_POINT('',#71);
#73=EDGE_CURVE('',#72,#72,#70,.T.);
#74=ORIENTED_EDGE('',*,*,#73,.T.);
#75=EDGE_LOOP('',(#74));
#76=FACE_OUTER_BOUND('',#75,.T.);
#77=ADVANCED_FACE('',(#76),#17,.T.);
#78=PROCEDURAL_SHAPE_REPRESENTATION_SEQUENCE('Base',(#30),(),'');
#79=EXPLICIT_PROCEDURAL_GEOMETRIC_REPRESENTATION_ITEM_RELATIONSHIP('','',#78,#40);
#80=SOLID_WITH_CONSTANT_RADIUS_EDGE_BLEND('Round','',#30,(#73),0.5);
"""
    return add(BASE.replace("#41=CLOSED_SHELL('',())", "#41=CLOSED_SHELL('',(#77))").replace("'Sequence',(#30)", "'Sequence',(#30,#80)"), edges)


def test_anchored_fillet_decodes_without_claiming_geometry_validity(tmp_path):
    result = invoke(tmp_path, "step_read_procedural", fillet_source())
    op = result["procedural"]["operations"][-1]
    assert op == {"id": "Round", "source_entity": 80, "type": "fillet", "base": "Block", "radius": 0.5, "step_edges": [73], "base_brep": 40}
    assert not result["adapter"]["geometry_validated"]


@pytest.mark.parametrize("old,new,match", [
    ("#30,(#73),0.5", "#30,(#73,#73),0.5", "fillet selection"),
    ("#30,(#73),0.5", "#30,(#73),-0.5", "fillet selection"),
    ("#30,(#73),0.5", "#30,(#73),#10", "numeric scalar"),
    ("#78,#40", "#78,#30", "MANIFOLD_SOLID_BREP"),
    ("'Base',(#30)", "'Base',(#80)", "construction prefix"),
])
def test_fillet_profile_rejections(tmp_path, old, new, match):
    with pytest.raises(StepError, match=match):
        invoke(tmp_path, "step_read_procedural", fillet_source().replace(old, new))


@pytest.mark.parametrize("old,new", [("#14,2.)", "#14,#10)"), ("'Sequence',(#30)", "'Sequence',(30)")])
def test_procedural_references_are_not_numbers(tmp_path, old, new):
    with pytest.raises(StepError):
        invoke(tmp_path, "step_read_procedural", BASE.replace(old, new))


def test_pmi_length_and_angle_units(tmp_path):
    centimeter = add(BASE, PMI).replace(".MILLI.", ".CENTI.")
    item = invoke(tmp_path, "step_read_pmi", centimeter)["pmi"]["annotations"][0]
    assert item["value"] == 40.
    assert item["polylines"][0][-1] == [40., 0., 0.]
    angle = add(add(BASE, PMI), "#200=(NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.));\n")
    angle = angle.replace("DIMENSIONAL_SIZE(#100,'width')", "ANGULAR_SIZE(#100,'angle')")
    angle = angle.replace("LENGTH_MEASURE(4.),#2", "PLANE_ANGLE_MEASURE(1.5707963267948966),#200")
    item = invoke(tmp_path, "step_read_pmi", angle)["pmi"]["annotations"][0]
    assert item["value"] == 90. and item["unit"] == "deg"


@pytest.mark.parametrize("designation", [False, True])
def test_semantic_property_pmi(tmp_path, designation):
    metadata = "#123=DESCRIPTIVE_REPRESENTATION_ITEM('source_id','P1');\n"
    if designation:
        metadata += "#124=DESCRIPTIVE_REPRESENTATION_ITEM('thread designation','M6');\n#125=DESCRIPTIVE_REPRESENTATION_ITEM('drawing_literal','M6');\n"
        items = "#123,#124,#125"
    else:
        metadata += "#124=MEASURE_WITH_UNIT(LENGTH_MEASURE(0.5),#2);\n"
        items = "#123,#124"
    extra = """#120=SHAPE_ASPECT('P1 note','',#63,.T.);
#121=GEOMETRIC_ITEM_SPECIFIC_USAGE('','',#120,#50,#40);
#122=PROPERTY_DEFINITION('note','',#120);
#126=REPRESENTATION('note',(""" + items + """),#1);
#127=PROPERTY_DEFINITION_REPRESENTATION(#122,#126);
#134=DRAUGHTING_CALLOUT('P1_Front',(#113));
#136=ANNOTATION_PLANE('','',#17,(#134));
#137=DRAUGHTING_MODEL_ITEM_ASSOCIATION('','',#122,#115,#134);
"""
    result = invoke(tmp_path, "step_read_pmi", add(add(BASE, PMI), metadata + extra), expected_count=2)["pmi"]
    item = next(x for x in result["annotations"] if x["id"] == "P1")
    assert item["dimension_kind"] == ("thread designation" if designation else "general radius")
    assert item["value"] is None if designation else item["value"] == 0.5


def test_review_chunk_order_and_schema_failures(tmp_path):
    payload = {KEY: {"schema": REVIEW_SCHEMAS[KEY], "text": "x" * 9000}}
    result = invoke(tmp_path, "step_append_review_properties", properties=payload, output_name="large.step")
    text = Path(result["artifact"]["path"]).read_text()
    with pytest.raises(StepError, match="reordered"):
        invoke(tmp_path, "step_read_review_properties", text.replace("chunk=000001/000003", "chunk=000002/000003"), expected_schemas={KEY: REVIEW_SCHEMAS[KEY]})
    with pytest.raises(StepError, match="schema"):
        invoke(tmp_path, "step_read_review_properties", text.replace("drawing2cad.review-annotations/1", "drawing2cad.review-annotations/9"), expected_schemas={KEY: REVIEW_SCHEMAS[KEY]})


def test_atomic_publish_failure_cleans_temp_and_never_publishes(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("Hard links unavailable")
    monkeypatch.setattr(os, "link", unavailable)
    with pytest.raises(StepError) as error:
        invoke(tmp_path, "step_append_review_properties", properties=PAYLOAD, output_name="missing.step")
    assert error.value.code == "STEP_WRITE_FAILED"
    assert not list((tmp_path / "out").iterdir())


def test_symlink_cannot_escape_allowed_root(tmp_path):
    outside = tmp_path / "outside"
    allowed = tmp_path / "allowed"
    outside.mkdir(); allowed.mkdir()
    source, sha = write_source(outside)
    link = allowed / "link.step"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("The test host does not permit symlink creation")
    with pytest.raises(StepError) as error:
        StepService([allowed], allowed / "out").call("step_inspect", {"path": str(link), "expected_sha256": sha})
    assert error.value.code == "STEP_PATH_NOT_ALLOWED"


def test_structured_error_for_invalid_path_and_unwritable_output(tmp_path):
    service = StepService([tmp_path], tmp_path / "out")
    with pytest.raises(StepError) as error:
        service.call("step_inspect", {"path": "bad\x00.step", "expected_sha256": "0" * 64})
    assert error.value.code in {"INVALID_STEP_FILE", "STEP_PATH_NOT_ALLOWED"}
    source, sha = write_source(tmp_path)
    (tmp_path / "out").write_text("Existing ordinary file")
    with pytest.raises(StepError) as error:
        service.call("step_append_review_properties", {"path": str(source), "expected_sha256": sha, "output_name": "candidate.step", "properties": PAYLOAD})
    assert error.value.code == "STEP_WRITE_FAILED"
    assert (tmp_path / "out").read_text() == "Existing ordinary file"


@pytest.mark.parametrize("measure", ["AREA_MEASURE", "VOLUME_MEASURE", "PLANE_ANGLE_MEASURE", "FAKE_LENGTH_MEASURE"])
def test_nominal_dimension_rejects_wrong_measure_family(tmp_path, measure):
    text=add(BASE,PMI).replace("LENGTH_MEASURE(4.)",measure+"(4.)")
    with pytest.raises(StepError,match="Measure type"):
        invoke(tmp_path,"step_read_pmi",text)


def test_angular_dimension_rejects_length_measure_and_wrong_unit_family(tmp_path):
    text=add(BASE,PMI).replace("DIMENSIONAL_SIZE(#100,'width')","ANGULAR_SIZE(#100,'angle')")
    with pytest.raises(StepError,match="Measure type"):
        invoke(tmp_path,"step_read_pmi",text)
    text=text.replace("LENGTH_MEASURE(4.)","PLANE_ANGLE_MEASURE(1.)")
    text=text.replace("SI_UNIT(.MILLI.,.METRE.)","SI_UNIT($,.RADIAN.)")
    with pytest.raises(StepError,match="Angle unit"):
        invoke(tmp_path,"step_read_pmi",text)


def test_length_dimension_rejects_wrong_unit_type(tmp_path):
    text=add(BASE,PMI).replace("LENGTH_UNIT()","AREA_UNIT()")
    with pytest.raises(StepError,match="Length unit"):
        invoke(tmp_path,"step_read_pmi",text)


@pytest.mark.parametrize("number", ["1e999","-1e999","[1e999]","{\"nested\":1e999}"])
def test_review_numeric_overflow_rejected(tmp_path,number):
    result=invoke(tmp_path,"step_append_review_properties",properties=PAYLOAD,output_name="valid.step")
    text=Path(result["artifact"]["path"]).read_text().replace('"markers":[]','"markers":'+number)
    with pytest.raises(StepError,match="Nonfinite JSON number"):
        invoke(tmp_path,"step_read_review_properties",text,expected_schemas={KEY:REVIEW_SCHEMAS[KEY]})


@pytest.mark.parametrize("text,match", [
    ("ISO-10303-21;DATA;#1=THING();ENDSEC;END-ISO-10303-21;","HEADER"),
    ("ISO-10303-21;HEADER;FILE_SCHEMA(('AP242'));ENDSEC;DATA;#1=THING();ENDSEC;GARBAGE;END-ISO-10303-21;","END-ISO"),
    ("ISO-10303-21;HEADER;FILE_SCHEMA(('AP242'));ENDSEC;GARBAGE;DATA;#1=THING();ENDSEC;END-ISO-10303-21;","DATA"),
    ("ISO-10303-21;HEADER;FILE_SCHEMA(('AP242'));ENDSEC;HEADER;ENDSEC;DATA;#1=THING();ENDSEC;END-ISO-10303-21;","DATA"),
    ("ISO-10303-21;HEADER;ENDSEC;DATA;#1=THING();ENDSEC;END-ISO-10303-21;","HEADER must"),
])
def test_exchange_grammar_rejects_missing_header_and_garbage(tmp_path,text,match):
    with pytest.raises(StepError,match=match):
        invoke(tmp_path,"step_inspect",text)


def test_exchange_header_strings_and_comments_do_not_change_section_order(tmp_path):
    text=BASE.replace("FILE_SCHEMA(","/* DATA; ENDSEC; */ FILE_DESCRIPTION(('DATA; ENDSEC;'),'2;1');\nFILE_SCHEMA(")
    result=invoke(tmp_path,"step_inspect",text)
    assert result["inspection"]["entity_count"]>0
    assert result["inspection"]["syntax_profile"]=="header-and-single-data-section"
    assert not result["inspection"]["express_validated"]


def test_replaced_output_directory_is_rejected_before_creation(tmp_path):
    output=tmp_path/"out"
    output.mkdir()
    service=StepService([tmp_path],output)
    source,sha=write_source(tmp_path)
    output.rename(tmp_path/"original-out")
    output.mkdir()
    with pytest.raises(StepError) as error:
        service.call("step_append_review_properties",{"path":str(source),"expected_sha256":sha,"output_name":"candidate.step","properties":PAYLOAD})
    assert error.value.code=="STEP_OUTPUT_ROOT_CHANGED"
    assert not list(output.iterdir())


def test_redirected_output_root_is_rejected_even_without_symlink_privilege(tmp_path,monkeypatch):
    output=tmp_path/"out"
    output.mkdir()
    service=StepService([tmp_path],output)
    source,sha=write_source(tmp_path)
    outside=tmp_path/"outside"
    outside.mkdir()
    original_resolve=Path.resolve
    def redirected(path,*args,**kwargs):
        return outside if path==output else original_resolve(path,*args,**kwargs)
    monkeypatch.setattr(Path,"resolve",redirected)
    with pytest.raises(StepError) as error:
        service.call("step_append_review_properties",{"path":str(source),"expected_sha256":sha,"output_name":"candidate.step","properties":PAYLOAD})
    assert error.value.code=="STEP_OUTPUT_ROOT_CHANGED"
    assert not list(outside.iterdir())
    assert not list(output.iterdir())


def test_output_root_revalidated_after_temporary_write(tmp_path,monkeypatch):
    import drawing2cad_mcp.step as module
    output=tmp_path/"out"
    output.mkdir()
    service=StepService([tmp_path],output)
    source,sha=write_source(tmp_path)
    original_fsync=module.os.fsync
    original_identity=service._directory_identity
    changed=[False]
    def changed_after_write(descriptor):
        original_fsync(descriptor)
        changed[0]=True
    def observed_identity(path):
        actual=original_identity(path)
        return (actual[0],actual[1]+1) if changed[0] else actual
    monkeypatch.setattr(module.os,"fsync",changed_after_write)
    monkeypatch.setattr(service,"_directory_identity",observed_identity)
    with pytest.raises(StepError) as error:
        service.call("step_append_review_properties",{"path":str(source),"expected_sha256":sha,"output_name":"candidate.step","properties":PAYLOAD})
    assert error.value.code=="STEP_OUTPUT_ROOT_CHANGED"
    assert not (output/"candidate.step").exists()
    # Cleanup must not delete through a directory whose identity no longer matches.
    assert len(list(output.glob(".step-candidate-*")))==1
