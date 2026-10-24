"""Schema errors name the field and the rule, never the input value."""

from jsonschema import Draft202012Validator

from drawing2cad_mcp.schema_errors import describe

# A private value with forward slashes, so that the check does not depend on the platform.
PRIVATE = "/srv/private-customer/secret-drawing.pdf"


def _error(schema, value):
    return next(Draft202012Validator(schema).iter_errors(value))


def test_pattern_error_names_the_rule_but_not_the_value():
    schema = {"type": "object", "properties": {"run_id": {"type": "string", "pattern": "^[a-z]+$"}}}
    target, message = describe(_error(schema, {"run_id": PRIVATE}))
    assert target == "/run_id"
    assert "pattern" in message and "^[a-z]+$" in message
    assert PRIVATE not in message and "secret" not in message


def test_type_error_shows_the_expected_type_but_not_the_value():
    schema = {"type": "object", "properties": {"pages": {"type": "array"}}}
    target, message = describe(_error(schema, {"pages": PRIVATE}))
    assert target == "/pages" and '"array"' in message and "secret" not in message


def test_required_and_additional_properties_do_not_repeat_input_names():
    schema = {"type": "object", "required": ["run_id"], "additionalProperties": False, "properties": {"run_id": {}}}
    target, missing = describe(_error({**schema, "additionalProperties": True}, {}))
    assert target == "/run_id" and "run_id" in missing
    nested, _ = describe(_error({**schema, "additionalProperties": True}, {}), "/arguments")
    assert nested == "/arguments/run_id"
    assert "'required'" in missing
    _, extra = describe(_error(schema, {"run_id": "a", PRIVATE: 1}))
    assert "secret" not in extra and "'additionalProperties'" in extra


def test_root_pointer_is_empty_and_combinators_name_their_rule():
    target, message = describe(_error({"type": "object"}, PRIVATE))
    assert target == "" and "argument root" in message and "secret" not in message
    one = {"type": "object", "properties": {"x": {"oneOf": [{"type": "string"}, {"minLength": 1}]}}}
    target, message = describe(_error(one, {"x": "secret value"}))
    assert target == "/x" and "'oneOf'" in message and "exactly one" in message and "secret" not in message
    any_of = {"type": "object", "properties": {"x": {"anyOf": [{"type": "integer"}, {"type": "boolean"}]}}}
    _, message = describe(_error(any_of, {"x": PRIVATE}))
    assert "'anyOf'" in message and "at least one" in message and "secret" not in message


def test_source_region_error_names_the_normalized_format():
    from drawing2cad_mcp.measurements_tools import MEASUREMENT_SCHEMAS
    reference = {"dimension_id": PRIVATE, "printed_value_mm": 20, "p0": [1, 1], "p1": [1, 1],
                 "source_region": [0.1, 0.2, 7.5, 0.4], "evidence": "printed_dimension"}
    errors = list(Draft202012Validator(MEASUREMENT_SCHEMAS["pdf_calibrate"]).iter_errors(
        {"path": PRIVATE, "page": 1, "references": [reference, reference]}))
    target, message = describe(errors[0])
    assert target == "/references/0/source_region/2"
    assert "[left, top, right, bottom] as fractions 0..1 of the displayed page" in message
    assert "7.5" not in message and "secret" not in message


def test_input_object_keys_are_masked_in_targets():
    from drawing2cad_mcp.schema_errors import describe_all
    schema = {"type": "object", "properties": {"changes": {"type": "object", "additionalProperties": {"type": "number"},
                                                           "properties": {"known": {"type": "number"}}}}}
    defects, total = describe_all(Draft202012Validator(schema), {"changes": {"SecretToken": "x", "known": "y"}})
    assert total == 2
    targets = {item["target"] for item in defects}
    assert targets == {"/changes/*", "/changes/known"}
    assert all("SecretToken" not in item["message"] for item in defects)


def test_semantic_defects_survive_the_defect_limit():
    from drawing2cad_mcp.schema_errors import describe_all, summary
    schema = {"type": "object", "properties": {f"f{i}": {"type": "number"} for i in range(15)}}
    defects, total = describe_all(Draft202012Validator(schema), {f"f{i}": "x" for i in range(15)},
                                  extra=[("/references/0/p1", "The reference endpoints p0 and p1 are equal.")])
    assert total == 16 and len(defects) == 10
    assert defects[1]["target"] == "/references/0/p1"
    assert "first 10 of 16" in summary(defects, total)


def test_masked_keys_keep_one_defect_for_each_invalid_field():
    from drawing2cad_mcp.schema_errors import describe_all
    schema = {"type": "object", "properties": {"changes": {"type": "object", "additionalProperties": {"type": "number"}}}}
    defects, total = describe_all(Draft202012Validator(schema), {"changes": {"KeyA": "x", "KeyB": "y"}})
    assert total == 2 and [item["target"] for item in defects] == ["/changes/*", "/changes/*"]


def test_only_the_two_calibration_references_get_semantic_checks():
    from drawing2cad_mcp.measurements import calibration_defects
    equal = {"p0": [1, 1], "p1": [1, 1]}
    assert len(calibration_defects([equal] * 20)) == 2


def test_generic_anyof_feedback_does_not_append_schema_descriptions():
    schema = {"anyOf": [{"type": "integer"}, {"type": "boolean"}],
              "description": "Supply one of the permitted forms."}
    _, message = describe(_error(schema, {"description": PRIVATE}))
    assert "at least one permitted form must match" in message
    assert schema["description"] not in message and "secret" not in message
