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
    _, missing = describe(_error({**schema, "additionalProperties": True}, {}))
    assert "run_id" in missing
    _, extra = describe(_error(schema, {"run_id": "a", PRIVATE: 1}))
    assert "secret" not in extra


def test_root_pointer_is_empty_and_combinators_name_their_rule():
    target, message = describe(_error({"type": "object"}, PRIVATE))
    assert target == "" and "argument root" in message and "secret" not in message
    one = {"type": "object", "properties": {"x": {"oneOf": [{"type": "string"}, {"minLength": 1}]}}}
    target, message = describe(_error(one, {"x": "secret value"}))
    assert target == "/x" and "'oneOf'" in message and "exactly one" in message and "secret" not in message
    any_of = {"type": "object", "properties": {"x": {"anyOf": [{"type": "integer"}, {"type": "boolean"}]}}}
    _, message = describe(_error(any_of, {"x": PRIVATE}))
    assert "'anyOf'" in message and "at least one" in message and "secret" not in message
