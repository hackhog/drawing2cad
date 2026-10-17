"""Typed inputs for the managed evidence workflow. These tools do not execute CAD."""


def _object(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False}


def _array(items, *, minimum=0, maximum=1000):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


TEXT = {"type": "string", "minLength": 1, "maxLength": 4000}
ID = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$"}
HASH = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
UNITS = {"enum": ["mm", "cm", "m", "in"]}
ARTIFACT = _object({"path": TEXT, "sha256": HASH})
SOURCE = _object({"path": TEXT, "sha256": HASH,
                  "role": {"enum": ["construction_source", "verification_only", "tool_reference"]}})
OBSERVATION = _object({"id": ID, "source_sha256": HASH, "location": TEXT, "text": TEXT})
UNCERTAINTY = _object({"id": ID, "status": {"enum": ["unresolved", "approved_assumption", "resolved"]},
                       "mandatory": {"type": "boolean"}, "description": TEXT, "target": TEXT,
                       "marker_id": ID, "evidence_ids": _array(ID, minimum=1), "decision_ref": TEXT},
                      ["id", "status", "mandatory", "description", "target", "marker_id", "evidence_ids"])
FINDING = _object({"code": ID, "severity": {"enum": ["blocking", "warning"]},
                   "target": TEXT, "message": TEXT, "required_action": TEXT})
PARAMETER = _object({"id": ID, "value": {"type": "number"}, "dimension_id": ID})
OPERATION = _object({"id": ID, "type": ID, "depends_on": _array(ID), "parameter_ids": _array(ID)})
CONTRACT = _object({"units": UNITS, "drawing_revision": ID,
                    "parameters": _array(PARAMETER, minimum=1),
                    "operations": _array(OPERATION, minimum=1)})
PHASES = ["observe", "drawing_prepare", "drawing_review", "freeze", "build", "drawing_model_check", "export"]
MUTATION = {"run_id": ID, "expected_state_revision": {"type": "integer", "minimum": 0}}

WORKFLOW_SCHEMAS = {
    "workflow_create_run": _object({"run_id": ID,
        "mode": {"enum": ["new_drawing", "replay_contract", "import_step", "edit_model"]},
        "sources": _array(SOURCE, minimum=1), "units": UNITS}),
    "workflow_read_run": _object({"run_id": ID}),
    "workflow_observe": _object({**MUTATION, "observations": _array(OBSERVATION, minimum=1),
                                  "uncertainties": _array(UNCERTAINTY)}),
    "workflow_register_drawing": _object({**MUTATION, "drawing_id": ID, "revision": ID,
        "editable": ARTIFACT, "render": ARTIFACT, "dimension_ids": {**_array(ID, minimum=1), "uniqueItems": True},
        "units": UNITS}),
    "workflow_review_drawing": _object({**MUTATION, "drawing_revision": ID, "reviewer": TEXT,
        "inspected_render_sha256": HASH, "findings": _array(FINDING), "notes": TEXT}),
    "workflow_fix_contract": _object({**MUTATION, "revision": ID, "contract": CONTRACT}),
    "workflow_check_readiness": _object({"run_id": ID, "phase": {"enum": PHASES}}),
}

WORKFLOW_DESCRIPTIONS = {
    "workflow_create_run": "Create a persistent managed evidence run from authorized source hashes. No CAD execution.",
    "workflow_read_run": "Read durable revisions, review attestations, uncertainties and managed evidence limits.",
    "workflow_observe": "Replace the evidence inventory and review register. Invalidate dependent drawing, review and contract state.",
    "workflow_register_drawing": "Register an editable technical sheet and readable render by actual file hashes. This is structural evidence, not CAD validation.",
    "workflow_review_drawing": "Record an identified review attestation tied to the exact drawing render. Compute the structural review gate from findings.",
    "workflow_fix_contract": "Fix a typed declarative contract from the reviewed drawing. Validate units, dimension mappings and operation DAG, not CAD support.",
    "workflow_check_readiness": "Inspect prerequisite defects and next action. Build, model comparison and export remain unavailable without a verified CAD backend.",
}
