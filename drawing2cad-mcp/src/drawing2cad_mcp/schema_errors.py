"""Describe JSON Schema errors without the input value.

The message of a jsonschema error repeats the invalid value. That value can be a private path or
another private input. The description below uses only the field location and the schema rule.
"""

from __future__ import annotations

import json

from jsonschema import ValidationError

# Rules whose expected value comes from the schema and is short enough to show.
_SHOWN = {"type", "enum", "const", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
          "minLength", "maxLength", "minItems", "maxItems", "multipleOf", "pattern", "format", "uniqueItems"}
_MAX_EXPECTED = 160


def pointer(error: ValidationError) -> str:
    """Return the JSON Pointer of the invalid field."""
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in error.absolute_path)


def describe(error: ValidationError) -> tuple[str, str]:
    """Return (JSON Pointer, message). The message names the schema rule, never the input value."""
    target = pointer(error)
    rule = str(error.validator)
    if rule == "required" and isinstance(error.instance, dict):
        # Property names come from the schema.
        missing = [name for name in error.validator_value if name not in error.instance]
        return target, f"The object at {target} lacks the required properties {missing}."
    if rule == "additionalProperties":
        return target, f"The object at {target} contains a property that the schema does not permit."
    if rule in {"oneOf", "anyOf"}:
        return target, f"The value at {target} matches none of the permitted forms."
    message = f"The value at {target} fails the schema rule '{rule}'."
    if rule in _SHOWN:
        expected = json.dumps(error.validator_value, ensure_ascii=False, default=str)
        if len(expected) <= _MAX_EXPECTED:
            message += f" Expected: {expected}."
    return target, message


__all__ = ["describe", "pointer"]
