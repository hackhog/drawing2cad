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


def pointer(error: ValidationError, prefix: str = "") -> str:
    """Return the JSON Pointer of the invalid field. The root is the empty string.
    The prefix locates a nested object that was validated separately, for example "/arguments"."""
    return prefix + "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in error.absolute_path)


def describe(error: ValidationError, prefix: str = "") -> tuple[str, str]:
    """Return (JSON Pointer, message). The message names the schema rule, never the input value."""
    target = pointer(error, prefix)
    location = target or "the argument root"
    rule = str(error.validator)
    if rule == "required" and isinstance(error.instance, dict):
        # Property names come from the schema.
        missing = [name for name in error.validator_value if name not in error.instance]
        # Point to the first missing property, so that the target names a field to add.
        field = target + "/" + str(missing[0]).replace("~", "~0").replace("/", "~1") if missing else target
        return field, f"The object at {location} fails the schema rule 'required': it lacks the properties {missing}."
    if rule == "additionalProperties":
        return target, f"The object at {location} fails the schema rule 'additionalProperties': it contains a property that the schema does not permit."
    if rule == "oneOf":
        return target, f"The value at {location} fails the schema rule 'oneOf': exactly one permitted form must match."
    if rule == "anyOf":
        return target, f"The value at {location} fails the schema rule 'anyOf': at least one permitted form must match."
    message = f"The value at {location} fails the schema rule '{rule}'."
    if rule in _SHOWN:
        expected = json.dumps(error.validator_value, ensure_ascii=False, default=str)
        if len(expected) <= _MAX_EXPECTED:
            message += f" Expected: {expected}."
    return target, message


__all__ = ["describe", "pointer"]
