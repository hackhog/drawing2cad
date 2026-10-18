"""Part contracts reject unsupported and unresolved construction inputs."""

from copy import deepcopy
from typing import get_args

import pytest

from drawing2cad_mcp.part_schema import Measurement, description_schema, parse_description, part_validate, resolve


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


def test_replaced_evidence_stays_visible_and_cannot_be_referenced():
    description = sample_description()
    old = description["evidence"][0]
    old.update(review_status="rejected", reason="Misread value. Replaced by drawing_fixed.")
    result = part_validate(description)
    assert result["status"] == "fail"
    assert {item["code"] for item in result["defects"]} == {"unresolved_input"}
    description["evidence"].append({**deepcopy(old), "id": "drawing_fixed", "review_status": "open",
                                    "reason": "Value read again from the front view."})
    for collection in ("parameters", "features", "measurements"):
        description[collection][0]["evidence_ids"] = ["drawing_fixed"]
    description["review_flags"] = [{"id": "length_check", "target_id": "length", "status": "open",
                                      "reason": "Check the length again.", "evidence_ids": ["drawing"]}]
    assert part_validate(description)["defects"][0]["pointer"] == "/review_flags/0/evidence_ids"
    description["review_flags"][0]["evidence_ids"] = ["drawing_fixed"]
    result = part_validate(description)
    assert result["status"] == "pass", result
    assert "drawing" in [item["id"] for item in result["review_items"]]


def test_schema_closes_objects_and_bounds_features():
    schema = description_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["features"]["maxItems"] == 500
    assert all(item.get("additionalProperties") is False for item in schema["$defs"].values())


def test_public_measurement_examples_cover_and_validate_every_kind():
    examples = description_schema()["x-measurement-guidance"]["examples"]
    kinds = set(get_args(Measurement.model_fields["kind"].annotation))
    assert set(examples) == kinds
    for kind, example in examples.items():
        description = sample_description()
        description["schema_version"] = "1.1"
        description["measurements"] = [deepcopy(example)]
        result = part_validate(description)
        assert result["status"] == "pass", (kind, result["defects"])


def test_measurement_examples_guidance_rejects_invalid_contracts():
    examples = description_schema()["x-measurement-guidance"]["examples"]
    for kind, change in (("bbox", lambda item: item.update(expected=[10.0, 20.0])),
                         ("volume", lambda item: item.update(direction=[0.0, 0.0, 1.0])),
                         ("arc_radius", lambda item: item.pop("position"))):
        description = sample_description()
        description["schema_version"] = "1.1"
        measurement = deepcopy(examples[kind])
        change(measurement)
        description["measurements"] = [measurement]
        assert part_validate(description)["status"] == "fail"


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


def _threaded_blind_hole():
    description = sample_description()
    description["schema_version"] = "1.2"
    description["features"].append({"id": "tap", "type": "hole", "position": [5, 5, 5],
                                    "diameter": 5, "extent": "blind", "depth": 14,
                                    "thread": {"designation": "M6", "pitch": 1, "length": 9},
                                    "evidence_ids": ["drawing"]})
    return description


def test_explicit_thread_length_and_legacy_serialization():
    description = _threaded_blind_hole()
    assert part_validate(description)["status"] == "pass"
    assert parse_description(description).model_dump()["features"][1]["thread"]["length"] == 9
    description["features"][1]["thread"].pop("length")
    assert part_validate(description)["status"] == "pass"
    assert "length" not in parse_description(description).model_dump()["features"][1]["thread"]
    description["schema_version"] = "1.0"
    assert part_validate(description)["status"] == "pass"


@pytest.mark.parametrize("value", [0, -1, 15, {"parameter": "missing"}, {"parameter": "length"}])
def test_invalid_thread_length_or_parameter(value):
    description = _threaded_blind_hole()
    description["features"][1]["thread"]["length"] = value
    assert part_validate(description)["status"] == "fail"


def test_thread_length_parameter_and_version_rules():
    description = _threaded_blind_hole()
    description["parameters"].append({"name": "thread_length", "value": 9, "unit": "mm", "evidence_ids": ["drawing"]})
    description["features"][1]["thread"]["length"] = {"parameter": "thread_length"}
    assert part_validate(description)["status"] == "pass"
    description["parameters"][-1]["unit"] = "deg"
    assert part_validate(description)["status"] == "fail"
    description["parameters"][-1]["unit"] = "mm"
    description["schema_version"] = "1.1"
    assert any(item["code"] == "schema_version" for item in part_validate(description)["defects"])


@pytest.mark.parametrize("change", [
    lambda hole: hole.update(extent="through", depth=None),
    lambda hole: hole.update(style="counterbore", counter_diameter=7, counter_depth=2),
    lambda hole: hole.update(style="countersink", counter_diameter=7, angle=90),
])
def test_explicit_thread_length_rejects_unsupported_holes(change):
    description = _threaded_blind_hole()
    change(description["features"][1])
    assert part_validate(description)["status"] == "fail"
