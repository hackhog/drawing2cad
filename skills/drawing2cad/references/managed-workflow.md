# Managed evidence tools

Read the live schemas before a call. This reference applies to MCP package 0.4.
All paths are absolute. Sources must be in configured allowed roots.
The configured output root is also permitted for generated evidence and STEP candidates.
The server verifies actual bytes against supplied SHA-256 values.

## Scope

The workflow service stores revisioned evidence under the configured output root.
It enforces evidence order, schemas, hashes, and dependencies.
It does not create drawings, inspect sheet content, execute CAD, or certify geometry.
A review is an identified attestation. The server cannot prove that a person or agent inspected the image.
The structural model contract does not implement expressions, sketch constraints, or backend operations.

Use `cad_capabilities({})` to identify these limits.
The build, model comparison, and export readiness checks return `CAD_VALIDATION_UNAVAILABLE`.
Keep that result. Do not replace it with a supplied success flag.

## Call sequence

1. Call `workflow_create_run` with a unique `run_id`, mode, units, and source entries.
   Each source has `path`, `sha256`, and `role`.
   Roles are `construction_source`, `verification_only`, or `tool_reference`.
   Creation does not inspect CAD content or isolate worker inputs.
2. Call `workflow_observe` with observations and uncertainties.
   An observation has `id`, `source_sha256`, `location`, and `text`.
   Observations must use construction sources.
   An uncertainty has an ID, status, mandatory flag, description, target, marker ID, and evidence IDs.
   An approved assumption needs a decision reference. It remains an assumption.
   This call replaces the inventory and invalidates dependent drawing, review, and contract data.
3. After a verified authoring tool creates the sheet, call `workflow_register_drawing`.
   Supply drawing ID, revision, editable artifact, render artifact, units, and dimension IDs.
   Each artifact has `path` and `sha256`.
   File registration does not prove dimensions or marker visibility.
4. Inspect the sheet and call `workflow_review_drawing`.
   Supply drawing revision, reviewer identity, inspected render hash, findings, and notes.
   A finding has code, severity, target, message, and required action.
   Severity is `blocking` or `warning`. No caller-supplied `passed` field is accepted.
5. Call `workflow_fix_contract` with a unique contract revision and typed contract.
   The contract contains units, drawing revision, parameters, and operations.
   A parameter contains `id`, numeric `value`, and `dimension_id`.
   An operation contains `id`, `type`, `depends_on`, and `parameter_ids`.
   The server checks references and the dependency graph. An operation type is not a capability claim.
   The stored contract hash also binds the exact reviewed drawing artifacts.
6. Call `workflow_check_readiness` for the next phase.
   Inspect `ready`, every defect, and `next_action`.
   CAD-dependent readiness cannot pass in the current service.

Every mutation after creation requires `expected_state_revision`.
Take this number from the last returned run. Readiness checks do not change it.
Use `workflow_read_run` after a lost response or restart.
Do not retry an old mutation with a guessed revision.
Creation rejects an existing run ID. Mutations with stale revisions fail without a second event.

Example readiness request:

```json
{"run_id":"example-run","phase":"build"}
```

The example supplies no part dimensions or evidence.
It returns a missing-run error unless that run exists.
Do not create evidence to make an unavailable CAD gate pass.

## Review and revision handling

Required unresolved data block the drawing review and contract.
Record the source and location of each uncertainty before requesting a decision.
Do not use an existing verification STEP as an undeclared construction source.
For a changed sheet, register a new revision and repeat review.
For changed observations, replace the inventory and repeat all dependent phases.
Preserve old files if the historical review must remain reproducible.

The state store uses atomic replacement and a lock for each run.
Separate service instances share that lock.
The store is bounded and validates records when it loads them.
It is not an audit service with authenticated reviewer identities or external tamper protection.
The existing source file hashes remain fixed; a changed source requires a new run.

`import_step` does not have a managed reconstruction path in this service.
Do not use a drawing from outside STEP to fill missing construction data.
See [drawing-first.md](drawing-first.md) for the intended isolated reconstruction tests.

## STEP tools

Each call requires `path` and `expected_sha256`. Use the exact-byte hash, including line endings.
The default file limit is 32 MiB. The server can configure it.

| Tool | Additional inputs | Interpretation |
|---|---|---|
| `step_inspect` | None | Bounded P21 syntax, references, entity inventory, and source identity. Not EXPRESS or geometric validation. |
| `step_read_procedural` | None | Declared construction subset: millimeters, rectangles along +Z, full circles along +Z/+X, refined Booleans, and anchored constant-radius fillets. Returns data; does not build shapes. |
| `step_read_pmi` | Optional `expected_count` | Nominal sizes, distances, angles, supported thread/radius properties, associations, and tessellated polylines. Tolerance and datum systems are unsupported. |
| `step_read_review_properties` | `expected_schemas` | Checks the declared application envelope identifiers. Does not validate all payload semantics or geometry anchors. |
| `step_append_review_properties` | `output_name`, `properties` | Appends application metadata to a new candidate. Refuses an existing output or property. Preserves source records. |

The two envelope names and schema IDs are:

- `drawing2cad.editable_ui.v1`: `drawing2cad.editable-ui/1`.
- `drawing2cad.review_annotations.v1`: `drawing2cad.review-annotations/1`.

These are application metadata, separate from standard semantic PMI.
Appending them does not create a construction graph, validate their targets, or pass an export gate.
Read back the new candidate and repeat all affected release checks.

## Optional development proxy

Raw backend tools are hidden by default.
A deployment can explicitly set `server.expose_freecad_proxy=true` for the existing FreeCAD profile.
This also requires a configured upstream.
The same MCP then advertises `freecad_*` tools with their upstream schemas.
They bypass managed evidence gates and can execute arbitrary upstream Python.
This is an explicit development mode, not global workflow enforcement.
Do not enable it to conceal a missing domain capability.
