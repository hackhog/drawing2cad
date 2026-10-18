"""Cross-checks of printed dimensions in the part description."""

import json

from drawing2cad_mcp.part_schema import description_schema, part_validate
from test_part_schema import sample_description

PRIVATE = "/srv/private-customer/secret-drawing.pdf"


def described(*dimensions):
    description = sample_description()
    description["schema_version"] = "1.4"
    description["dimensions"] = [{"evidence_ids": ["drawing"], **item} for item in dimensions]
    return description


def dim(identifier, nominal, **extra):
    return {"id": identifier, "printed_text": f"{nominal:g}".replace(".", ","), "nominal": nominal, **extra}


def codes(result):
    return {item["code"] for item in result["defects"]}


def test_correct_chain_views_and_measurement_pass():
    result = part_validate(described(
        dim("a", 12, chain={"id": "top", "role": "part"}),
        dim("b", 8, chain={"id": "top", "role": "part"}, dim_id="length_b"),
        dim("total", 20, chain={"id": "top", "role": "total"}, measured={"value": 20.15, "method": "vector_geometry"}),
        dim("b_side", 8, dim_id="length_b")))
    assert result["status"] == "pass", result
    checks = result["dimension_checks"]
    assert checks["chains"][0]["check"] == "pass"
    assert checks["cross_view"][0]["check"] == "pass"
    assert [item["check"] for item in checks["measured"]] == ["not_tested", "not_tested", "pass", "not_tested"]
    assert checks["summary"] == {"pass": 3, "fail": 0, "not_tested": 3}


def test_chain_with_a_wrong_part_fails():
    result = part_validate(described(
        dim("a", 12, chain={"id": "top", "role": "part"}),
        dim("b", 9, chain={"id": "top", "role": "part"}),
        dim("total", 20, chain={"id": "top", "role": "total"})))
    assert result["status"] == "fail"
    defect = next(item for item in result["defects"] if item["code"] == "dimension_chain")
    assert defect["pointer"] == "/dimensions/0/chain"
    assert "21" in defect["message"] and "20" in defect["message"]


def test_cross_view_conflict_fails():
    result = part_validate(described(dim("front", 40, dim_id="width"), dim("top", 42, dim_id="width")))
    assert codes(result) == {"dimension_views"}
    assert result["dimension_checks"]["cross_view"][0]["values"] == [40, 42]


def test_printed_value_that_disagrees_with_its_measurement_fails():
    description = described(dim("hole", 30, measured={"value": 30.6, "method": "pdf_measure_distance"}))
    result = part_validate(description)
    assert codes(result) == {"dimension_measured"}
    assert result["dimension_checks"]["measured"][0]["allowed"] == 0.3
    description["dimensions"][0]["not_to_scale"] = True
    result = part_validate(description)
    assert result["status"] == "pass"
    assert result["dimension_checks"]["measured"][0]["check"] == "not_tested"


def test_missing_data_is_not_tested_never_pass():
    result = part_validate(described(
        dim("alone", 5, dim_id="single"), dim("part_only", 5, chain={"id": "open", "role": "part"})))
    assert result["status"] == "pass"
    checks = result["dimension_checks"]
    assert checks["summary"]["pass"] == 0
    assert checks["chains"][0]["check"] == "not_tested"
    assert checks["cross_view"][0]["check"] == "not_tested"


def test_mixed_units_duplicates_version_and_rejected_evidence_fail():
    result = part_validate(described(
        dim("a", 10, chain={"id": "c", "role": "part"}), dim("t", 10, unit="deg", chain={"id": "c", "role": "total"})))
    assert "dimension_unit" in codes(result)
    assert "duplicate_id" in codes(part_validate(described(dim("a", 1), dim("a", 1))))
    description = described(dim("a", 1))
    description["schema_version"] = "1.3"
    assert "schema_version" in codes(part_validate(description))
    description = described(dim("a", 1))
    description["dimensions"][0]["evidence_ids"] = ["missing"]
    assert "unknown_evidence" in codes(part_validate(description))


def test_messages_do_not_repeat_the_printed_text():
    result = part_validate(described(
        {"id": "a", "printed_text": PRIVATE, "nominal": 10, "dim_id": "w"},
        {"id": "b", "printed_text": PRIVATE, "nominal": 11, "dim_id": "w"}))
    assert PRIVATE not in json.dumps(result["defects"])
    assert PRIVATE not in json.dumps(result["dimension_checks"])


def test_descriptions_without_dimensions_are_unchanged():
    result = part_validate(sample_description())
    assert "dimension_checks" not in result
    schema = description_schema()
    assert "PrintedDimension" in json.dumps(schema)
