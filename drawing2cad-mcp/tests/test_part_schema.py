"""Part contracts reject unsupported and unresolved construction inputs."""

from copy import deepcopy

import pytest

from drawing2cad_mcp.part_schema import description_schema, parse_description, part_validate, resolve


def sample_description():
    return {
        "schema_version": "1.0", "name": "Synthetic plate", "units": "mm",
        "coordinate_system": "right_handed_xyz",
        "evidence": [{"id": "drawing", "status": "explicit", "reason": "Synthetic test dimensions.", "source": {"source_id": "test-source", "source_sha256": "a" * 64, "page": 1, "view": "front", "region": [0, 0, 100, 100]}}],
        "parameters": [{"name": "length", "value": 20, "unit": "mm", "evidence_ids": ["drawing"]}],
        "features": [{"id": "base", "type": "box", "operation": "base", "length": {"parameter": "length"}, "width": 10, "height": 5, "evidence_ids": ["drawing"]}],
        "measurements": [{"id": "overall", "kind": "bbox", "basis": "printed_dimension", "expected": [20, 10, 5], "evidence_ids": ["drawing"]}],
    }


def test_valid_description_and_parameter_reference():
    description = sample_description()
    assert part_validate(description)["status"] == "pass"
    parsed = parse_description(description)
    assert resolve(parsed.features[0].length, parsed) == 20


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(units="inch"),
    lambda d: d.update(script="import os"),
    lambda d: d["features"][0].update(type="arbitrary_code"),
    lambda d: d["features"][0].update(length="20*2"),
    lambda d: d["features"][0].update(length=float("nan")),
    lambda d: d["features"][0].update(height=True),
    lambda d: d["features"][0].update(height=-2),
    lambda d: d["parameters"][0].update(unit="deg"),
    lambda d: d["features"][0].update(length={"parameter": "missing"}),
    lambda d: d["features"].append(deepcopy(d["features"][0])),
    lambda d: d["evidence"][0].update(status="unresolved"),
    lambda d: d["evidence"][0]["source"].update(region=[10, 0, 0, 20]),
    lambda d: d["parameters"][0].update(value=None),
    lambda d: d["features"][0].update(evidence_ids=["missing"]),
])
def test_contract_rejects_invalid_inputs(mutation):
    description = sample_description()
    mutation(description)
    result = part_validate(description)
    assert result["status"] == "fail"
    assert all(item["pointer"].startswith("/") for item in result["defects"])


def test_assumptions_have_source_and_reason_and_stay_visible():
    description = sample_description()
    description["evidence"][0].update(status="assumed", reason="Estimate from the adjacent profile.")
    result = part_validate(description)
    assert result["status"] == "pass"
    assert result["review_items"][0]["status"] == "assumed"
    del description["evidence"][0]["source"]
    assert part_validate(description)["status"] == "fail"


def test_schema_closes_objects_and_bounds_features():
    schema = description_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["features"]["maxItems"] == 500
    assert all(item.get("additionalProperties") is False for item in schema["$defs"].values())


def test_normalized_source_region_has_unit_interval_bounds():
    description = sample_description()
    description["evidence"][0]["source"].update(coordinate_system="normalized_displayed", region=[0, 0, 1, 1])
    assert part_validate(description)["status"] == "pass"
    description["evidence"][0]["source"]["region"][3] = 2
    assert part_validate(description)["status"] == "fail"


def test_union_errors_use_input_json_pointers():
    description = sample_description()
    description["features"][0]["height"] = "not a dimension"
    result = part_validate(description)
    assert all(item["pointer"] == "/features/0/height" for item in result["defects"])
