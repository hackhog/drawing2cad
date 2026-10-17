"""Integrity checks for the application-specific STEP construction property."""

from copy import deepcopy

import pytest

from drawing2cad_mcp.adapters.construction import change_parameters, embed_construction, read_construction
from drawing2cad_mcp.adapters.p21 import P21Ref, sth_p21_parse, sth_p21_record
from test_part_schema import sample_description


def exchange():
    # This synthetic exchange tests the metadata parser, not CAD conformance.
    return """ISO-10303-21;
HEADER;
FILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF'));
ENDSEC;
DATA;
#1=PRODUCT_DEFINITION('part','',#2,#3);
#2=PRODUCT_DEFINITION_FORMATION('','',#4);
#3=PRODUCT_DEFINITION_CONTEXT('',#5,'design');
#4=PRODUCT('part','Synthetic plate','',(#6));
#5=APPLICATION_CONTEXT('mechanical design');
#6=PRODUCT_CONTEXT('',#5,'mechanical');
#7=PRODUCT_DEFINITION_SHAPE('','',#1);
#8=SHAPE_DEFINITION_REPRESENTATION(#7,#9);
#9=ADVANCED_BREP_SHAPE_REPRESENTATION('',(#10),#11);
#10=CARTESIAN_POINT('',(0.,0.,0.));
#11=REPRESENTATION_CONTEXT('','');
ENDSEC;
END-ISO-10303-21;
"""


def rewrite(text, mutate):
    records = sth_p21_parse(text)
    mutate(records)
    header = text[:text.index("DATA;") + 5]
    return header + "\n" + "\n".join(sth_p21_record(i, *value) for i, value in records.items()) + "\nENDSEC;\nEND-ISO-10303-21;\n"


def test_recipe_roundtrip_keeps_order_evidence_and_parameter_references():
    description = sample_description()
    description["features"].append({"id": "hole", "type": "hole", "position": [5, 5, 5], "diameter": 3, "evidence_ids": ["drawing"]})
    encoded, result = embed_construction(exchange(), description)
    recovered = read_construction(encoded)
    assert recovered["description"]["features"][0]["length"] == {"parameter": "length"}
    assert [item["id"] for item in recovered["description"]["features"]] == ["base", "hole"]
    assert recovered["description"]["evidence"][0]["source"]["source_id"] == "test-source"
    assert result["standard_procedural_history"] == "not_supported"
    original, current = sth_p21_parse(exchange()), sth_p21_parse(encoded)
    assert all(sth_p21_record(i, *value) == sth_p21_record(i, *current[i]) for i, value in original.items())


def test_parameter_edits_do_not_rewrite_printed_measurements_or_input():
    description = sample_description()
    before = deepcopy(description)
    changed = change_parameters(description, {"length": 30})
    assert changed["parameters"][0]["value"] == 30
    assert changed["measurements"][0]["expected"] == [20, 10, 5]
    assert description == before


@pytest.mark.parametrize("changes", [{"missing": 2}, {"length": True}, {"length": float("nan")}, {"length": float("inf")}, {"length": "20"}, {"length": -2}])
def test_invalid_parameter_changes_fail(changes):
    with pytest.raises(ValueError):
        change_parameters(sample_description(), changes)


def test_duplicate_property_and_geometry_change_fail():
    encoded, _ = embed_construction(exchange(), sample_description())
    with pytest.raises(ValueError, match="already exists"):
        embed_construction(encoded, sample_description())
    modified = encoded.replace("(0.,0.,0.)", "(1.,0.,0.)")
    with pytest.raises(ValueError, match="geometry"):
        read_construction(modified)
    def duplicate(records):
        prop = next(value for value in records.values() if value[0] == "PROPERTY_DEFINITION")
        records[max(records) + 1] = deepcopy(prop)
    with pytest.raises(ValueError, match="Exactly one"):
        read_construction(rewrite(encoded, duplicate))


@pytest.mark.parametrize("mutation", [
    lambda payload: payload.replace('"profile":"drawing2cad-construction/1"', '"profile":"future/2"'),
    lambda payload: payload.replace('"encoding":', '"extra":1,"encoding":'),
    lambda payload: payload.replace('"encoding":', '"profile":"bad","encoding":'),
    lambda payload: payload.replace('"value":20.0', '"value":NaN'),
    lambda payload: payload.replace('"value":20.0', '"value":21.0'),
])
def test_payload_tampering_fails(mutation):
    encoded, _ = embed_construction(exchange(), sample_description())
    def corrupt(records):
        ident = next(i for i, (kind, _) in records.items() if kind == "DESCRIPTIVE_REPRESENTATION_ITEM")
        records[ident][1][1] = mutation(records[ident][1][1])
    with pytest.raises(ValueError):
        read_construction(rewrite(encoded, corrupt))


def test_wrong_product_and_reordered_chunks_fail():
    description = sample_description()
    description["evidence"][0]["reason"] = "Synthetic evidence. " * 90
    encoded, _ = embed_construction(exchange(), description)
    def wrong_product(records):
        next(args for kind, args in records.values() if kind == "PROPERTY_DEFINITION")[2] = P21Ref(4)
    with pytest.raises(ValueError, match="another product"):
        read_construction(rewrite(encoded, wrong_product))
    def reordered(records):
        rep = next(args for kind, args in records.values() if kind == "REPRESENTATION")
        assert len(rep[1]) > 1
        rep[1].reverse()
    with pytest.raises(ValueError, match="chunks"):
        read_construction(rewrite(encoded, reordered))


def test_ap214_header_and_arbitrary_code_are_rejected():
    with pytest.raises(ValueError, match="actual AP242"):
        embed_construction(exchange().replace("AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF", "AUTOMOTIVE_DESIGN"), sample_description())
    description = sample_description()
    description["features"][0] = {"type": "script", "code": "import os"}
    with pytest.raises(ValueError):
        embed_construction(exchange(), description)


@pytest.mark.parametrize("mutation", [
    lambda text: text.replace("AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF", "AUTOMOTIVE_DESIGN") + "/* FILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF')); */",
    lambda text: text.replace("HEADER;", "HEADER;\nFILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF'));"),
    lambda text: text.replace("AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF", "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF { 1 0 10303 442 9 9 9 }"),
    lambda text: text.replace("END-ISO-10303-21;", ""),
    lambda text: text + "EXTRA;",
    lambda text: text.replace("ISO-10303-21;", "", 1),
])
def test_schema_spoofs_duplicate_headers_and_broken_exchange_fail(mutation):
    with pytest.raises(ValueError):
        embed_construction(mutation(exchange()), sample_description())


@pytest.mark.parametrize("kind,index", [("PROPERTY_DEFINITION", 2), ("PROPERTY_DEFINITION_REPRESENTATION", 0), ("PROPERTY_DEFINITION_REPRESENTATION", 1), ("REPRESENTATION", 2)])
def test_numeric_values_cannot_impersonate_entity_references(kind, index):
    encoded, _ = embed_construction(exchange(), sample_description())
    def corrupt(records):
        args = next(args for entity, args in records.values() if entity == kind)
        args[index] = int(args[index])
    with pytest.raises(ValueError):
        read_construction(rewrite(encoded, corrupt))


def test_empty_property_arguments_fail_with_value_error():
    encoded, _ = embed_construction(exchange(), sample_description())
    def corrupt(records):
        next(args for entity, args in records.values() if entity == "PROPERTY_DEFINITION").clear()
    with pytest.raises(ValueError, match="argument count"):
        read_construction(rewrite(encoded, corrupt))


def test_payload_and_chunk_limits(monkeypatch):
    from drawing2cad_mcp.adapters import construction
    encoded, _ = embed_construction(exchange(), sample_description())
    def oversized(records):
        next(args for entity, args in records.values() if entity == "DESCRIPTIVE_REPRESENTATION_ITEM")[1] = "x" * (construction.CHUNK_SIZE + 1)
    with pytest.raises(ValueError, match="oversized"):
        read_construction(rewrite(encoded, oversized))
    monkeypatch.setattr(construction, "MAX_PAYLOAD", 100)
    with pytest.raises(ValueError, match="size"):
        embed_construction(exchange(), sample_description())


def test_unrelated_product_name_cannot_mask_wrong_linked_product():
    encoded, _ = embed_construction(exchange(), sample_description())
    def corrupt(records):
        records[4][1][1] = "Other product"
        records[max(records) + 1] = ("PRODUCT", ["id", "Synthetic plate", "", []])
    with pytest.raises(ValueError, match="linked product name"):
        read_construction(rewrite(encoded, corrupt))
