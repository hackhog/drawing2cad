"""Typed tool inputs for the maintained STEP metadata adapters."""

SOURCE = {
    "path": {"type": "string", "minLength": 1, "description": "Absolute path to an authorized STEP file inside an allowed root."},
    "expected_sha256": {"type": "string", "pattern": "^[0-9a-fA-F]{64}$", "description": "Expected SHA-256 of the exact source bytes."},
}
REVIEW_SCHEMAS = {
    "drawing2cad.editable_ui.v1": "drawing2cad.editable-ui/1",
    "drawing2cad.review_annotations.v1": "drawing2cad.review-annotations/1",
}
SCHEMA_MAP = {"type": "object", "minProperties": 1, "maxProperties": 2,
              "properties": {name: {"const": schema} for name, schema in REVIEW_SCHEMAS.items()},
              "additionalProperties": False}
PROPERTIES = {"type": "object", "minProperties": 1, "maxProperties": 2,
              "properties": {name: {"type": "object", "properties": {"schema": {"const": schema}},
                                     "required": ["schema"]} for name, schema in REVIEW_SCHEMAS.items()},
              "additionalProperties": False}


def schema(extra=None, required=()):
    return {"type": "object", "properties": {**SOURCE, **(extra or {})},
            "required": [*SOURCE, *required], "additionalProperties": False}


STEP_SCHEMAS = {
    "step_inspect": schema(),
    "step_read_procedural": schema(),
    "step_read_pmi": schema({"expected_count": {"type": "integer", "minimum": 0, "maximum": 100000}}),
    "step_read_review_properties": schema({"expected_schemas": SCHEMA_MAP}, ["expected_schemas"]),
    "step_append_review_properties": schema({
        "output_name": {"type": "string", "maxLength": 128, "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]*\\.(?:step|stp)$"},
        "properties": PROPERTIES,
    }, ["output_name", "properties"]),
}
STEP_DESCRIPTIONS = {
    "step_inspect": "Inspect bounded STEP syntax, entity counts, and exact source hash. No CAD kernel, geometry validation, or EXPRESS validation.",
    "step_read_procedural": "Decode the maintained millimeter procedural subset: +Z boxes, +Z/+X full-circle extrusions, refined Booleans, and anchored constant-radius fillets. Returns declarative operations; does not rebuild geometry.",
    "step_read_pmi": "Read nominal size, distance, and angle PMI, thread designations, positive radius properties, associations, and tessellated polylines. Tolerance and datum systems are unsupported. Does not author PMI.",
    "step_read_review_properties": "Read the two supported application review/UI metadata envelopes with exact schema identifiers. Does not validate geometry anchors or infer original drawing PMI.",
    "step_append_review_properties": "Append application review/UI metadata to a separate STEP candidate. Preserve source bytes and entities. Refuse existing properties and output files. This edits metadata; it is not CAD or semantic-PMI export.",
}
