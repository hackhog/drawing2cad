"""Stable MCP tool contracts for the M1 part service."""

from copy import deepcopy

_ID = {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$"}
_HASH = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
_RUN = {"run_id": _ID}
_REVISION = {**_RUN, "expected_revision": {"type": "integer", "minimum": 1}}
_PART = {"type": "object", "minProperties": 6, "maxProperties": 12,
         "description": "A part description that conforms to the full contract returned by part_schema."}
_FEATURE = {"type": "object", "minProperties": 3, "maxProperties": 16,
            "required": ["id", "type", "evidence_ids"], "properties": {
                "id": _ID, "type": {"enum": ["box", "cylinder", "extrusion", "profile_extrusion", "hole", "pocket", "cut", "chamfer", "fillet"]},
                "evidence_ids": {"type": "array", "items": _ID, "minItems": 1, "maxItems": 100}},
            "description": "A feature that conforms to the matching type in part_schema. The service validates every field."}
_SOURCE = {"type": "object", "additionalProperties": False, "required": ["path", "sha256", "role"], "properties": {
    "path": {"type": "string", "minLength": 1, "maxLength": 4096}, "sha256": _HASH,
    "role": {"enum": ["construction", "verification"]}, "source_id": {"type": "string", "minLength": 1, "maxLength": 200},
}}
_COUNT = {"type": "object", "additionalProperties": False, "required": ["total", "reviewed"], "properties": {
    "total": {"type": "integer", "minimum": 1, "maximum": 10000}, "reviewed": {"type": "integer", "minimum": 0, "maximum": 10000},
}}
_COVERAGE = {"type": "object", "additionalProperties": False, "required": ["reviewer", "source_hashes", "views", "features", "printed_dimensions", "critical_measurement_ids", "reason"], "properties": {
    "reviewer": {"type": "string", "minLength": 1, "maxLength": 200},
    "source_hashes": {"type": "array", "items": _HASH, "minItems": 1, "maxItems": 100, "uniqueItems": True},
    "views": _COUNT, "features": _COUNT, "printed_dimensions": _COUNT,
    "critical_measurement_ids": {"type": "array", "items": _ID, "minItems": 1, "maxItems": 1000, "uniqueItems": True},
    "reason": {"type": "string", "minLength": 1, "maxLength": 2000},
}}


def _object(properties, required=None):
    return {"type": "object", "additionalProperties": False, "properties": deepcopy(properties), "required": list(properties) if required is None else required}


CAD_SCHEMAS = {
    "part_schema": _object({}),
    "part_validate": _object({"description": {"type": "object", "maxProperties": 12}}),
    "part_create": _object({**_RUN, "description": _PART, "sources": {"type": "array", "items": _SOURCE, "minItems": 1, "maxItems": 100}, "step_budget": {"type": "integer", "minimum": 5, "maximum": 100}}, ["run_id", "description", "sources"]),
    "part_read": _object(_RUN),
    "part_update": _object({**_REVISION, "description": _PART}),
    "build_from_description": _object({**_REVISION,
        "export_profile": {"enum": ["ap214", "ap242"], "default": "ap214"},
        "pmi": {"type": "object", "description": "An AP242 PMI specification from pmi_schema. Unsupported or ambiguous associations fail."}}, list(_REVISION)),
    "pmi_schema": _object({}),
    "build_code": _object({**_REVISION, "code": {"type": "string", "minLength": 1, "maxLength": 65536}}),
    "export_step": _object({**_REVISION, "coverage": _COVERAGE}),
    "part_export_review": _object(_REVISION),
    "cad_worker_probe": _object({}),
}
for _name in ("create_base_body", "add_hole", "add_pocket", "add_cut", "add_chamfer", "add_fillet"):
    CAD_SCHEMAS[_name] = _object({**_REVISION, "feature": _FEATURE})

CAD_DESCRIPTIONS = {
    "pmi_schema": "Read the supported semantic PMI dimensions and geometric association contract. Target-CAD display and full EXPRESS conformance require separate tests.",
    "part_schema": "Read the closed, versioned JSON part contract and feature scope. Schema 1.3 includes source-bound manufacturing tolerances, separate from geometry-test tolerances. This does not execute CAD.",
    "part_validate": "Validate part structure, named values, evidence references, and unresolved inputs. No CAD geometry is created.",
    "part_create": "Create an M1 server-side part run from authorized PDF paths and exact hashes. Read part_schema for the complete description contract. source_id defaults to sha256. Verification sources cannot supply construction values.",
    "part_read": "Read current part, revision, build state, budget, and events. This call is recorded. Audit reads and report export remain available after the execution budget is reached.",
    "part_update": "Replace the editable JSON part description with an optimistic revision check. Return changed parameters, direct references, and potentially affected later features. Invalidate prior builds and releases. Rebuild to measure effects against the retained validated baseline. Printed expectations are not changed automatically.",
    "create_base_body": "Replace the first base body or append an additive box, cylinder, polygon, or line-and-arc profile extrusion. Schema 1.1 supports tapered cylinders. Positive taper reduces their radius along the signed axis. Read part_schema for the closed feature contract.",
    "add_hole": "Append a through, blind, counterbore, countersink, or tap-drill hole with evidence. Schema 1.2 and later permit explicit thread.length on a plain blind hole. The worker checks the attribute against the cylindrical tap-drill bore after construction and STEP re-import.",
    "add_pocket": "Append a bounded box, cylinder, polygon, or line-and-arc profile pocket with evidence. Schema 1.1 supports taper_angle. Positive taper reduces the cutter along its signed local axis. Read part_schema for coordinate rules.",
    "add_cut": "Append a bounded box, cylinder, polygon, or line-and-arc profile material cut with evidence. Schema 1.1 supports taper_angle. Positive taper reduces the cutter along its signed local axis. Read part_schema for coordinate rules.",
    "add_chamfer": "Append a chamfer using a geometric edge-center region and an exact expected edge count.",
    "add_fillet": "Append a fillet using a bounded edge-center region and an exact expected edge count. Schema 1.1 can restrict edges to an adjacent planar face. Empty or ambiguous selections fail. Use fillet_radius measurements to verify the resulting surfaces.",
    "build_from_description": "Build the ordered part graph in a restricted worker and re-import its STEP candidate in a separate worker. Supplied draft_angle and fillet_radius measurements test supported analytic surfaces with explicit tolerances. Default is AP214. AP242 embeds application-specific construction for the maintained adapter; it does not prove native target-CAD history. Does not release the candidate.",
    "build_code": "Use an explicitly enabled, tested sandbox fallback. The namespace supplies build123d and a copy of the current description. Code must assign a build123d Shape to result. A separate trusted worker validates the candidate. Feature replay remains unverified.",
    "export_step": "Release the selected STEP profile only after trusted re-import, source dimension checks, and a complete source-review attestation. AP242 adapter and PMI reports have separate scope; native target-CAD and independent conformance require additional tests.",
    "part_export_review": "Export the current JSON description, review list in Markdown and CSV, coverage, manifest, and complete recorded run trace.",
    "cad_worker_probe": "Test the worker restrictions, limits, crash handling, and recovery. A passing probe is required before build_code.",
}
CAD_METHODS = {name: name for name in CAD_SCHEMAS}
