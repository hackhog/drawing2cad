# Maintained part workflow

This reference describes the M1 part service.
Use the live schemas for exact argument types, limits, and required fields.
The installed server can differ from the skill version.

## Discovery and validation

Call `drawing2cad_status`, `cad_capabilities`, and `cad_worker_probe`.
If the sandbox probe fails, stop the CAD workflow.
The service requires a passing probe before free-code execution; declarative builds also require the supported sandbox.
Do not replace it with a raw backend call.

Call `part_schema` to read the closed versioned schema.
Call `part_validate` with `description`.
The description contains units, coordinates, stable parameters and features, source evidence, review records, and independent measurements.
Use only operations and parameter references accepted by the schema.
Unknown fields, unsupported operations, invalid references, and nonfinite values require correction.

A parameter must have evidence.
An assumed value needs a reason and a source region.
Keep `explicit`, `derived`, `inferred`, `assumed`, and `unresolved` distinct.
Use a supported closed review status.
A reasonable geometric assumption can support construction without a new user question.
An unresolved value that prevents a reasonable build remains a blocker.

## Construction and revisions

| Tool | Use |
|---|---|
| `part_create` | Supply `run_id`, `description`, and `sources`. Each source has `path`, `sha256`, and `role` (`construction` or `verification`). |
| `part_read` | Supply `run_id`; read the description, revision, results, and budget. This call is recorded. Audit access remains available after the execution budget is reached. |
| `part_update` | Supply `run_id`, `expected_revision`, and the changed `description`. Prior builds and releases become stale. |
| `create_base_body` | Add a supported box, cylinder, polygon extrusion, or closed line-and-arc profile extrusion. |
| `add_hole` | Add a through or blind hole, with supported countersink, counterbore, or thread data. |
| `add_pocket`, `add_cut` | Add a supported material-removal feature. |
| `add_chamfer`, `add_fillet` | Apply edge treatment with a bounded selector and expected selection count. |
| `build_from_description` | Build the stored description, export a candidate, and re-import in a separate worker. It does not release the candidate. |
| `build_code` | Optional in-memory execution within the separately verified sandbox scope. |

Read the current revision before a mutation.
Model edits increment the revision and invalidate prior builds and releases.
Supply `run_id` and `expected_revision` for each mutation.
Granular calls also take a typed `feature`.
`build_code` takes an in-memory `code` string and must assign the resulting build123d shape to `result`.
The namespace supplies `build123d` and a separate copy of the current `description`.
Read named parameters from that description. Do not keep a second set of unlinked model values in code.
Changes to this copy cannot change the trusted validation description.
Free-code output has separate geometry validation; feature replay remains unverified.
Retain the exact inline payload in the event trace.
To test a parameter change, update the description and rerun that payload.
JSON alone cannot replay construction that exists only in the inline payload.
Do not substitute `build_from_description` and claim equivalent replay without a separate comparison.
After a lost response, read state before another call.
Do not repeat an old mutation with a guessed revision.
Keep mutations to the same part in sequence.
The server counts part-service calls against its run budget.
After the budget is reached, `part_read` and `part_export_review` remain available for audit.
These calls cannot enable more construction or release operations.
Reserve calls for candidate release and report export.
The agent separately tracks the overall budget, including PDF preparation, discovery, and retries.

The description is the editable source for the declarative M1 path.
Changing a stored number alone does not prove editability.
Rebuild the changed description and measure the intended geometric effects.
Scalar references update their direct uses. The prototype does not have an algebraic constraint solver.
Derived profile points and edge selectors can require coordinated edits after a dimension change.

Closed profiles can contain straight lines and three-point circular arcs.
Extrusions support a bounded draft angle. Blind holes can include an explicit drill-tip angle.
The blind depth is the cylindrical depth; the conical tip extends beyond it.

Geometry checks include cylindrical diameters and lengths, circular edges, cone angle and width,
axis spacing, parallel-plane spacing, planar draft angles, and straight-edge angles.
`section_distance` measures two trimmed planar faces along one line. It can measure a drafted rib at a selected height.
Both anchors must lie on that line. `surface_radius` measures a cylindrical face near its surface anchor, including a trimmed fillet.
Do not use an axis-center anchor for `surface_radius`.

For a hole opening check, supply source-derived `entry_position` and an axis that points into the part.
The entry must lie on the measured hole axis.
The entry check supports connected full concave cylinders, cones, and planar shoulders at a planar circular opening.
Toroidal lips and partial or noncircular transitions are outside this check.
If `entry_position` is omitted, `entry_side` remains `not_tested`.
A cylindrical diameter/depth pass alone does not prove the correct entry side.

Thread data in M1 describe a tap-drill representation and thread attributes.
They do not prove modeled helical flanks or semantic thread PMI in STEP.

## Validation, export, and reports

Inspect the returned build status and each measurement.
Feature creation is not proof that the intended source feature was interpreted correctly.
Compare actual geometry with independent drawing expectations.
Use [validation.md](validation.md) for separate claims.

The build creates a candidate and runs fresh-worker re-import before release.
`export_step` requires `run_id`, `expected_revision`, and `coverage`.
Coverage identifies the reviewer, source hashes, view/feature/printed-dimension totals and reviewed counts, and critical measurement IDs.
Include the reason for the review conclusion.
The service verifies the evidence structure; the attestation does not prove that the reviewer interpreted every source correctly.
Keep a separate inventory that links each printed callout to its geometry check.
The reviewer must also check features that do not have dimensions, such as a visible web or a drill tip.
Do not replace a failed local check with a bounding-box check that does not measure the same feature.

Release requires trusted re-import, passing source-dimension checks, and complete source-review coverage.
Record the actual AP214 schema, units, product identity, and geometry.
A passed re-import does not prove STEP-only feature reconstruction.

Call `part_export_review` for review records, coverage, manifest, and event evidence.
Keep unexecuted NX, independent conformance, model comparison, and PMI tests as `not_tested`.
A successful server operation is not a complete metric pass when required external checks are missing.

## Legacy evidence and STEP tools

The `workflow_*` tools retain a separate legacy evidence profile.
They are hidden by default; `server.expose_legacy_workflow=true` explicitly enables that development profile.
They register structural evidence, revisions, and review attestations.
They do not execute CAD or replace the part service's build/export validation.
Do not use a caller-supplied attestation as measured geometry.

The bounded STEP readers remain useful for inspection:

- `step_inspect`: syntax, references, and entity inventory.
- `step_read_procedural`: the declared construction subset.
- `step_read_pmi`: supported nominal dimensions and associations.
- `step_read_review_properties`: application metadata envelopes.
- `step_append_review_properties`: metadata in a separate candidate.

These tools use an authorized path and its exact-byte `expected_sha256`.
Their parsing success does not prove geometry, full EXPRESS conformity, or general PMI support.
A metadata append is not CAD export or semantic-PMI authoring.

Historical FreeCAD inline adapters are unavailable through the current MCP.
Do not load them for the current tool sequence.
